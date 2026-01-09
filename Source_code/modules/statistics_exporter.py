"""統計データをExcel形式で出力するユーティリティ。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple, Dict, Any
import numbers

import pandas as pd

from .db_manager import MAIN_DB_PATH, configure_connection

try:  # Optional依存 - グラフ生成ではXlsxWriterを利用する
    from xlsxwriter.utility import xl_rowcol_to_cell

    _XLSXWRITER_AVAILABLE = True
except Exception:  # pragma: no cover - 実行環境でのみ判定
    xl_rowcol_to_cell = None  # type: ignore
    _XLSXWRITER_AVAILABLE = False

DOWNWARD_DIRECTIONS = {"B", "R"}
BIKE_KEYWORDS = ("bike", "bicyc", "cyclist")
DEFAULT_STATISTICS_DIR = os.path.join("output", "statistics")

STATISTICS_MODES: Dict[str, Dict[str, str]] = {
    "lane": {
        "label": "白線区分",
        "description": "白線内外(A/B)ごとの比較",
    },
    "lane_id": {
        "label": "白線距離(自転車ID別)",
        "description": "自転車のグループIDごとの白線距離集計",
    },
    "clearance": {
        "label": "離隔距離×速度",
        "description": "離隔距離帯ごとの距離と速度",
    },
    "track": {
        "label": "トラックID別 速度・白線距離",
        "description": "トラックIDごとの速度と白線距離の推移",
    },
}
DEFAULT_STATISTICS_MODE = "lane"


def _coerce_run_ids(values: Sequence[int | str]) -> list[int]:
    run_ids: list[int] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        try:
            run_id = int(text)
        except ValueError:
            raise ValueError(f"Run ID '{value}' は整数に変換できません。") from None
        run_ids.append(run_id)
    return sorted(set(run_ids))


def _normalize_mode(mode: Optional[str]) -> str:
    if mode is None:
        return DEFAULT_STATISTICS_MODE
    key = str(mode).strip().lower()
    if not key:
        return DEFAULT_STATISTICS_MODE
    if key not in STATISTICS_MODES:
        valid = "、".join(sorted(STATISTICS_MODES))
        raise ValueError(f"サポートされていない集計モードです: {mode} (利用可能: {valid})")
    return key


def _load_detection_dataframe(run_ids: Sequence[int]) -> pd.DataFrame:
    if not run_ids:
        raise ValueError("Run ID を一つ以上指定してください。")

    placeholders = ",".join("?" for _ in run_ids)
    query = f"""
        SELECT d.auto_id,
               d.run_id,
               d.group_id,
               d.track_id,
               d.frame_num,
               d.speed_km_h,
               d.clearance_distance_cm,
               d.clearance_distance_m,
               d.approach_distance_m,
               d.travel_direction,
               d.lane_position_flag,
               d.line_distance,
               d.l_line_distance,
               d.r_line_distance,
               c.class_name,
               p.output_folder,
               p.folder_alias,
               v.filename
        FROM Detection d
        JOIN ProcessLog p ON d.run_id = p.run_id
        JOIN Video v ON d.video_id = v.video_id
        LEFT JOIN Class c ON d.class_id = c.class_id
        WHERE d.run_id IN ({placeholders})

    """

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        df = pd.read_sql_query(query, conn, params=list(run_ids))

    if df.empty:
        return df

    # 旧バージョンのDBでは line_distance が存在しない/NULL の場合があるため補完する
    nullable_float = "Float64"
    index = df.index

    if "line_distance" in df.columns:
        line_series = pd.to_numeric(df["line_distance"], errors="coerce")
    else:
        line_series = pd.Series(pd.NA, index=index, dtype=nullable_float)

    if "l_line_distance" in df.columns:
        left_series = pd.to_numeric(df["l_line_distance"], errors="coerce")
    else:
        left_series = pd.Series(pd.NA, index=index, dtype=nullable_float)

    if "r_line_distance" in df.columns:
        right_series = pd.to_numeric(df["r_line_distance"], errors="coerce")
    else:
        right_series = pd.Series(pd.NA, index=index, dtype=nullable_float)

    fallback = pd.concat([left_series, right_series], axis=1, keys=["left", "right"])
    fallback_min = fallback.min(axis=1, skipna=True)

    df["line_distance"] = line_series.combine(
        fallback_min,
        lambda base, alt: float(alt) if (pd.isna(base) and not pd.isna(alt)) else base,
    )

    return df


def _filter_bicycle_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    class_series = df["class_name"].fillna("").astype(str).str.lower()
    mask = pd.Series(False, index=df.index)
    for keyword in BIKE_KEYWORDS:
        mask = mask | class_series.str.contains(keyword)
    return df[mask].copy()


def _mean(series: pd.Series) -> Optional[float]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(round(numeric.mean(), 3))


def _median(series: pd.Series) -> Optional[float]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(round(numeric.median(), 3))


def _most_common(series: pd.Series) -> Optional[str]:
    cleaned = series.dropna()
    if cleaned.empty:
        return None
    mode = cleaned.mode()
    if mode.empty:
        return None
    return str(mode.iloc[0])


def _determine_output_directory(
    df: pd.DataFrame,
    explicit_dir: Optional[str] = None,
) -> str:
    if explicit_dir:
        base_dir = os.path.abspath(explicit_dir)
    else:
        candidates = [
            os.path.abspath(os.path.normpath(path))
            for path in df.get("output_folder", pd.Series(dtype=str)).dropna().tolist()
            if str(path).strip()
        ]
        if candidates:
            try:
                base_dir = os.path.commonpath(candidates)
            except ValueError:
                base_dir = candidates[0]
        else:
            base_dir = os.path.abspath(DEFAULT_STATISTICS_DIR)
    os.makedirs(base_dir, exist_ok=True)
    return base_dir


def _sanitize_sheet_name(name: str) -> str:
    invalid_chars = set('[]:*?/\\')
    filtered = ''.join('_' if ch in invalid_chars else ch for ch in name)
    filtered = filtered.strip()
    if not filtered:
        filtered = "Sheet"
    return filtered[:31]


def _column_letter(index: int) -> str:
    letters = ""
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters or "A"


def _build_sheet_xml(rows: List[List[object]]) -> str:
    from xml.sax.saxutils import escape

    xml_rows: List[str] = []
    for row_idx, row in enumerate(rows, start=1):
        cells: List[str] = []
        for col_idx, value in enumerate(row, start=1):
            if value is None:
                continue
            cell_ref = f"{_column_letter(col_idx)}{row_idx}"
            if isinstance(value, numbers.Real) and not isinstance(value, bool):
                if pd.isna(value):
                    continue
                cells.append(f'<c r="{cell_ref}"><v>{float(value)}</v></c>')
            else:
                text = escape(str(value))
                cells.append(
                    f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>'
                )
        if cells:
            xml_rows.append(f"<row r=\"{row_idx}\">{''.join(cells)}</row>")
        else:
            xml_rows.append(f"<row r=\"{row_idx}\"/>")
    sheet_data = "".join(xml_rows)
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
        f"<sheetData>{sheet_data}</sheetData>"
        "</worksheet>"
    )


def _write_simple_xlsx(path: str, sheets: List[Tuple[str, List[List[object]]]]) -> None:
    from zipfile import ZipFile, ZIP_DEFLATED
    from xml.sax.saxutils import escape

    sheet_names = [_sanitize_sheet_name(name) for name, _ in sheets]
    sheet_xml_parts = [_build_sheet_xml(rows) for _, rows in sheets]

    content_types = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">",
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>",
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>",
        "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>",
        "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>",
    ]
    for idx in range(len(sheets)):
        content_types.append(
            f"<Override PartName=\"/xl/worksheets/sheet{idx + 1}.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
        )
    content_types.append("</Types>")
    content_types_xml = "".join(content_types)

    relationships_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/>"
        "</Relationships>"
    )

    sheets_xml = "".join(
        f"<sheet name=\"{escape(name)}\" sheetId=\"{idx}\" r:id=\"rId{idx}\"/>"
        for idx, name in enumerate(sheet_names, start=1)
    )
    workbook_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        f"<sheets>{sheets_xml}</sheets>"
        "</workbook>"
    )

    relations = [
        f"<Relationship Id=\"rId{idx}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet{idx}.xml\"/>"
        for idx in range(1, len(sheets) + 1)
    ]
    relations.append(
        f"<Relationship Id=\"rId{len(sheets) + 1}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>"
    )
    workbook_rels_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        + "".join(relations)
        + "</Relationships>"
    )

    styles_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
        "<fonts count=\"1\"><font><sz val=\"11\"/><name val=\"Calibri\"/></font></fonts>"
        "<fills count=\"1\"><fill><patternFill patternType=\"none\"/></fill></fills>"
        "<borders count=\"1\"><border/></borders>"
        "<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>"
        "<cellXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/></cellXfs>"
        "<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>"
        "</styleSheet>"
    )

    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", relationships_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/styles.xml", styles_xml)
        for idx, xml in enumerate(sheet_xml_parts, start=1):
            archive.writestr(f"xl/worksheets/sheet{idx}.xml", xml)


def _write_with_xlsxwriter(
    path: str,
    summary_metadata: List[List[object]],
    summary_headers: List[object],
    summary_table_rows: List[List[object]],
    summary_chart_rows: List[List[object]],
    per_run_df: pd.DataFrame,
    detail_df: pd.DataFrame,
    *,
    mode: str,
    chart_empty_message: str,
) -> bool:
    """XlsxWriterを用いてExcelを書き込み、グラフシートも併せて生成する。"""

    if not _XLSXWRITER_AVAILABLE:
        raise RuntimeError(
            "XlsxWriter がインストールされていないためグラフを含むExcelを生成できません。"
        )

    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        workbook = writer.book

        header_format = workbook.add_format({"bold": True, "bg_color": "#D9E1F2"})
        meta_format = workbook.add_format({"bold": True})
        summary_ws = workbook.add_worksheet("概要")
        writer.sheets["概要"] = summary_ws

        current_row = 0
        for row in summary_metadata:
            summary_ws.write_row(current_row, 0, row, meta_format if row else None)
            current_row += 1

        current_row += 1  # 空行
        header_row_idx = current_row
        summary_ws.write_row(header_row_idx, 0, summary_headers, header_format)
        current_row += 1

        for row in summary_table_rows:
            summary_ws.write_row(current_row, 0, row)
            current_row += 1

        summary_ws.set_column(0, 0, 18)
        summary_ws.set_column(1, len(summary_headers) - 1, 20)
        summary_ws.freeze_panes(header_row_idx + 1, 0)

        per_run_df.to_excel(writer, sheet_name="Run別集計", index=False)
        per_run_ws = writer.sheets["Run別集計"]
        per_run_ws.freeze_panes(1, 0)
        if not per_run_df.empty:
            per_run_ws.autofilter(0, 0, per_run_df.shape[0], per_run_df.shape[1] - 1)

        detail_df.to_excel(writer, sheet_name="詳細データ", index=False)
        detail_ws = writer.sheets["詳細データ"]
        detail_ws.freeze_panes(1, 0)
        if not detail_df.empty:
            detail_ws.autofilter(0, 0, detail_df.shape[0], detail_df.shape[1] - 1)

        graph_ws = workbook.add_worksheet("グラフ")
        writer.sheets["グラフ"] = graph_ws
        mode_info = STATISTICS_MODES.get(mode, {})
        graph_title = f"{mode_info.get('label', '集計')}の統計グラフ"
        graph_ws.write("A1", graph_title)
        graph_ws.write("A2", "※「概要」シートの集計値を元に自動生成されています。")

        chart_created = False
        if summary_chart_rows:
            assert xl_rowcol_to_cell is not None  # 型チェックのため
            data_start_row = header_row_idx + 1
            data_end_row = data_start_row + len(summary_chart_rows) - 1

            def _range(col: int) -> str:
                start = xl_rowcol_to_cell(data_start_row, col, row_abs=True, col_abs=True)
                end = xl_rowcol_to_cell(data_end_row, col, row_abs=True, col_abs=True)
                return f"='概要'!{start}:{end}"

            categories_range = _range(0)
            header_index = {name: idx for idx, name in enumerate(summary_headers)}

            inserted_any = False
            if mode == "lane":
                speed_idx = header_index.get("平均速度(km/h)")
                clearance_idx = header_index.get("離隔時平均距離(cm)")
                lane_idx = header_index.get("平均白線距離(m)")

                if speed_idx is not None:
                    speed_chart = workbook.add_chart({"type": "column"})
                    speed_chart.add_series(
                        {
                            "name": "平均速度(km/h)",
                            "categories": categories_range,
                            "values": _range(speed_idx),
                            "data_labels": {"value": True},
                        }
                    )
                    speed_chart.set_title({"name": "白線区分別 平均速度"})
                    speed_chart.set_x_axis({"name": "区分"})
                    speed_chart.set_y_axis({"name": "km/h"})
                    speed_chart.set_style(2)
                    graph_ws.insert_chart("A4", speed_chart, {"x_offset": 10, "y_offset": 10})
                    inserted_any = True

                if clearance_idx is not None:
                    clearance_chart = workbook.add_chart({"type": "column"})
                    clearance_chart.add_series(
                        {
                            "name": "離隔時平均距離(cm)",
                            "categories": categories_range,
                            "values": _range(clearance_idx),
                            "data_labels": {"value": True},
                        }
                    )
                    clearance_chart.set_title({"name": "白線区分別 離隔距離"})
                    clearance_chart.set_x_axis({"name": "区分"})
                    clearance_chart.set_y_axis({"name": "cm"})
                    clearance_chart.set_style(3)
                    graph_ws.insert_chart("H4", clearance_chart, {"x_offset": 10, "y_offset": 10})
                    inserted_any = True

                if lane_idx is not None:
                    lane_chart = workbook.add_chart({"type": "line"})
                    lane_chart.add_series(
                        {
                            "name": "平均白線距離(m)",
                            "categories": categories_range,
                            "values": _range(lane_idx),
                            "data_labels": {"value": True},
                        }
                    )
                    lane_chart.set_title({"name": "白線区分別 白線距離"})
                    lane_chart.set_x_axis({"name": "区分"})
                    lane_chart.set_y_axis({"name": "m"})
                    lane_chart.set_style(12)
                    graph_ws.insert_chart("A20", lane_chart, {"x_offset": 10, "y_offset": 10})
                    inserted_any = True

                chart_created = inserted_any

            elif mode == "lane_id":
                mean_idx = header_index.get("平均白線距離(m)")
                median_idx = header_index.get("中央値(m)")
                min_idx = header_index.get("最小値(m)")
                max_idx = header_index.get("最大値(m)")

                inserted_any = False

                if mean_idx is not None:
                    mean_chart = workbook.add_chart({"type": "line"})
                    mean_chart.add_series(
                        {
                            "name": "平均白線距離(m)",
                            "categories": categories_range,
                            "values": _range(mean_idx),
                            "data_labels": {"value": True},
                        }
                    )
                    if median_idx is not None:
                        mean_chart.add_series(
                            {
                                "name": "中央値(m)",
                                "categories": categories_range,
                                "values": _range(median_idx),
                                "data_labels": {"value": True},
                            }
                        )
                    mean_chart.set_title({"name": "自転車ID別 白線距離(平均/中央値)"})
                    mean_chart.set_x_axis({"name": "Run-Group"})
                    mean_chart.set_y_axis({"name": "m"})
                    mean_chart.set_style(9)
                    graph_ws.insert_chart("A4", mean_chart, {"x_offset": 10, "y_offset": 10})
                    inserted_any = True

                if min_idx is not None or max_idx is not None:
                    range_chart = workbook.add_chart({"type": "column"})
                    if min_idx is not None:
                        range_chart.add_series(
                            {
                                "name": "最小値(m)",
                                "categories": categories_range,
                                "values": _range(min_idx),
                                "data_labels": {"value": True},
                            }
                        )
                    if max_idx is not None:
                        range_chart.add_series(
                            {
                                "name": "最大値(m)",
                                "categories": categories_range,
                                "values": _range(max_idx),
                                "data_labels": {"value": True},
                            }
                        )
                    range_chart.set_title({"name": "自転車ID別 白線距離レンジ"})
                    range_chart.set_x_axis({"name": "Run-Group"})
                    range_chart.set_y_axis({"name": "m"})
                    range_chart.set_style(11)
                    graph_ws.insert_chart("H4", range_chart, {"x_offset": 10, "y_offset": 10})
                    inserted_any = True

                chart_created = inserted_any

            elif mode == "track":
                speed_mean_idx = header_index.get("平均速度(km/h)")
                speed_median_idx = header_index.get("速度中央値(km/h)")
                lane_mean_idx = header_index.get("平均白線距離(m)")
                lane_median_idx = header_index.get("白線距離中央値(m)")

                inserted_any = False

                if speed_mean_idx is not None:
                    speed_chart = workbook.add_chart({"type": "line"})
                    speed_chart.add_series(
                        {
                            "name": "平均速度(km/h)",
                            "categories": categories_range,
                            "values": _range(speed_mean_idx),
                            "data_labels": {"value": True},
                        }
                    )
                    if speed_median_idx is not None:
                        speed_chart.add_series(
                            {
                                "name": "速度中央値(km/h)",
                                "categories": categories_range,
                                "values": _range(speed_median_idx),
                                "data_labels": {"value": True},
                            }
                        )
                    speed_chart.set_title({"name": "トラックID別 速度推移"})
                    speed_chart.set_x_axis({"name": "Run-Track"})
                    speed_chart.set_y_axis({"name": "km/h"})
                    speed_chart.set_style(10)
                    graph_ws.insert_chart("A4", speed_chart, {"x_offset": 10, "y_offset": 10})
                    inserted_any = True

                if lane_mean_idx is not None:
                    lane_chart = workbook.add_chart({"type": "line"})
                    lane_chart.add_series(
                        {
                            "name": "平均白線距離(m)",
                            "categories": categories_range,
                            "values": _range(lane_mean_idx),
                            "data_labels": {"value": True},
                        }
                    )
                    if lane_median_idx is not None:
                        lane_chart.add_series(
                            {
                                "name": "白線距離中央値(m)",
                                "categories": categories_range,
                                "values": _range(lane_median_idx),
                                "data_labels": {"value": True},
                            }
                        )
                    lane_chart.set_title({"name": "トラックID別 白線距離推移"})
                    lane_chart.set_x_axis({"name": "Run-Track"})
                    lane_chart.set_y_axis({"name": "m"})
                    lane_chart.set_style(12)
                    graph_ws.insert_chart("H4", lane_chart, {"x_offset": 10, "y_offset": 10})
                    inserted_any = True

                chart_created = inserted_any

            elif mode == "clearance":
                distance_idx = header_index.get("距離平均(cm)")
                speed_idx = header_index.get("速度平均(km/h)")

                if distance_idx is not None:
                    distance_chart = workbook.add_chart({"type": "column"})
                    distance_chart.add_series(
                        {
                            "name": "平均離隔距離(cm)",
                            "categories": categories_range,
                            "values": _range(distance_idx),
                            "data_labels": {"value": True},
                        }
                    )
                    distance_chart.set_title({"name": "距離帯別 離隔距離"})
                    distance_chart.set_x_axis({"name": "距離帯"})
                    distance_chart.set_y_axis({"name": "cm"})
                    distance_chart.set_style(3)
                    graph_ws.insert_chart("A4", distance_chart, {"x_offset": 10, "y_offset": 10})
                    chart_created = True

                if speed_idx is not None:
                    clearance_speed_chart = workbook.add_chart({"type": "line"})
                    clearance_speed_chart.add_series(
                        {
                            "name": "平均速度(km/h)",
                            "categories": categories_range,
                            "values": _range(speed_idx),
                            "data_labels": {"value": True},
                        }
                    )
                    clearance_speed_chart.set_title({"name": "距離帯別 速度"})
                    clearance_speed_chart.set_x_axis({"name": "距離帯"})
                    clearance_speed_chart.set_y_axis({"name": "km/h"})
                    clearance_speed_chart.set_style(2)
                    graph_ws.insert_chart("H4", clearance_speed_chart, {"x_offset": 10, "y_offset": 10})
                    chart_created = True

            if not chart_created:
                graph_ws.write("A4", chart_empty_message)
        else:
            graph_ws.write("A4", chart_empty_message)

    return chart_created


def _prepare_statistics_payload(
    run_ids: Sequence[int | str],
    *,
    downward_only: bool = False,
    mode: str = DEFAULT_STATISTICS_MODE,
) -> Dict[str, Any]:
    """集計に必要な共通データを生成する。"""

    normalized_run_ids = _coerce_run_ids(run_ids)
    if not normalized_run_ids:
        raise ValueError("統計に含めるRun IDを選択してください。")

    df = _load_detection_dataframe(normalized_run_ids)
    df = _filter_bicycle_rows(df)

    if df.empty:
        raise ValueError("指定したRunに自転車の検出結果が見つかりませんでした。")

    numeric_columns = [
        "speed_km_h",
        "clearance_distance_cm",
        "clearance_distance_m",
        "approach_distance_m",
        "line_distance",
        "l_line_distance",
        "r_line_distance",
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    if downward_only:
        df = df[df["travel_direction"].isin(DOWNWARD_DIRECTIONS)]
        if df.empty:
            raise ValueError("条件に一致する下向きの自転車データが存在しません。")

    df["lane_position_flag"] = df["lane_position_flag"].fillna("").astype(str)
    df["lane_category"] = df["lane_position_flag"].map({"+": "A", "-": "B"}).fillna("未分類")

    mode_key = _normalize_mode(mode)
    mode_meta = STATISTICS_MODES[mode_key]

    generated_at = datetime.now()
    timestamp_text = generated_at.strftime("%Y-%m-%d %H:%M:%S")

    condition_parts = ["対象: 自転車検出のみ", f"モード: {mode_meta['label']}"]
    if downward_only:
        condition_parts.append("下向き移動のみ抽出")
    condition_text = "、".join(condition_parts)

    summary_metadata_rows: List[List[object]] = [
        ["作成日時", timestamp_text],
        ["対象Run", ", ".join(str(rid) for rid in normalized_run_ids)],
        ["モード", mode_meta["label"]],
        ["抽出条件", condition_text],
    ]

    chart_empty_message = "グラフを生成するためのデータが不足しています。"

    if mode_key == "lane":
        working_df = df.copy()
        summary_headers = [
            "区分",
            "データ数",
            "Run数",
            "平均速度(km/h)",
            "離隔データ数",
            "離隔時平均距離(cm)",
            "離隔時平均速度(km/h)",
            "平均白線距離(m)",
        ]

        summary_table_rows: List[List[object]] = []
        summary_chart_rows: List[List[object]] = []

        for key, label in (("A", "A: 白線内側 (+)"), ("B", "B: 白線外側 (-)")):
            subset = working_df[working_df["lane_category"] == key]
            if subset.empty:
                continue
            clearance_subset = subset.dropna(subset=["clearance_distance_cm"])
            row = [
                label,
                int(len(subset)),
                int(subset["run_id"].nunique()),
                _mean(subset["speed_km_h"]),
                int(len(clearance_subset)) if not clearance_subset.empty else 0,
                _mean(clearance_subset["clearance_distance_cm"]),
                _mean(clearance_subset["speed_km_h"]),
                _mean(subset["line_distance"]),
            ]
            summary_table_rows.append(row)
            summary_chart_rows.append(row)

        if not summary_table_rows:
            summary_table_rows.append(
                ["(該当データなし)"] + [None] * (len(summary_headers) - 1)
            )

        per_run_headers = [
            "Run ID",
            "動画ファイル",
            "区分",
            "データ数",
            "平均速度(km/h)",
            "離隔データ数",
            "離隔時平均距離(cm)",
            "離隔時平均速度(km/h)",
            "平均白線距離(m)",
        ]
        per_run_rows: List[List[object]] = []

        grouped = working_df.groupby(["run_id", "filename", "lane_category"], dropna=False)
        for (run_id, filename, category), group in grouped:
            if category not in {"A", "B"}:
                continue
            clearance_subset = group.dropna(subset=["clearance_distance_cm"])
            per_run_rows.append(
                [
                    int(run_id),
                    filename,
                    "A: 白線内側 (+)" if category == "A" else "B: 白線外側 (-)",
                    int(len(group)),
                    _mean(group["speed_km_h"]),
                    int(len(clearance_subset)) if not clearance_subset.empty else 0,
                    _mean(clearance_subset["clearance_distance_cm"]),
                    _mean(clearance_subset["speed_km_h"]),
                    _mean(group["line_distance"]),
                ]
            )

        chart_empty_message = "グラフを生成するための白線区分別データが不足しています。"
        result_df = working_df

    elif mode_key == "lane_id":
        working_df = df.copy()
        working_df["group_id"] = pd.to_numeric(
            working_df.get("group_id"), errors="coerce"
        )
        working_df = working_df.dropna(subset=["group_id"])
        if working_df.empty:
            raise ValueError("グループIDが付与された自転車データが存在しません。")

        working_df["group_id"] = working_df["group_id"].astype(int)

        summary_headers = [
            "識別ID",
            "Run ID",
            "グループID",
            "動画ファイル",
            "白線内外(±)",
            "データ数",
            "平均白線距離(m)",
            "中央値(m)",
            "最小値(m)",
            "最大値(m)",
        ]

        summary_table_rows = []
        summary_chart_rows = []

        grouped = working_df.groupby(
            ["run_id", "filename", "group_id"], dropna=False
        )
        for (run_id, filename, group_id), group in grouped:
            lane_flag = _most_common(group["lane_position_flag"].replace("", pd.NA))
            lane_label = {
                "+": "内側 (+)",
                "-": "外側 (-)",
            }.get(lane_flag, lane_flag if lane_flag else None)

            lane_series = pd.to_numeric(
                group.get("line_distance"), errors="coerce"
            ).dropna()
            mean_value = _mean(group["line_distance"])
            median_value = _median(group["line_distance"])
            min_value: Optional[float]
            max_value: Optional[float]
            if lane_series.empty:
                min_value = None
                max_value = None
            else:
                min_value = float(round(float(lane_series.min()), 3))
                max_value = float(round(float(lane_series.max()), 3))

            identifier = f"Run{int(run_id)}-G{int(group_id)}"

            row = [
                identifier,
                int(run_id),
                int(group_id),
                filename,
                lane_label,
                int(len(group)),
                mean_value,
                median_value,
                min_value,
                max_value,
            ]
            summary_table_rows.append(row)
            summary_chart_rows.append(row)

        per_run_headers = summary_headers
        if summary_table_rows:
            per_run_rows = [list(row) for row in summary_table_rows]
        else:
            per_run_rows = []
            summary_table_rows.append(
                ["(該当データなし)"] + [None] * (len(summary_headers) - 1)
            )
        chart_empty_message = "自転車ID別の白線距離集計に必要なデータが不足しています。"
        result_df = working_df

    elif mode_key == "clearance":
        working_df = df.copy()
        clearance_df = working_df.dropna(subset=["clearance_distance_cm"])
        if clearance_df.empty:
            raise ValueError("離隔距離が記録されたデータが存在しませんでした。")

        distance_values = pd.to_numeric(
            clearance_df["clearance_distance_cm"], errors="coerce"
        )
        valid_index = distance_values.dropna().index
        if valid_index.empty:
            raise ValueError("離隔距離の数値データが取得できませんでした。")

        unique_count = int(distance_values.loc[valid_index].nunique())

        if unique_count <= 1:
            base_value = float(distance_values.loc[valid_index].iloc[0])
            buffer = max(abs(base_value) * 0.1, 1.0)
            bands = pd.cut(
                distance_values.loc[valid_index],
                bins=[base_value - buffer, base_value + buffer],
                include_lowest=True,
            )
        else:
            quantiles = min(6, unique_count)
            bands = pd.qcut(
                distance_values.loc[valid_index],
                q=quantiles,
                duplicates="drop",
            )

        def _format_band(interval: object) -> str:
            if isinstance(interval, pd.Interval):
                left_val = int(round(interval.left))
                right_val = int(round(interval.right))
                return f"{left_val}～{right_val}cm"
            return str(interval)

        if hasattr(bands, "cat"):
            categories = list(bands.cat.categories)
            labels = [_format_band(cat) for cat in categories]
            renamed = bands.cat.rename_categories(labels)
            clearance_df.loc[valid_index, "distance_band"] = pd.Categorical(
                renamed, categories=labels, ordered=True
            )
        else:
            labels = [_format_band(value) for value in bands]
            clearance_df.loc[valid_index, "distance_band"] = pd.Categorical(
                labels, categories=labels, ordered=True
            )

        clearance_df["distance_band_label"] = clearance_df["distance_band"].astype(str)
        clearance_df["distance_band_label"] = clearance_df["distance_band_label"].replace(
            {"nan": "未分類"}
        )

        summary_headers = [
            "距離帯",
            "データ数",
            "Run数",
            "距離平均(cm)",
            "距離中央値(cm)",
            "速度平均(km/h)",
            "速度中央値(km/h)",
        ]

        summary_table_rows: List[List[object]] = []
        summary_chart_rows: List[List[object]] = []
        grouped_bands = clearance_df.groupby("distance_band", sort=False, dropna=False)
        for band, subset in grouped_bands:
            if subset.empty:
                continue
            label = _format_band(band) if band is not None else "未分類"
            row = [
                label,
                int(len(subset)),
                int(subset["run_id"].nunique()),
                _mean(subset["clearance_distance_cm"]),
                _median(subset["clearance_distance_cm"]),
                _mean(subset["speed_km_h"]),
                _median(subset["speed_km_h"]),
            ]
            summary_table_rows.append(row)
            summary_chart_rows.append(row)

        if not summary_table_rows:
            summary_table_rows.append(
                ["(該当データなし)"] + [None] * (len(summary_headers) - 1)
            )

        per_run_headers = [
            "Run ID",
            "動画ファイル",
            "距離平均(cm)",
            "距離中央値(cm)",
            "速度平均(km/h)",
            "速度中央値(km/h)",
            "データ数",
        ]
        per_run_rows: List[List[object]] = []
        run_grouped = clearance_df.groupby(["run_id", "filename"], dropna=False)
        for (run_id, filename), subset in run_grouped:
            per_run_rows.append(
                [
                    int(run_id),
                    filename,
                    _mean(subset["clearance_distance_cm"]),
                    _median(subset["clearance_distance_cm"]),
                    _mean(subset["speed_km_h"]),
                    _median(subset["speed_km_h"]),
                    int(len(subset)),
                ]
            )

        chart_empty_message = "離隔距離を用いた集計に必要なデータが不足しています。"
        result_df = clearance_df

    elif mode_key == "track":
        working_df = df.copy()
        working_df["track_id"] = pd.to_numeric(
            working_df.get("track_id"), errors="coerce"
        )
        working_df = working_df.dropna(subset=["track_id"])
        if working_df.empty:
            raise ValueError("トラックID付きの検出データが存在しません。")

        working_df["track_id"] = working_df["track_id"].astype(int)
        working_df["group_id"] = pd.to_numeric(
            working_df.get("group_id"), errors="coerce"
        )

        summary_headers = [
            "識別ID",
            "Run ID",
            "トラックID",
            "グループID",
            "動画ファイル",
            "白線内外(±)",
            "データ数",
            "平均速度(km/h)",
            "速度中央値(km/h)",
            "平均白線距離(m)",
            "白線距離中央値(m)",
        ]

        summary_table_rows = []
        summary_chart_rows = []

        grouped = working_df.sort_values(["run_id", "track_id", "frame_num"]).groupby(
            ["run_id", "filename", "track_id"], dropna=False
        )
        for (run_id, filename, track_id_value), group in grouped:
            lane_flag = _most_common(group["lane_position_flag"].replace("", pd.NA))
            lane_label = {
                "+": "内側 (+)",
                "-": "外側 (-)",
            }.get(lane_flag, lane_flag if lane_flag else None)

            group_id_series = pd.to_numeric(
                group.get("group_id"), errors="coerce"
            ).dropna()
            group_id_value: Optional[int]
            if group_id_series.empty:
                group_id_value = None
            else:
                group_id_value = int(group_id_series.mode().iloc[0])

            speed_mean = _mean(group["speed_km_h"])
            speed_median = _median(group["speed_km_h"])
            lane_mean = _mean(group["line_distance"])
            lane_median = _median(group["line_distance"])

            identifier = f"Run{int(run_id)}-T{int(track_id_value)}"

            row = [
                identifier,
                int(run_id),
                int(track_id_value),
                int(group_id_value) if group_id_value is not None else None,
                filename,
                lane_label,
                int(len(group)),
                speed_mean,
                speed_median,
                lane_mean,
                lane_median,
            ]
            summary_table_rows.append(row)
            summary_chart_rows.append(row)

        if not summary_table_rows:
            summary_table_rows.append(
                ["(該当データなし)"] + [None] * (len(summary_headers) - 1)
            )

        per_run_headers = summary_headers
        per_run_rows = summary_table_rows.copy()

        chart_empty_message = "トラックID別の集計データが不足しています。"
        result_df = working_df

    else:  # pragma: no cover - safety net
        raise ValueError(f"未対応の集計モードです: {mode_key}")

    detail_columns = [
        ("run_id", "Run ID"),
        ("folder_alias", "フォルダ"),
        ("filename", "動画ファイル"),
        ("frame_num", "フレーム"),
        ("group_id", "Group ID"),
        ("track_id", "トラックID"),
        ("speed_km_h", "速度(km/h)"),
        ("approach_distance_m", "接近距離(m)"),
        ("clearance_distance_cm", "離隔距離(cm)"),
        ("lane_position_flag", "白線内外(±)"),
        ("lane_category", "区分(A/B)"),
        ("travel_direction", "進行方向"),
        ("line_distance", "白線最短距離"),
        ("l_line_distance", "左白線距離"),
        ("r_line_distance", "右白線距離"),
        ("class_name", "クラス名"),
    ]
    if mode_key == "clearance" and "distance_band_label" in result_df.columns:
        detail_columns.append(("distance_band_label", "離隔距離帯"))

    detail_rows: List[List[object]] = [[header for _, header in detail_columns]]
    for _, row in result_df.sort_values(["run_id", "frame_num", "group_id"]).iterrows():
        record: List[object] = []
        for column, _ in detail_columns:
            value = row.get(column)
            if isinstance(value, numbers.Real) and not isinstance(value, bool):
                if pd.isna(value):
                    record.append(None)
                else:
                    record.append(float(round(float(value), 3)))
            else:
                record.append(value if value not in ("", None) else None)
        detail_rows.append(record)

    per_run_df = pd.DataFrame(per_run_rows, columns=per_run_headers)
    detail_df = (
        pd.DataFrame(detail_rows[1:], columns=detail_rows[0])
        if len(detail_rows) > 1
        else pd.DataFrame(columns=detail_rows[0])
    )

    return {
        "run_ids": normalized_run_ids,
        "downward_only": downward_only,
        "mode": mode_key,
        "mode_label": mode_meta["label"],
        "condition_text": condition_text,
        "generated_at": generated_at,
        "generated_at_text": timestamp_text,
        "df": result_df,
        "record_count": int(len(result_df)),
        "summary_headers": summary_headers,
        "summary_metadata_rows": summary_metadata_rows,
        "summary_table_rows": summary_table_rows,
        "summary_chart_rows": summary_chart_rows,
        "per_run_headers": per_run_headers,
        "per_run_rows": per_run_rows,
        "per_run_df": per_run_df,
        "detail_rows": detail_rows,
        "detail_df": detail_df,
        "chart_empty_message": chart_empty_message,
    }

def generate_statistics_preview(
    run_ids: Sequence[int | str],
    *,
    downward_only: bool = False,
    mode: str = DEFAULT_STATISTICS_MODE,
    detail_limit: int = 200,
) -> Dict[str, Any]:
    """Web表示向けの集計データを生成する。"""

    payload = _prepare_statistics_payload(
        run_ids,
        downward_only=downward_only,
        mode=mode,
    )

    summary_headers = payload["summary_headers"]
    summary_rows = [
        dict(zip(summary_headers, row))
        for row in payload["summary_table_rows"]
    ]

    per_run_headers = payload["per_run_headers"]
    per_run_rows = [
        dict(zip(per_run_headers, row))
        for row in payload["per_run_rows"]
    ]

    detail_headers = payload["detail_rows"][0]
    detail_records = payload["detail_rows"][1 : detail_limit + 1]
    detail_preview = [dict(zip(detail_headers, row)) for row in detail_records]

    summary_chart_rows = payload["summary_chart_rows"]
    header_index = {name: idx for idx, name in enumerate(summary_headers)}
    chart_canvases: List[Dict[str, str]] = []
    chart_configs: List[Dict[str, Any]] = []
    chart_available = bool(summary_chart_rows)

    if payload["mode"] == "lane" and chart_available:
        label_idx = 0
        speed_idx = header_index.get("平均速度(km/h)")
        clearance_idx = header_index.get("離隔時平均距離(cm)")
        lane_idx = header_index.get("平均白線距離(m)")

        # Prepare Scatter Data (Raw samples)
        # Using working_df from payload logic implies we need access to raw df here.
        # Payload struct has 'df'.
        raw_df = payload.get('df')
        scatter_datasets = []
        if raw_df is not None and not raw_df.empty:
            # Downsample if too huge
            limit = 2000
            if len(raw_df) > limit:
                 raw_df = raw_df.sample(limit)
            
            for key, label, color in (("A", "A: 白線内側", "#0d6efd"), ("B", "B: 白線外側", "#dc3545")):
                sub = raw_df[raw_df["lane_category"] == key]
                if not sub.empty:
                    data_points = []
                    for _, r in sub.iterrows():
                        x_val = r["speed_km_h"]
                        y_val = r["line_distance"]
                        if isinstance(x_val, numbers.Real) and isinstance(y_val, numbers.Real):
                             data_points.append({"x": x_val, "y": y_val})
                    
                    if data_points:
                        scatter_datasets.append({
                            "label": label,
                            "data": data_points,
                            "backgroundColor": color,
                            "pointRadius": 3,
                        })

        # Prepare Histogram Data (Speed distribution)
        hist_datasets = []
        hist_labels = []
        if raw_df is not None and not raw_df.empty:
             valid_speed = raw_df["speed_km_h"].dropna().astype(float)
             if not valid_speed.empty:
                 min_s, max_s = valid_speed.min(), valid_speed.max()
                 bin_size = 5 # 5km/h steps
                 start = (int(min_s) // bin_size) * bin_size
                 end = (int(max_s) // bin_size + 1) * bin_size
                 bins = list(range(start, end + bin_size, bin_size))
                 hist_labels = [f"{b} - {b+bin_size}" for b in bins[:-1]]

                 for key, label, color in (("A", "A: 白線内側", "rgba(13, 110, 253, 0.5)"), ("B", "B: 白線外側", "rgba(220, 53, 69, 0.5)")):
                     sub = raw_df[raw_df["lane_category"] == key]
                     counts = [0] * (len(bins) - 1)
                     if not sub.empty:
                         sub_v = sub["speed_km_h"].dropna().astype(float)
                         for v in sub_v:
                             idx = (int(v) - start) // bin_size
                             if 0 <= idx < len(counts):
                                 counts[idx] += 1
                     hist_datasets.append({
                         "label": label,
                         "data": counts,
                         "backgroundColor": color,
                         "borderWidth": 1,
                     })

        labels = [str(row[label_idx]) for row in summary_chart_rows]
        speed_data = [
            float(row[speed_idx]) if speed_idx is not None and isinstance(row[speed_idx], numbers.Real) else None
            for row in summary_chart_rows
        ]
        clearance_data = [
            float(row[clearance_idx]) if clearance_idx is not None and isinstance(row[clearance_idx], numbers.Real) else None
            for row in summary_chart_rows
        ]
        lane_distance_data = [
            float(row[lane_idx]) if lane_idx is not None and isinstance(row[lane_idx], numbers.Real) else None
            for row in summary_chart_rows
        ]

        chart_canvases = [
            {"id": "laneSpeedChart", "class": "col-12 col-xl-4", "height": 220},
            {"id": "laneClearanceChart", "class": "col-12 col-xl-4", "height": 220},
            {"id": "laneDistanceChart", "class": "col-12 col-xl-4", "height": 220},
        ]
        chart_configs = [
            {
                "id": "laneSpeedChart",
                "config": {
                    "type": "bar",
                    "data": {
                        "labels": labels,
                        "datasets": [
                            {
                                "label": "平均速度 (km/h)",
                                "data": speed_data,
                                "backgroundColor": "#0d6efd",
                            }
                        ],
                    },
                    "options": {
                        "responsive": True,
                        "scales": {
                            "y": {
                                "beginAtZero": True,
                                "title": {"display": True, "text": "km/h"},
                            }
                        },
                        "plugins": {"legend": {"display": True}},
                    },
                },
            },
            {
                "id": "laneClearanceChart",
                "config": {
                    "type": "bar",
                    "data": {
                        "labels": labels,
                        "datasets": [
                            {
                                "label": "離隔時平均距離 (cm)",
                                "data": clearance_data,
                                "backgroundColor": "#fd7e14",
                            }
                        ],
                    },
                    "options": {
                        "responsive": True,
                        "scales": {
                            "y": {
                                "beginAtZero": True,
                                "title": {"display": True, "text": "cm"},
                            }
                        },
                        "plugins": {"legend": {"display": True}},
                    },
                },
            },
            {
                "id": "laneDistanceChart",
                "config": {
                    "type": "line",
                    "data": {
                        "labels": labels,
                        "datasets": [
                            {
                                "label": "平均白線距離 (m)",
                                "data": lane_distance_data,
                                "borderColor": "#20c997",
                                "backgroundColor": "rgba(32,201,151,0.2)",
                                "tension": 0.2,
                                "fill": False,
                            }
                        ],
                    },
                    "options": {
                        "responsive": True,
                        "scales": {
                            "y": {
                                "beginAtZero": True,
                                "title": {"display": True, "text": "m"},
                            }
                        },
                        "plugins": {"legend": {"display": True}},
                    },
                },
            },
        ]

        if scatter_datasets:
            chart_canvases.append({"id": "laneScatterChart", "class": "col-12 col-xl-6", "height": 300})
            chart_configs.append({
                "id": "laneScatterChart",
                "config": {
                    "type": "scatter",
                    "data": {"datasets": scatter_datasets},
                    "options": {
                        "responsive": True,
                        "plugins": {
                            "title": { "display": True, "text": "速度 vs 白線距離 分布" },
                            "tooltip": {
                                "callbacks": {
                                    "label": "(ctx) => `${ctx.dataset.label}: ${ctx.raw.x} km/h, ${ctx.raw.y} m`"
                                }
                            }
                        },
                        "scales": {
                            "x": { "title": { "display": True, "text": "速度 (km/h)" }, "type": "linear", "position": "bottom" },
                            "y": { "title": { "display": True, "text": "白線距離 (m)" } }
                        }
                    }
                }
            })
        
        if hist_datasets:
            chart_canvases.append({"id": "laneHistChart", "class": "col-12 col-xl-6", "height": 300})
            chart_configs.append({
                "id": "laneHistChart",
                "config": {
                    "type": "bar",
                    "data": { "labels": hist_labels, "datasets": hist_datasets },
                    "options": {
                        "responsive": True,
                        "plugins": {
                            "title": { "display": True, "text": "速度の度数分布 (ヒストグラム)" },
                        },
                        "scales": {
                            "x": { "title": { "display": True, "text": "速度帯 (km/h)" } },
                            "y": { "title": { "display": True, "text": "件数" }, "beginAtZero": True }
                        }
                    }
                }
            })

    elif payload["mode"] == "lane_id" and chart_available:
        label_idx = header_index.get("識別ID")
        mean_idx = header_index.get("平均白線距離(m)")
        median_idx = header_index.get("中央値(m)")
        min_idx = header_index.get("最小値(m)")
        max_idx = header_index.get("最大値(m)")

        labels = [
            str(row[label_idx]) if label_idx is not None else str(index)
            for index, row in enumerate(summary_chart_rows, start=1)
        ]
        mean_data = [
            float(row[mean_idx])
            if mean_idx is not None and isinstance(row[mean_idx], numbers.Real)
            else None
            for row in summary_chart_rows
        ]
        median_data = [
            float(row[median_idx])
            if median_idx is not None and isinstance(row[median_idx], numbers.Real)
            else None
            for row in summary_chart_rows
        ]
        min_data = [
            float(row[min_idx])
            if min_idx is not None and isinstance(row[min_idx], numbers.Real)
            else None
            for row in summary_chart_rows
        ]
        max_data = [
            float(row[max_idx])
            if max_idx is not None and isinstance(row[max_idx], numbers.Real)
            else None
            for row in summary_chart_rows
        ]

        chart_canvases = [
            {"id": "laneIdMeanChart", "class": "col-12 col-xl-6", "height": 230},
            {"id": "laneIdRangeChart", "class": "col-12 col-xl-6", "height": 230},
        ]
        chart_configs = [
            {
                "id": "laneIdMeanChart",
                "config": {
                    "type": "line",
                    "data": {
                        "labels": labels,
                        "datasets": [
                            {
                                "label": "平均白線距離 (m)",
                                "data": mean_data,
                                "borderColor": "#20c997",
                                "backgroundColor": "rgba(32,201,151,0.2)",
                                "tension": 0.2,
                                "fill": False,
                            },
                            {
                                "label": "中央値 (m)",
                                "data": median_data,
                                "borderColor": "#6f42c1",
                                "backgroundColor": "rgba(111,66,193,0.15)",
                                "tension": 0.25,
                                "fill": False,
                            },
                        ],
                    },
                    "options": {
                        "responsive": True,
                        "scales": {
                            "y": {
                                "beginAtZero": True,
                                "title": {"display": True, "text": "m"},
                            }
                        },
                        "plugins": {"legend": {"display": True}},
                    },
                },
            },
            {
                "id": "laneIdRangeChart",
                "config": {
                    "type": "bar",
                    "data": {
                        "labels": labels,
                        "datasets": [
                            {
                                "label": "最小値 (m)",
                                "data": min_data,
                                "backgroundColor": "rgba(13,110,253,0.35)",
                                "borderColor": "#0d6efd",
                                "borderWidth": 1,
                            },
                            {
                                "label": "最大値 (m)",
                                "data": max_data,
                                "backgroundColor": "rgba(253,126,20,0.35)",
                                "borderColor": "#fd7e14",
                                "borderWidth": 1,
                            },
                        ],
                    },
                    "options": {
                        "responsive": True,
                        "scales": {
                            "y": {
                                "beginAtZero": True,
                                "title": {"display": True, "text": "m"},
                            }
                        },
                        "plugins": {"legend": {"display": True}},
                    },
                },
            },
        ]

    elif payload["mode"] == "track" and chart_available:
        label_idx = header_index.get("識別ID")
        speed_mean_idx = header_index.get("平均速度(km/h)")
        speed_median_idx = header_index.get("速度中央値(km/h)")
        lane_mean_idx = header_index.get("平均白線距離(m)")
        lane_median_idx = header_index.get("白線距離中央値(m)")

        labels = [
            str(row[label_idx]) if label_idx is not None else str(index)
            for index, row in enumerate(summary_chart_rows, start=1)
        ]
        speed_mean_data = [
            float(row[speed_mean_idx])
            if speed_mean_idx is not None and isinstance(row[speed_mean_idx], numbers.Real)
            else None
            for row in summary_chart_rows
        ]
        speed_median_data = [
            float(row[speed_median_idx])
            if speed_median_idx is not None and isinstance(row[speed_median_idx], numbers.Real)
            else None
            for row in summary_chart_rows
        ]
        lane_mean_data = [
            float(row[lane_mean_idx])
            if lane_mean_idx is not None and isinstance(row[lane_mean_idx], numbers.Real)
            else None
            for row in summary_chart_rows
        ]
        lane_median_data = [
            float(row[lane_median_idx])
            if lane_median_idx is not None and isinstance(row[lane_median_idx], numbers.Real)
            else None
            for row in summary_chart_rows
        ]

        chart_canvases = [
            {"id": "trackSpeedChart", "class": "col-12 col-xl-6", "height": 230},
            {"id": "trackLaneChart", "class": "col-12 col-xl-6", "height": 230},
        ]
        chart_configs = [
            {
                "id": "trackSpeedChart",
                "config": {
                    "type": "line",
                    "data": {
                        "labels": labels,
                        "datasets": [
                            {
                                "label": "平均速度 (km/h)",
                                "data": speed_mean_data,
                                "borderColor": "#0d6efd",
                                "backgroundColor": "rgba(13,110,253,0.15)",
                                "tension": 0.25,
                                "fill": False,
                            },
                            {
                                "label": "速度中央値 (km/h)",
                                "data": speed_median_data,
                                "borderColor": "#6f42c1",
                                "backgroundColor": "rgba(111,66,193,0.15)",
                                "tension": 0.25,
                                "fill": False,
                            },
                        ],
                    },
                    "options": {
                        "responsive": True,
                        "scales": {
                            "y": {
                                "beginAtZero": True,
                                "title": {"display": True, "text": "km/h"},
                            }
                        },
                        "plugins": {"legend": {"display": True}},
                    },
                },
            },
            {
                "id": "trackLaneChart",
                "config": {
                    "type": "line",
                    "data": {
                        "labels": labels,
                        "datasets": [
                            {
                                "label": "平均白線距離 (m)",
                                "data": lane_mean_data,
                                "borderColor": "#20c997",
                                "backgroundColor": "rgba(32,201,151,0.2)",
                                "tension": 0.2,
                                "fill": False,
                            },
                            {
                                "label": "白線距離中央値 (m)",
                                "data": lane_median_data,
                                "borderColor": "#fd7e14",
                                "backgroundColor": "rgba(253,126,20,0.2)",
                                "tension": 0.2,
                                "fill": False,
                            },
                        ],
                    },
                    "options": {
                        "responsive": True,
                        "scales": {
                            "y": {
                                "beginAtZero": True,
                                "title": {"display": True, "text": "m"},
                            }
                        },
                        "plugins": {"legend": {"display": True}},
                    },
                },
            },
        ]

    elif payload["mode"] == "clearance" and chart_available:
        label_idx = 0
        distance_idx = header_index.get("距離平均(cm)")
        speed_idx = header_index.get("速度平均(km/h)")

        labels = [str(row[label_idx]) for row in summary_chart_rows]
        distance_data = [
            float(row[distance_idx]) if distance_idx is not None and isinstance(row[distance_idx], numbers.Real) else None
            for row in summary_chart_rows
        ]
        speed_data = [
            float(row[speed_idx]) if speed_idx is not None and isinstance(row[speed_idx], numbers.Real) else None
            for row in summary_chart_rows
        ]

        chart_canvases = [
            {"id": "clearanceDistanceChart", "class": "col-12 col-lg-6", "height": 220},
            {"id": "clearanceSpeedChart", "class": "col-12 col-lg-6", "height": 220},
        ]
        chart_configs = [
            {
                "id": "clearanceDistanceChart",
                "config": {
                    "type": "bar",
                    "data": {
                        "labels": labels,
                        "datasets": [
                            {
                                "label": "平均離隔距離 (cm)",
                                "data": distance_data,
                                "backgroundColor": "#ffc107",
                            }
                        ],
                    },
                    "options": {
                        "responsive": True,
                        "scales": {
                            "y": {
                                "beginAtZero": True,
                                "title": {"display": True, "text": "cm"},
                            }
                        },
                        "plugins": {"legend": {"display": True}},
                    },
                },
            },
            {
                "id": "clearanceSpeedChart",
                "config": {
                    "type": "line",
                    "data": {
                        "labels": labels,
                        "datasets": [
                            {
                                "label": "平均速度 (km/h)",
                                "data": speed_data,
                                "borderColor": "#0d6efd",
                                "backgroundColor": "rgba(13,110,253,0.15)",
                                "tension": 0.25,
                                "fill": False,
                            }
                        ],
                    },
                    "options": {
                        "responsive": True,
                        "scales": {
                            "y": {
                                "beginAtZero": True,
                                "title": {"display": True, "text": "km/h"},
                            }
                        },
                        "plugins": {"legend": {"display": True}},
                    },
                },
            },
        ]

    chart_available = bool(chart_configs)
    chart_payload = {
        "mode": payload["mode"],
        "charts": chart_configs,
    }

    return {
        "run_ids": payload["run_ids"],
        "downward_only": payload["downward_only"],
        "mode": payload["mode"],
        "mode_label": payload["mode_label"],
        "condition_text": payload["condition_text"],
        "generated_at": payload["generated_at_text"],
        "record_count": payload["record_count"],
        "summary_headers": summary_headers,
        "summary_rows": summary_rows,
        "summary_metadata": payload["summary_metadata_rows"],
        "per_run_headers": per_run_headers,
        "per_run_rows": per_run_rows,
        "detail_headers": detail_headers,
        "detail_rows": detail_preview,
        "detail_limit": detail_limit,
        "total_detail_rows": len(payload["detail_rows"]) - 1,
        "chart": {
            "available": chart_available,
            "canvases": chart_canvases,
            "config": chart_payload,
            "empty_message": payload["chart_empty_message"],
        },
    }


def export_statistics_workbook(
    run_ids: Sequence[int | str],
    *,
    downward_only: bool = False,
    mode: str = DEFAULT_STATISTICS_MODE,
    output_dir: Optional[str] = None,
) -> Tuple[str, Dict[str, object]]:
    """指定したRunの自転車データを集計しExcelファイルとして保存する。"""

    payload = _prepare_statistics_payload(
        run_ids,
        downward_only=downward_only,
        mode=mode,
    )

    df = payload["df"]
    base_dir = _determine_output_directory(df, output_dir)

    timestamp_slug = payload["generated_at"].strftime("%Y%m%d_%H%M%S")
    if len(payload["run_ids"]) == 1:
        stem = f"run_{payload['run_ids'][0]}"
    else:
        stem = (
            f"runs_{payload['run_ids'][0]}_{payload['run_ids'][-1]}_"
            f"{len(payload['run_ids'])}本"
        )
    filename = f"statistics_{stem}_{timestamp_slug}.xlsx"
    excel_path = os.path.join(base_dir, filename)

    suffix = 1
    while os.path.exists(excel_path):
        excel_path = os.path.join(
            base_dir, f"statistics_{stem}_{timestamp_slug}_{suffix}.xlsx"
        )
        suffix += 1

    charts_created = False
    if _XLSXWRITER_AVAILABLE:
        charts_created = _write_with_xlsxwriter(
            excel_path,
            payload["summary_metadata_rows"],
            payload["summary_headers"],
            payload["summary_table_rows"],
            payload["summary_chart_rows"],
            payload["per_run_df"],
            payload["detail_df"],
            mode=payload["mode"],
            chart_empty_message=payload["chart_empty_message"],
        )
    else:
        sheets_payload = [
            (
                "概要",
                payload["summary_metadata_rows"]
                + [[None]]
                + [payload["summary_headers"]]
                + payload["summary_table_rows"],
            ),
            (
                "Run別集計",
                [payload["per_run_headers"]]
                + payload["per_run_rows"]
                if not payload["per_run_df"].empty
                else [payload["per_run_headers"]],
            ),
            ("詳細データ", payload["detail_rows"]),
            (
                "グラフ",
                [
                    [
                        "XlsxWriterが未導入のため、グラフは生成されませんでした。",
                    ],
                    [payload["chart_empty_message"]],
                ],
            ),
        ]
        _write_simple_xlsx(excel_path, sheets_payload)

    track_csv_path: Optional[str] = None
    if payload["mode"] == "track" and payload["summary_table_rows"]:
        track_df = pd.DataFrame(
            payload["summary_table_rows"], columns=payload["summary_headers"]
        )
        if not track_df.empty and track_df.iloc[0, 0] != "(該当データなし)":
            csv_filename = f"track_metrics_{stem}_{timestamp_slug}.csv"
            track_csv_path = os.path.join(base_dir, csv_filename)
            track_df.to_csv(track_csv_path, index=False, encoding="utf-8-sig")

    metadata: Dict[str, object] = {
        "run_ids": payload["run_ids"],
        "downward_only": payload["downward_only"],
        "mode": payload["mode"],
        "record_count": payload["record_count"],
        "excel_path": excel_path,
        "charts": charts_created,
        "xlsxwriter": _XLSXWRITER_AVAILABLE,
    }
    if track_csv_path:
        metadata["track_csv_path"] = track_csv_path
    return excel_path, metadata
