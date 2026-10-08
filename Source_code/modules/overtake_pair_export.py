import io
import sqlite3
from typing import Iterable, Optional

import pandas as pd

from .db_manager import MAIN_DB_PATH

_BIKE_TOKENS = ("bicycle", "bike", "cyclist")
_WINDOW_RADIUS = 30


def _is_bike(class_name: object) -> bool:
    return any(token in str(class_name or "").lower() for token in _BIKE_TOKENS)


def _normalize_run_ids(run_ids: Optional[Iterable[int]]) -> list[int]:
    if not run_ids:
        return []
    normalized: list[int] = []
    seen = set()
    for raw in run_ids:
        try:
            rid = int(raw)
        except (TypeError, ValueError):
            continue
        if rid in seen:
            continue
        seen.add(rid)
        normalized.append(rid)
    return normalized


def _pick_group_class(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    counts = (
        df.groupby(["run_id", "group_id", "class_id"], dropna=True)
        .size()
        .reset_index(name="count")
    )
    if counts.empty:
        return counts
    counts = counts.sort_values(
        ["run_id", "group_id", "count", "class_id"],
        ascending=[True, True, False, True],
    )
    return counts.drop_duplicates(["run_id", "group_id"])


def _build_group_class_maps(db_path: str, run_ids: list[int]) -> tuple[dict, dict, dict]:
    if not run_ids:
        return {}, {}, {}
    placeholders = ", ".join(["?"] * len(run_ids))
    query = f"""
        SELECT run_id, group_id, class_id, model_name
        FROM Detection
        WHERE run_id IN ({placeholders})
          AND group_id IS NOT NULL
          AND class_id IS NOT NULL
    """
    with sqlite3.connect(db_path) as conn:
        group_df = pd.read_sql_query(query, conn, params=run_ids)
        if group_df.empty:
            return {}, {}, {}
        group_df["model_name"] = group_df["model_name"].fillna("")
        group_df["run_id"] = pd.to_numeric(group_df["run_id"], errors="coerce")
        group_df["group_id"] = pd.to_numeric(group_df["group_id"], errors="coerce")
        group_df["class_id"] = pd.to_numeric(group_df["class_id"], errors="coerce")
        group_df = group_df.dropna(subset=["run_id", "group_id", "class_id"])
        group_df["run_id"] = group_df["run_id"].astype(int)
        group_df["group_id"] = group_df["group_id"].astype(int)
        group_df["class_id"] = group_df["class_id"].astype(int)

        non_tire_df = group_df[~group_df["model_name"].str.lower().eq("best")]
        primary = _pick_group_class(non_tire_df)
        fallback = _pick_group_class(group_df)
        if primary.empty:
            chosen = fallback
        else:
            chosen = primary
            if not fallback.empty:
                primary_keys = set(zip(primary["run_id"], primary["group_id"]))
                missing = fallback[
                    ~fallback.apply(lambda r: (r["run_id"], r["group_id"]) in primary_keys, axis=1)
                ]
                if not missing.empty:
                    chosen = pd.concat([primary, missing], ignore_index=True)

        class_map: dict[int, str] = {}
        cur = conn.cursor()
        try:
            cur.execute("SELECT class_id, class_name FROM ClassMaster")
            for class_id, class_name in cur.fetchall():
                if class_id not in class_map:
                    class_map[int(class_id)] = str(class_name)
        except sqlite3.Error:
            pass
        try:
            cur.execute("SELECT class_id, class_name FROM Class")
            for class_id, class_name in cur.fetchall():
                if class_id not in class_map:
                    class_map[int(class_id)] = str(class_name)
        except sqlite3.Error:
            pass
        class_map[0] = "car"

    group_class_id_map = {
        (int(row["run_id"]), int(row["group_id"])): int(row["class_id"])
        for _, row in chosen.iterrows()
    }
    group_class_name_map = {
        key: class_map.get(class_id)
        for key, class_id in group_class_id_map.items()
    }
    class_id_name_map = dict(class_map)
    return group_class_id_map, group_class_name_map, class_id_name_map


def generate_overtake_pair_csv(
    db_path: str = MAIN_DB_PATH,
    run_ids: Optional[Iterable[int]] = None,
) -> bytes:
    """Generate a pair-summary CSV (overtaker/overtaken in one row) from OvertakeEvents."""
    target_runs = _normalize_run_ids(run_ids)
    params: list[object] = []
    where_clause = ""
    if target_runs:
        placeholders = ", ".join(["?"] * len(target_runs))
        where_clause = f"WHERE o.run_id IN ({placeholders})"
        params.extend(target_runs)

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        ot_cols = {row[1] for row in cur.execute("PRAGMA table_info(OvertakeEvents)")}

        if "event_id" in ot_cols:
            event_id_expr = "o.event_id"
        elif "overtake_event_id" in ot_cols:
            event_id_expr = "o.overtake_event_id"
        else:
            event_id_expr = "o.rowid"

        det_cols = {row[1] for row in cur.execute("PRAGMA table_info(Detection)")}
        class_master_cols = {row[1] for row in cur.execute("PRAGMA table_info(ClassMaster)")}
        class_lookup_cols = {row[1] for row in cur.execute("PRAGMA table_info(Class)")}

        join_parts = []
        if class_master_cols:
            join_parts.append("LEFT JOIN ClassMaster cm_ot ON d.class_id = cm_ot.class_id")
        if class_lookup_cols:
            join_parts.append("LEFT JOIN Class c_ot ON d.class_id = c_ot.class_id")
        join_class = "\n        ".join(join_parts)

        if "class_name" in det_cols:
            class_expr = "d.class_name"
        elif class_master_cols and class_lookup_cols:
            class_expr = "COALESCE(cm_ot.class_name, c_ot.class_name)"
        elif class_master_cols:
            class_expr = "cm_ot.class_name"
        elif class_lookup_cols:
            class_expr = "c_ot.class_name"
        else:
            class_expr = "d.class_id"

        event_query = f"""
        SELECT
            {event_id_expr} AS event_id,
            o.run_id,
            o.event_frame_num,
            o.overtaker_group_id,
            o.overtaken_group_id,
            o.approach_distance_m,
            o.clearance_distance_m,
            o.clearance_distance_cm,
            o.clearance_distance_px,
            o.line_distance_m,
            v.filename AS video_filename,
            v.fps AS video_fps,
            v.collection_year,
            v.road_type
        FROM OvertakeEvents o
        JOIN ProcessLog p ON o.run_id = p.run_id
        JOIN Video v ON p.video_id = v.video_id
        {where_clause}
        ORDER BY o.run_id, o.event_frame_num, {event_id_expr}
        """
        events_df = pd.read_sql_query(event_query, conn, params=params)

        if events_df.empty:
            header_df = pd.DataFrame(columns=_final_column_order())
            return header_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

        all_frames: list[pd.DataFrame] = []

        for _, event in events_df.iterrows():
            run_id = event["run_id"]
            event_frame = int(event["event_frame_num"])
            overtaker_gid = event["overtaker_group_id"]
            overtaken_gid = event["overtaken_group_id"]
            if pd.isna(overtaker_gid) or pd.isna(overtaken_gid):
                continue
            try:
                overtaker_gid = int(overtaker_gid)
                overtaken_gid = int(overtaken_gid)
            except (TypeError, ValueError):
                continue

            det_query = f"""
                SELECT
                    d.frame_num,
                    d.group_id,
                    d.auto_id,
                    d.track_id,
                    d.class_id,
                    {class_expr} AS class_name,
                    d.model_name,
                    d.speed_km_h,
                    d.pixel_speed,
                    d.pixel_speed_frame,
                    d.x_pixels_per_meter,
                    d.x1, d.y1, d.x2, d.y2,
                    d.measure_x, d.measure_y,
                    d.line_distance_m, d.line_distance_cm, d.line_distance,
                    d.l_line_distance_m, d.l_line_distance_cm, d.l_line_distance,
                    d.r_line_distance_m, d.r_line_distance_cm, d.r_line_distance,
                    d.l_line_cross_m, d.r_line_cross_m,
                    d.lane_position_flag,
                    d.center_line_overtake_status,
                    d.white_line_overtake_status,
                    d.travel_direction,
                    d.clearance_distance_m,
                    d.clearance_distance_cm,
                    d.clearance_distance_px,
                    d.overtake_window_offset
                FROM Detection d
                {join_class}
                WHERE d.run_id = ?
                  AND d.group_id IN (?, ?)
                ORDER BY d.frame_num
            """
            det_df = pd.read_sql_query(
                det_query,
                conn,
                params=(run_id, overtaker_gid, overtaken_gid),
            )
            if det_df.empty:
                continue

            ot_df = det_df[det_df["group_id"] == overtaker_gid].copy()
            od_df = det_df[det_df["group_id"] == overtaken_gid].copy()

            def _prefix(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
                rename_map = {col: f"{prefix}{col}" for col in df.columns if col != "frame_num"}
                return df.rename(columns=rename_map)

            ot_df = _prefix(ot_df, "overtaker_")
            od_df = _prefix(od_df, "overtaken_")

            merged = pd.merge(ot_df, od_df, on="frame_num", how="inner")
            merged["event_id"] = event["event_id"]
            merged["run_id"] = run_id
            merged["video_filename"] = event["video_filename"]
            merged["video_fps"] = event["video_fps"]
            merged["collection_year"] = event["collection_year"]
            merged["road_type"] = event["road_type"]
            merged["event_frame_num"] = event_frame
            merged["overtaker_group_id"] = overtaker_gid
            merged["overtaken_group_id"] = overtaken_gid
            merged["approach_distance_m"] = event["approach_distance_m"]
            merged["line_distance_m"] = event["line_distance_m"]

            merged["offset_frame"] = merged["frame_num"].astype(int) - int(event_frame)

            merged["clearance_distance_m"] = (
                merged.get("overtaker_clearance_distance_m")
                .combine_first(merged.get("overtaken_clearance_distance_m"))
            )
            merged["clearance_distance_cm"] = (
                merged.get("overtaker_clearance_distance_cm")
                .combine_first(merged.get("overtaken_clearance_distance_cm"))
            )
            merged["clearance_distance_px"] = (
                merged.get("overtaker_clearance_distance_px")
                .combine_first(merged.get("overtaken_clearance_distance_px"))
            )
            for col, fallback_key in (
                ("clearance_distance_m", "clearance_distance_m"),
                ("clearance_distance_cm", "clearance_distance_cm"),
                ("clearance_distance_px", "clearance_distance_px"),
            ):
                fallback_val = event.get(fallback_key)
                if fallback_val is not None and pd.notna(fallback_val):
                    merged[col] = merged[col].fillna(fallback_val)

            all_frames.append(merged)

    if not all_frames:
        header_df = pd.DataFrame(columns=_final_column_order())
        return header_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

    df = pd.concat(all_frames, ignore_index=True)

    run_id_list = (
        pd.to_numeric(df["run_id"], errors="coerce")
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )
    group_class_id_map, group_class_name_map, class_id_name_map = _build_group_class_maps(
        db_path, run_id_list
    )
    if group_class_id_map:
        def _make_key_series(run_series: pd.Series, group_series: pd.Series) -> pd.Series:
            keys = []
            for r_val, g_val in zip(run_series, group_series):
                if pd.isna(r_val) or pd.isna(g_val):
                    keys.append(None)
                    continue
                try:
                    keys.append((int(r_val), int(g_val)))
                except (TypeError, ValueError):
                    keys.append(None)
            return pd.Series(keys, index=run_series.index)

        overtaker_keys = _make_key_series(df["run_id"], df["overtaker_group_id"])
        overtaken_keys = _make_key_series(df["run_id"], df["overtaken_group_id"])

        df["overtaker_class_id"] = overtaker_keys.map(group_class_id_map)
        df["overtaken_class_id"] = overtaken_keys.map(group_class_id_map)
        if "overtaker_class_id_raw" in df.columns:
            df["overtaker_class_id"] = df["overtaker_class_id"].fillna(df["overtaker_class_id_raw"])
        if "overtaken_class_id_raw" in df.columns:
            df["overtaken_class_id"] = df["overtaken_class_id"].fillna(df["overtaken_class_id_raw"])
        df["overtaker_class_name"] = (
            overtaker_keys.map(group_class_name_map).fillna(df["overtaker_class_name"])
        )
        df["overtaken_class_name"] = (
            overtaken_keys.map(group_class_name_map).fillna(df["overtaken_class_name"])
        )
        if "overtaker_class_id" in df.columns:
            df["overtaker_class_name"] = df["overtaker_class_name"].fillna(
                df["overtaker_class_id"]
                .map(class_id_name_map)
                .fillna(
                    df["overtaker_class_id"].map(
                        lambda cid: "car" if pd.notna(cid) and int(cid) == 0 else None
                    )
                )
            )
        if "overtaken_class_id" in df.columns:
            df["overtaken_class_name"] = df["overtaken_class_name"].fillna(
                df["overtaken_class_id"]
                .map(class_id_name_map)
                .fillna(
                    df["overtaken_class_id"].map(
                        lambda cid: "car" if pd.notna(cid) and int(cid) == 0 else None
                    )
                )
            )
        if "overtaker_class_id" in df.columns:
            df["overtaker_class_name"] = df["overtaker_class_name"].fillna(
                df["overtaker_class_id"].map(
                    lambda cid: "car" if pd.notna(cid) and int(cid) == 0 else None
                )
            )
        if "overtaken_class_id" in df.columns:
            df["overtaken_class_name"] = df["overtaken_class_name"].fillna(
                df["overtaken_class_id"].map(
                    lambda cid: "car" if pd.notna(cid) and int(cid) == 0 else None
                )
            )
        df.loc[df["overtaker_class_id"] == 0, "overtaker_class_name"] = "car"
        df.loc[df["overtaken_class_id"] == 0, "overtaken_class_name"] = "car"

    if "clearance_distance_cm" in df.columns:
        missing_cm = df["clearance_distance_cm"].isna()
        if missing_cm.any() and "clearance_distance_m" in df.columns:
            df.loc[missing_cm, "clearance_distance_cm"] = (
                df.loc[missing_cm, "clearance_distance_m"] * 100.0
            )

    def _video_time(row: pd.Series) -> Optional[float]:
        fps = row.get("video_fps")
        frame = row.get("frame_num")
        try:
            fps_val = float(fps) if fps else None
            if fps_val and fps_val > 0 and frame is not None:
                return float(frame) / fps_val
        except (TypeError, ValueError):
            return None
        return None

    df["video_time_s"] = df.apply(_video_time, axis=1)

    def _ensure_line_distance_px(prefix: str) -> None:
        px_map = [
            ("line_distance", "line_distance_px"),
            ("l_line_distance", "l_line_distance_px"),
            ("r_line_distance", "r_line_distance_px"),
        ]
        for base_suffix, px_suffix in px_map:
            base_col = f"{prefix}_{base_suffix}"
            px_col = f"{prefix}_{px_suffix}"
            if base_col not in df.columns:
                continue
            if px_col in df.columns:
                df[px_col] = df[px_col].combine_first(df[base_col])
            else:
                df[px_col] = df[base_col]

        scale_col = f"{prefix}_x_pixels_per_meter"
        if scale_col not in df.columns:
            return
        scale = pd.to_numeric(df[scale_col], errors="coerce")
        for m_suffix, px_suffix in (
            ("line_distance_m", "line_distance_px"),
            ("l_line_distance_m", "l_line_distance_px"),
            ("r_line_distance_m", "r_line_distance_px"),
        ):
            m_col = f"{prefix}_{m_suffix}"
            px_col = f"{prefix}_{px_suffix}"
            if m_col not in df.columns or px_col not in df.columns:
                continue
            missing = df[px_col].isna()
            if not missing.any():
                continue
            m_vals = pd.to_numeric(df.loc[missing, m_col], errors="coerce")
            scale_vals = scale.loc[missing]
            df.loc[missing, px_col] = m_vals * scale_vals

    def _fill_line_distance_cm(prefix: str) -> None:
        for m_suffix, cm_suffix in (
            ("line_distance_m", "line_distance_cm"),
            ("l_line_distance_m", "l_line_distance_cm"),
            ("r_line_distance_m", "r_line_distance_cm"),
        ):
            m_col = f"{prefix}_{m_suffix}"
            cm_col = f"{prefix}_{cm_suffix}"
            if m_col not in df.columns:
                continue
            if cm_col not in df.columns:
                df[cm_col] = None
            missing = df[cm_col].isna()
            if not missing.any():
                continue
            df.loc[missing, cm_col] = (
                pd.to_numeric(df.loc[missing, m_col], errors="coerce") * 100.0
            )

    def _apply_signed_line_distance(prefix: str) -> None:
        lane_col = f"{prefix}_lane_position_flag"
        if lane_col not in df.columns:
            return
        lane_flags = df[lane_col].fillna("").astype(str).str.strip()
        sign = lane_flags.map({"+": 1.0, "-": -1.0})
        if sign.isna().all():
            return
        for suffix in ("line_distance_m", "line_distance_cm", "line_distance_px"):
            col = f"{prefix}_{suffix}"
            if col not in df.columns:
                continue
            values = pd.to_numeric(df[col], errors="coerce")
            signed = values.copy()
            mask = sign.notna()
            signed.loc[mask] = values.loc[mask].abs() * sign.loc[mask]
            df[col] = signed

    for target_prefix in ("overtaker", "overtaken"):
        _ensure_line_distance_px(target_prefix)
        _fill_line_distance_cm(target_prefix)
        _apply_signed_line_distance(target_prefix)

    df["overtaker_center_cross_m"] = None
    df["overtaker_white_cross_m"] = None
    df["overtaken_center_cross_m"] = None
    df["overtaken_white_cross_m"] = None
    df["overtaker_center_cross"] = None
    df["overtaker_white_cross"] = None
    df["overtaken_center_cross"] = None
    df["overtaken_white_cross"] = None

    def _presence_from_status_or_cross(
        status_value: object,
        cross_value: object,
        lane_flag: Optional[str],
        expected_label: str,
        inside_label: str,
    ) -> str:
        if lane_flag in {"+", "-"}:
            return expected_label if lane_flag == "+" else inside_label
        if status_value is not None:
            status_text = str(status_value).strip()
            if status_text:
                if status_text == expected_label:
                    return expected_label
                if status_text == inside_label:
                    return inside_label
        if pd.notnull(cross_value):
            try:
                return expected_label if float(cross_value) > 0 else inside_label
            except (TypeError, ValueError):
                return "-"
        return "-"

    for idx, row in df.iterrows():
        def _resolve_cross(prefix: str) -> tuple[object, object, Optional[str], bool]:
            direction = str(row.get(f"{prefix}_travel_direction", "")).strip().upper()
            l_cross = row.get(f"{prefix}_l_line_cross_m")
            r_cross = row.get(f"{prefix}_r_line_cross_m")
            l_dist = row.get(f"{prefix}_l_line_distance_m")
            r_dist = row.get(f"{prefix}_r_line_distance_m")
            lane_flag = str(row.get(f"{prefix}_lane_position_flag") or "").strip()
            is_bike = _is_bike(row.get(f"{prefix}_class_name"))

            if direction == "F":
                white_cross = l_cross
                center_cross = r_cross
                white_dist = l_dist
                center_dist = r_dist
            else:
                center_cross = l_cross
                white_cross = r_cross
                center_dist = l_dist
                white_dist = r_dist

            if lane_flag in {"+", "-"}:
                if lane_flag == "+":
                    center_cross = center_dist
                    white_cross = white_dist
                else:
                    center_cross = None
                    white_cross = None

            if is_bike:
                center_cross = None
            else:
                white_cross = None

            return center_cross, white_cross, (lane_flag if lane_flag in {"+", "-"} else None), is_bike

        ot_center, ot_white, ot_lane_flag, ot_is_bike = _resolve_cross("overtaker")
        od_center, od_white, od_lane_flag, od_is_bike = _resolve_cross("overtaken")

        df.at[idx, "overtaker_center_cross_m"] = ot_center
        df.at[idx, "overtaker_white_cross_m"] = ot_white
        df.at[idx, "overtaken_center_cross_m"] = od_center
        df.at[idx, "overtaken_white_cross_m"] = od_white

        df.at[idx, "overtaker_center_cross"] = (
            _presence_from_status_or_cross(
                row.get("overtaker_center_status") if not ot_is_bike else None,
                ot_center,
                ot_lane_flag if not ot_is_bike else None,
                "中央線越え",
                "中央線内側",
            )
            if not ot_is_bike
            else "-"
        )
        df.at[idx, "overtaker_white_cross"] = (
            _presence_from_status_or_cross(
                row.get("overtaker_white_status") if ot_is_bike else None,
                ot_white,
                ot_lane_flag if ot_is_bike else None,
                "白線越え",
                "白線内側",
            )
            if ot_is_bike
            else "-"
        )
        df.at[idx, "overtaken_center_cross"] = (
            _presence_from_status_or_cross(
                row.get("overtaken_center_status") if not od_is_bike else None,
                od_center,
                od_lane_flag if not od_is_bike else None,
                "中央線越え",
                "中央線内側",
            )
            if not od_is_bike
            else "-"
        )
        df.at[idx, "overtaken_white_cross"] = (
            _presence_from_status_or_cross(
                row.get("overtaken_white_status") if od_is_bike else None,
                od_white,
                od_lane_flag if od_is_bike else None,
                "白線越え",
                "白線内側",
            )
            if od_is_bike
            else "-"
        )

    _round_columns(
        df,
        [
            "approach_distance_m",
            "clearance_distance_m",
            "clearance_distance_cm",
            "clearance_distance_px",
            "line_distance_m",
            "video_time_s",
            "overtaker_speed_km_h",
            "overtaker_pixel_speed",
            "overtaker_pixel_speed_frame",
            "overtaken_speed_km_h",
            "overtaken_pixel_speed",
            "overtaken_pixel_speed_frame",
            "overtaker_line_distance_m",
            "overtaker_line_distance_cm",
            "overtaker_line_distance_px",
            "overtaken_line_distance_m",
            "overtaken_line_distance_cm",
            "overtaken_line_distance_px",
            "overtaker_l_line_distance_m",
            "overtaker_l_line_distance_cm",
            "overtaker_l_line_distance_px",
            "overtaker_r_line_distance_m",
            "overtaker_r_line_distance_cm",
            "overtaker_r_line_distance_px",
            "overtaken_l_line_distance_m",
            "overtaken_l_line_distance_cm",
            "overtaken_l_line_distance_px",
            "overtaken_r_line_distance_m",
            "overtaken_r_line_distance_cm",
            "overtaken_r_line_distance_px",
            "overtaker_center_cross_m",
            "overtaker_white_cross_m",
            "overtaken_center_cross_m",
            "overtaken_white_cross_m",
        ],
        decimals=4,
    )

    df = df.rename(columns=_column_map())
    for col in _final_column_order():
        if col not in df.columns:
            df[col] = None
    df = df[_final_column_order()]

    output = io.BytesIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    return output.getvalue()


def _round_columns(df: pd.DataFrame, columns: list[str], decimals: int) -> None:
    for col in columns:
        if col not in df.columns:
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce").round(decimals)


def _column_map() -> dict[str, str]:
    return {
        "event_id": "イベントID",
        "run_id": "Run",
        "video_filename": "動画名",
        "offset_frame": "オフセットフレーム",
        "frame_num": "動画フレーム",
        "video_time_s": "動画時間(s)",
        "overtaker_group_id": "追い越し側Group",
        "overtaker_track_id": "追い越し側トラックID",
        "overtaker_auto_id": "追い越し側検出ID",
        "overtaker_class_id": "追い越し側クラスID",
        "overtaker_class_name": "追い越し側クラス",
        "overtaker_x1": "追い越し側BBOX x1",
        "overtaker_y1": "追い越し側BBOX y1",
        "overtaker_x2": "追い越し側BBOX x2",
        "overtaker_y2": "追い越し側BBOX y2",
        "overtaker_speed_km_h": "追い越し側時速(km/h)",
        "overtaker_pixel_speed": "追い越し側ピクセル速度(px/s)",
        "overtaker_pixel_speed_frame": "追い越し側ピクセル移動量(px/f)",
        "overtaker_measure_x": "追い越し側測定X(px)",
        "overtaker_measure_y": "追い越し側測定Y(px)",
        "overtaker_line_distance_m": "追い越し側 白線距離(m)",
        "overtaker_line_distance_cm": "追い越し側 白線距離(cm)",
        "overtaker_line_distance_px": "追い越し側 白線距離(px)",
        "overtaker_l_line_distance_m": "追い越し側 左白線距離(m)",
        "overtaker_l_line_distance_cm": "追い越し側 左白線距離(cm)",
        "overtaker_l_line_distance_px": "追い越し側 左白線距離(px)",
        "overtaker_r_line_distance_m": "追い越し側 右白線距離(m)",
        "overtaker_r_line_distance_cm": "追い越し側 右白線距離(cm)",
        "overtaker_r_line_distance_px": "追い越し側 右白線距離(px)",
        "overtaken_group_id": "追い越され側Group",
        "overtaken_track_id": "追い越され側トラックID",
        "overtaken_auto_id": "追い越され側検出ID",
        "overtaken_class_id": "追い越され側クラスID",
        "overtaken_class_name": "追い越され側クラス",
        "overtaken_x1": "追い越され側BBOX x1",
        "overtaken_y1": "追い越され側BBOX y1",
        "overtaken_x2": "追い越され側BBOX x2",
        "overtaken_y2": "追い越され側BBOX y2",
        "overtaken_speed_km_h": "追い越され側時速(km/h)",
        "overtaken_pixel_speed": "追い越され側ピクセル速度(px/s)",
        "overtaken_pixel_speed_frame": "追い越され側ピクセル移動量(px/f)",
        "overtaken_measure_x": "追い越され側測定X(px)",
        "overtaken_measure_y": "追い越され側測定Y(px)",
        "overtaken_line_distance_m": "追い越され側 白線距離(m)",
        "overtaken_line_distance_cm": "追い越され側 白線距離(cm)",
        "overtaken_line_distance_px": "追い越され側 白線距離(px)",
        "overtaken_l_line_distance_m": "追い越され側 左白線距離(m)",
        "overtaken_l_line_distance_cm": "追い越され側 左白線距離(cm)",
        "overtaken_l_line_distance_px": "追い越され側 左白線距離(px)",
        "overtaken_r_line_distance_m": "追い越され側 右白線距離(m)",
        "overtaken_r_line_distance_cm": "追い越され側 右白線距離(cm)",
        "overtaken_r_line_distance_px": "追い越され側 右白線距離(px)",
        "clearance_distance_m": "離隔距離(m)",
        "clearance_distance_cm": "離隔距離(cm)",
        "clearance_distance_px": "離隔距離(px)",
        "overtaker_center_cross_m": "追い越し側 中央線越え(m)",
        "overtaken_center_cross_m": "追い越され側 中央線越え(m)",
        "overtaken_white_cross_m": "追い越され側 白線越え(m)",
        "overtaker_center_cross": "追い越し側 中央線越え",
        "overtaker_white_cross": "追い越し側 白線越え",
        "overtaken_center_cross": "追い越され側 中央線越え",
        "overtaken_white_cross": "追い越され側 白線越え",
        "collection_year": "採取年度",
        "road_type": "道種",
    }


def _final_column_order() -> list[str]:
    return [
        "イベントID",
        "Run",
        "動画名",
        "オフセットフレーム",
        "動画フレーム",
        "動画時間(s)",
        "追い越し側Group",
        "追い越し側トラックID",
        "追い越し側検出ID",
        "追い越し側クラスID",
        "追い越し側クラス",
        "追い越し側BBOX x1",
        "追い越し側BBOX y1",
        "追い越し側BBOX x2",
        "追い越し側BBOX y2",
        "追い越し側時速(km/h)",
        "追い越し側ピクセル速度(px/s)",
        "追い越し側ピクセル移動量(px/f)",
        "追い越し側測定X(px)",
        "追い越し側測定Y(px)",
        "追い越し側 白線距離(m)",
        "追い越し側 白線距離(cm)",
        "追い越し側 白線距離(px)",
        "追い越し側 左白線距離(m)",
        "追い越し側 左白線距離(cm)",
        "追い越し側 左白線距離(px)",
        "追い越し側 右白線距離(m)",
        "追い越し側 右白線距離(cm)",
        "追い越し側 右白線距離(px)",
        "追い越され側Group",
        "追い越され側トラックID",
        "追い越され側検出ID",
        "追い越され側クラスID",
        "追い越され側クラス",
        "追い越され側BBOX x1",
        "追い越され側BBOX y1",
        "追い越され側BBOX x2",
        "追い越され側BBOX y2",
        "追い越され側時速(km/h)",
        "追い越され側ピクセル速度(px/s)",
        "追い越され側ピクセル移動量(px/f)",
        "追い越され側測定X(px)",
        "追い越され側測定Y(px)",
        "追い越され側 白線距離(m)",
        "追い越され側 白線距離(cm)",
        "追い越され側 白線距離(px)",
        "追い越され側 左白線距離(m)",
        "追い越され側 左白線距離(cm)",
        "追い越され側 左白線距離(px)",
        "追い越され側 右白線距離(m)",
        "追い越され側 右白線距離(cm)",
        "追い越され側 右白線距離(px)",
        "離隔距離(m)",
        "離隔距離(cm)",
        "離隔距離(px)",
        "追い越し側 中央線越え(m)",
        "追い越され側 中央線越え(m)",
        "追い越され側 白線越え(m)",
        "追い越し側 中央線越え",
        "追い越し側 白線越え",
        "追い越され側 中央線越え",
        "追い越され側 白線越え",
        "採取年度",
        "道種",
    ]
