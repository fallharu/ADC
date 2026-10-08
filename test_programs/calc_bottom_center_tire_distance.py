from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "my_app_data.db"
TIRE_POINT_CHOICES = (
    "center",
    "bottom_center",
    "bottom_left",
    "bottom_right",
    "nearest_bottom_corner",
    "nearest_any",
)
TIRE_POINT_LABELS = {
    "center": "タイヤ中心",
    "bottom_center": "タイヤ下端中央",
    "bottom_left": "タイヤ左下",
    "bottom_right": "タイヤ右下",
    "nearest_bottom_corner": "近い下端角",
    "nearest_any": "最も近い点",
}
TIRE_POINT_BY_LABEL = {label: key for key, label in TIRE_POINT_LABELS.items()}


@dataclass(frozen=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    @property
    def bottom_center(self) -> tuple[float, float]:
        # 既存の BoundingBox と同じ定義: x は bbox 中心、y は下端。
        return ((self.x1 + self.x2) / 2.0, self.y2)

    @property
    def bottom_left(self) -> tuple[float, float]:
        return (self.x1, self.y2)

    @property
    def bottom_right(self) -> tuple[float, float]:
        return (self.x2, self.y2)

    @property
    def area(self) -> float:
        return max(0.0, abs(self.x2 - self.x1) * abs(self.y2 - self.y1))


def parse_bbox(value: str) -> BoundingBox:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox は x1,y1,x2,y2 の形式で入力してください")
    try:
        x1, y1, x2, y2 = (float(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("bbox の値は数値で入力してください") from exc
    return BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)


def point_distance_px(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def tire_points(tire: BoundingBox) -> dict[str, tuple[float, float]]:
    return {
        "center": tire.center,
        "bottom_center": tire.bottom_center,
        "bottom_left": tire.bottom_left,
        "bottom_right": tire.bottom_right,
    }


def select_tire_point(
    vehicle_bottom_center: tuple[float, float],
    tire: BoundingBox,
    point_name: str,
) -> tuple[str, tuple[float, float]]:
    points = tire_points(tire)
    if point_name == "nearest_bottom_corner":
        bottom_corners = {
            "bottom_left": points["bottom_left"],
            "bottom_right": points["bottom_right"],
        }
        return min(
            bottom_corners.items(),
            key=lambda item: point_distance_px(vehicle_bottom_center, item[1]),
        )
    if point_name == "nearest_any":
        return min(
            points.items(),
            key=lambda item: point_distance_px(vehicle_bottom_center, item[1]),
        )
    return point_name, points[point_name]


def distance_report(
    vehicle: BoundingBox,
    tire: BoundingBox,
    tire_point: str,
) -> dict[str, object]:
    vehicle_point = vehicle.bottom_center
    selected_name, selected_point = select_tire_point(vehicle_point, tire, tire_point)
    all_distances = {
        name: point_distance_px(vehicle_point, point)
        for name, point in tire_points(tire).items()
    }
    all_distances["nearest_bottom_corner"] = min(
        all_distances["bottom_left"],
        all_distances["bottom_right"],
    )
    all_distances["nearest_any"] = min(
        all_distances["center"],
        all_distances["bottom_center"],
        all_distances["bottom_left"],
        all_distances["bottom_right"],
    )

    return {
        "vehicle_bottom_center": vehicle_point,
        "tire_point_name": selected_name,
        "tire_point": selected_point,
        "distance_px": point_distance_px(vehicle_point, selected_point),
        "all_distances_px": all_distances,
    }


def is_tire_row(row: Mapping[str, object]) -> bool:
    class_name = str(row.get("class_name") or "").lower()
    model_name = str(row.get("model_name") or "").lower()
    try:
        class_id = int(row.get("class_id")) if row.get("class_id") is not None else None
    except (TypeError, ValueError):
        class_id = None

    if "plate" in class_name or "number" in class_name:
        return False
    if "tire" in class_name or "tyre" in class_name or "wheel" in class_name:
        return True
    if class_id in {100, 102}:
        return True
    return model_name in {"best", "best.pt"} and class_id != 101


def row_to_bbox(row: Mapping[str, object]) -> BoundingBox:
    return BoundingBox(
        x1=float(row["x1"]),
        y1=float(row["y1"]),
        x2=float(row["x2"]),
        y2=float(row["y2"]),
    )


def overlap_area(a: BoundingBox, b: BoundingBox) -> float:
    x_left = max(a.x1, b.x1)
    y_top = max(a.y1, b.y1)
    x_right = min(a.x2, b.x2)
    y_bottom = min(a.y2, b.y2)
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0
    return (x_right - x_left) * (y_bottom - y_top)


def dict_rows(conn: sqlite3.Connection, sql: str, params: Iterable[object]) -> list[dict[str, object]]:
    cursor = conn.execute(sql, tuple(params))
    return [dict(row) for row in cursor.fetchall()]


def detection_select_sql(where_sql: str) -> str:
    return f"""
        SELECT
            d.auto_id,
            d.run_id,
            d.frame_num,
            d.group_id,
            d.track_id,
            d.class_id,
            COALESCE(NULLIF(d.class_name, ''), cls.class_name, cm.class_name) AS class_name,
            d.model_name,
            d.x1,
            d.y1,
            d.x2,
            d.y2
        FROM Detection d
        LEFT JOIN Class cls ON cls.class_id = d.class_id
        LEFT JOIN ClassMaster cm ON cm.class_id = d.class_id
        WHERE {where_sql}
    """


def fetch_detection_by_auto_id(conn: sqlite3.Connection, auto_id: int) -> dict[str, object]:
    rows = dict_rows(
        conn,
        detection_select_sql("d.auto_id = ?"),
        (auto_id,),
    )
    if not rows:
        raise ValueError(f"Detection auto_id={auto_id} が見つかりません")
    return rows[0]


def fetch_frame_detections(
    conn: sqlite3.Connection,
    run_id: int,
    frame_num: int,
    group_id: Optional[int],
) -> list[dict[str, object]]:
    where = "d.run_id = ? AND d.frame_num = ?"
    params: list[object] = [run_id, frame_num]
    if group_id is not None:
        where += " AND d.group_id = ?"
        params.append(group_id)
    return dict_rows(conn, detection_select_sql(where), params)


def pick_vehicle(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    vehicles = [row for row in rows if not is_tire_row(row)]
    if not vehicles:
        raise ValueError("指定したフレーム/グループに車両検出が見つかりません")
    return max(vehicles, key=lambda row: row_to_bbox(row).area)


def pick_tire(
    rows: Sequence[dict[str, object]],
    vehicle: Mapping[str, object],
) -> dict[str, object]:
    tires = [row for row in rows if is_tire_row(row)]
    if not tires:
        raise ValueError("指定したフレーム/グループにタイヤ検出が見つかりません")

    vehicle_box = row_to_bbox(vehicle)
    vehicle_point = vehicle_box.bottom_center

    def rank(row: Mapping[str, object]) -> tuple[float, float]:
        tire_box = row_to_bbox(row)
        # 車両 bbox と重なるタイヤを優先し、複数ある場合は車両下端中央に近いものを使う。
        return (
            -overlap_area(vehicle_box, tire_box),
            point_distance_px(vehicle_point, tire_box.bottom_center),
        )

    return min(tires, key=rank)


def resolve_boxes_from_db(args: argparse.Namespace) -> tuple[BoundingBox, BoundingBox, dict[str, object], dict[str, object]]:
    db_path = Path(args.db)
    if not db_path.exists():
        raise FileNotFoundError(f"DBファイルが見つかりません: {db_path}")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        if args.vehicle_auto_id is not None:
            vehicle_row = fetch_detection_by_auto_id(conn, args.vehicle_auto_id)
        else:
            if args.run_id is None or args.frame is None:
                raise ValueError("--vehicle-auto-id を使わない場合は --run-id と --frame が必要です")
            frame_rows = fetch_frame_detections(conn, args.run_id, args.frame, args.group_id)
            vehicle_row = pick_vehicle(frame_rows)

        if args.tire_auto_id is not None:
            tire_row = fetch_detection_by_auto_id(conn, args.tire_auto_id)
        else:
            run_id = int(vehicle_row["run_id"])
            frame_num = int(vehicle_row["frame_num"])
            group_value = args.group_id
            if group_value is None and vehicle_row.get("group_id") is not None:
                group_value = int(vehicle_row["group_id"])

            frame_rows = fetch_frame_detections(conn, run_id, frame_num, group_value)
            try:
                tire_row = pick_tire(frame_rows, vehicle_row)
            except ValueError:
                # タイヤに group_id が未付与の場合に備え、同じフレーム全体から再検索する。
                frame_rows = fetch_frame_detections(conn, run_id, frame_num, None)
                tire_row = pick_tire(frame_rows, vehicle_row)

    return row_to_bbox(vehicle_row), row_to_bbox(tire_row), vehicle_row, tire_row


def format_point(point: Sequence[float]) -> str:
    return f"({float(point[0]):.2f}, {float(point[1]):.2f})"


def build_report_text(
    report: Mapping[str, object],
    vehicle_meta: Optional[Mapping[str, object]] = None,
    tire_meta: Optional[Mapping[str, object]] = None,
) -> str:
    lines: list[str] = []
    if vehicle_meta:
        lines.append(
            "車両: "
            f"auto_id={vehicle_meta.get('auto_id')} "
            f"run_id={vehicle_meta.get('run_id')} "
            f"frame_num={vehicle_meta.get('frame_num')} "
            f"group_id={vehicle_meta.get('group_id')} "
            f"class={vehicle_meta.get('class_name')}"
        )
    if tire_meta:
        lines.append(
            "タイヤ: "
            f"auto_id={tire_meta.get('auto_id')} "
            f"run_id={tire_meta.get('run_id')} "
            f"frame_num={tire_meta.get('frame_num')} "
            f"group_id={tire_meta.get('group_id')} "
            f"class={tire_meta.get('class_name')}"
        )

    tire_point_name = str(report["tire_point_name"])
    tire_point_label = TIRE_POINT_LABELS.get(tire_point_name, tire_point_name)
    lines.append(f"車両下端中央: {format_point(report['vehicle_bottom_center'])}")
    lines.append(f"タイヤ基準点[{tire_point_label}]: {format_point(report['tire_point'])}")
    lines.append(f"ピクセル距離: {float(report['distance_px']):.3f} px")

    distances = report["all_distances_px"]
    if isinstance(distances, Mapping):
        lines.append("基準点別ピクセル距離:")
        for name in (
            "center",
            "bottom_center",
            "bottom_left",
            "bottom_right",
            "nearest_bottom_corner",
            "nearest_any",
        ):
            label = TIRE_POINT_LABELS.get(name, name)
            lines.append(f"  {label}: {float(distances[name]):.3f} px")
    return "\n".join(lines)


def print_report(
    report: Mapping[str, object],
    vehicle_meta: Optional[Mapping[str, object]] = None,
    tire_meta: Optional[Mapping[str, object]] = None,
) -> None:
    print(build_report_text(report, vehicle_meta, tire_meta))


def find_sample_group(db_path: Path) -> Optional[dict[str, int]]:
    if not db_path.exists():
        raise FileNotFoundError(f"DBファイルが見つかりません: {db_path}")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                d.run_id,
                d.frame_num,
                d.group_id,
                COUNT(*) AS total_count,
                SUM(
                    CASE
                        WHEN (
                            LOWER(COALESCE(d.class_name, '')) LIKE '%tire%'
                            OR LOWER(COALESCE(d.class_name, '')) LIKE '%tyre%'
                            OR LOWER(COALESCE(d.class_name, '')) LIKE '%wheel%'
                            OR (
                                LOWER(COALESCE(d.model_name, '')) IN ('best', 'best.pt')
                                AND COALESCE(d.class_id, -1) != 101
                            )
                        )
                        AND LOWER(COALESCE(d.class_name, '')) NOT LIKE '%plate%'
                        AND LOWER(COALESCE(d.class_name, '')) NOT LIKE '%number%'
                        THEN 1 ELSE 0
                    END
                ) AS tire_count,
                SUM(
                    CASE
                        WHEN NOT (
                            (
                                LOWER(COALESCE(d.class_name, '')) LIKE '%tire%'
                                OR LOWER(COALESCE(d.class_name, '')) LIKE '%tyre%'
                                OR LOWER(COALESCE(d.class_name, '')) LIKE '%wheel%'
                                OR (
                                    LOWER(COALESCE(d.model_name, '')) IN ('best', 'best.pt')
                                    AND COALESCE(d.class_id, -1) != 101
                                )
                            )
                            AND LOWER(COALESCE(d.class_name, '')) NOT LIKE '%plate%'
                            AND LOWER(COALESCE(d.class_name, '')) NOT LIKE '%number%'
                        )
                        THEN 1 ELSE 0
                    END
                ) AS vehicle_count
            FROM Detection d
            WHERE d.group_id IS NOT NULL
              AND d.x1 IS NOT NULL
              AND d.y1 IS NOT NULL
              AND d.x2 IS NOT NULL
              AND d.y2 IS NOT NULL
            GROUP BY d.run_id, d.frame_num, d.group_id
            HAVING tire_count > 0 AND vehicle_count > 0
            ORDER BY d.run_id DESC, d.frame_num ASC, d.group_id ASC
            LIMIT 1
            """
        ).fetchall()

    if not rows:
        return None
    row = rows[0]
    return {
        "run_id": int(row["run_id"]),
        "frame": int(row["frame_num"]),
        "group_id": int(row["group_id"]),
    }


def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    tire_point_labels = [TIRE_POINT_LABELS[key] for key in TIRE_POINT_CHOICES]

    class DistanceGui(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("車両下端中央とタイヤのピクセル距離")
            self.geometry("980x680")
            self.minsize(860, 560)

            self.mode_var = tk.StringVar(value="db")
            self.db_var = tk.StringVar(value=str(DEFAULT_DB_PATH))
            self.run_id_var = tk.StringVar()
            self.frame_var = tk.StringVar()
            self.group_id_var = tk.StringVar()
            self.vehicle_auto_id_var = tk.StringVar()
            self.tire_auto_id_var = tk.StringVar()
            self.vehicle_bbox_var = tk.StringVar(value="100,100,300,300")
            self.tire_bbox_var = tk.StringVar(value="260,250,280,270")
            self.tire_point_var = tk.StringVar(value=TIRE_POINT_LABELS["bottom_center"])

            self._build_ui()

        def _build_ui(self) -> None:
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

            self.columnconfigure(0, weight=1)
            self.rowconfigure(2, weight=1)

            top = ttk.Frame(self, padding=(10, 10))
            top.grid(row=0, column=0, sticky="ew")
            top.columnconfigure(0, weight=1)

            ttk.Label(
                top,
                text="車両の真ん中下部とタイヤのピクセル距離",
                font=("Yu Gothic UI", 14, "bold"),
            ).grid(row=0, column=0, sticky="w")

            mode_frame = ttk.LabelFrame(self, text="入力方法", padding=(10, 8))
            mode_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
            mode_frame.columnconfigure(1, weight=1)
            ttk.Radiobutton(
                mode_frame,
                text="Detection DBから読み込む",
                value="db",
                variable=self.mode_var,
            ).grid(row=0, column=0, sticky="w", padx=(0, 16))
            ttk.Radiobutton(
                mode_frame,
                text="bbox座標を直接入力する",
                value="bbox",
                variable=self.mode_var,
            ).grid(row=0, column=1, sticky="w")

            main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
            main.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

            inputs = ttk.Frame(main)
            output = ttk.Frame(main)
            main.add(inputs, weight=2)
            main.add(output, weight=3)

            self._build_db_inputs(inputs)
            self._build_bbox_inputs(inputs)
            self._build_actions(inputs)
            self._build_output(output)

        def _build_db_inputs(self, parent: ttk.Frame) -> None:
            frame = ttk.LabelFrame(parent, text="DB入力", padding=(10, 8))
            frame.pack(fill=tk.X, pady=(0, 8))
            frame.columnconfigure(1, weight=1)

            ttk.Label(frame, text="DBファイル").grid(row=0, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=self.db_var).grid(row=0, column=1, sticky="ew", padx=6, pady=3)
            ttk.Button(frame, text="参照", command=self._browse_db).grid(row=0, column=2, pady=3)

            ttk.Label(frame, text="run_id").grid(row=1, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=self.run_id_var, width=14).grid(row=1, column=1, sticky="w", padx=6, pady=3)

            ttk.Label(frame, text="frame_num").grid(row=2, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=self.frame_var, width=14).grid(row=2, column=1, sticky="w", padx=6, pady=3)

            ttk.Label(frame, text="group_id").grid(row=3, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=self.group_id_var, width=14).grid(row=3, column=1, sticky="w", padx=6, pady=3)

            ttk.Label(frame, text="車両auto_id").grid(row=4, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=self.vehicle_auto_id_var, width=14).grid(row=4, column=1, sticky="w", padx=6, pady=3)

            ttk.Label(frame, text="タイヤauto_id").grid(row=5, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=self.tire_auto_id_var, width=14).grid(row=5, column=1, sticky="w", padx=6, pady=3)

            ttk.Button(frame, text="サンプルを検索", command=self._fill_sample).grid(
                row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0)
            )

        def _build_bbox_inputs(self, parent: ttk.Frame) -> None:
            frame = ttk.LabelFrame(parent, text="bbox直接入力", padding=(10, 8))
            frame.pack(fill=tk.X, pady=(0, 8))
            frame.columnconfigure(1, weight=1)

            ttk.Label(frame, text="車両bbox").grid(row=0, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=self.vehicle_bbox_var).grid(row=0, column=1, sticky="ew", padx=6, pady=3)
            ttk.Label(frame, text="x1,y1,x2,y2").grid(row=0, column=2, sticky="w", pady=3)

            ttk.Label(frame, text="タイヤbbox").grid(row=1, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=self.tire_bbox_var).grid(row=1, column=1, sticky="ew", padx=6, pady=3)
            ttk.Label(frame, text="x1,y1,x2,y2").grid(row=1, column=2, sticky="w", pady=3)

        def _build_actions(self, parent: ttk.Frame) -> None:
            frame = ttk.LabelFrame(parent, text="計算", padding=(10, 8))
            frame.pack(fill=tk.X)
            frame.columnconfigure(1, weight=1)

            ttk.Label(frame, text="タイヤ基準点").grid(row=0, column=0, sticky="w", pady=3)
            ttk.Combobox(
                frame,
                textvariable=self.tire_point_var,
                values=tire_point_labels,
                state="readonly",
            ).grid(row=0, column=1, sticky="ew", padx=6, pady=3)

            ttk.Button(frame, text="計算", command=self._calculate).grid(
                row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0)
            )
            ttk.Button(frame, text="結果をクリア", command=self._clear_output).grid(
                row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0)
            )

        def _build_output(self, parent: ttk.Frame) -> None:
            parent.columnconfigure(0, weight=1)
            parent.rowconfigure(0, weight=1)

            out_frame = ttk.LabelFrame(parent, text="結果", padding=(8, 8))
            out_frame.grid(row=0, column=0, sticky="nsew")
            out_frame.columnconfigure(0, weight=1)
            out_frame.rowconfigure(0, weight=1)

            self.output_text = tk.Text(out_frame, wrap="word", font=("Consolas", 10))
            self.output_text.grid(row=0, column=0, sticky="nsew")
            scrollbar = ttk.Scrollbar(out_frame, orient="vertical", command=self.output_text.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            self.output_text.configure(yscrollcommand=scrollbar.set)

        def _browse_db(self) -> None:
            path = filedialog.askopenfilename(
                title="SQLite DBを選択",
                initialdir=str(DEFAULT_DB_PATH.parent),
                filetypes=(("SQLite DB", "*.db"), ("すべてのファイル", "*.*")),
            )
            if path:
                self.db_var.set(path)

        def _optional_int(self, value: str, label: str) -> Optional[int]:
            text = value.strip()
            if not text:
                return None
            try:
                return int(text)
            except ValueError as exc:
                raise ValueError(f"{label} は整数で入力してください") from exc

        def _fill_sample(self) -> None:
            try:
                sample = find_sample_group(Path(self.db_var.get().strip()))
            except Exception as exc:
                messagebox.showerror("エラー", str(exc))
                return
            if not sample:
                messagebox.showinfo("サンプルなし", "車両とタイヤの両方があるフレーム/グループが見つかりませんでした。")
                return
            self.mode_var.set("db")
            self.run_id_var.set(str(sample["run_id"]))
            self.frame_var.set(str(sample["frame"]))
            self.group_id_var.set(str(sample["group_id"]))
            self.vehicle_auto_id_var.set("")
            self.tire_auto_id_var.set("")
            self._write_output(
                "サンプルを入力しました:\n"
                f"run_id={sample['run_id']}, frame_num={sample['frame']}, group_id={sample['group_id']}\n"
            )

        def _calculate(self) -> None:
            try:
                if self.mode_var.get() == "bbox":
                    vehicle_box = parse_bbox(self.vehicle_bbox_var.get())
                    tire_box = parse_bbox(self.tire_bbox_var.get())
                    vehicle_meta = None
                    tire_meta = None
                else:
                    args = argparse.Namespace(
                        db=self.db_var.get().strip(),
                        run_id=self._optional_int(self.run_id_var.get(), "run_id"),
                        frame=self._optional_int(self.frame_var.get(), "frame_num"),
                        group_id=self._optional_int(self.group_id_var.get(), "group_id"),
                        vehicle_auto_id=self._optional_int(
                            self.vehicle_auto_id_var.get(),
                            "vehicle_auto_id",
                        ),
                        tire_auto_id=self._optional_int(self.tire_auto_id_var.get(), "tire_auto_id"),
                    )
                    vehicle_box, tire_box, vehicle_meta, tire_meta = resolve_boxes_from_db(args)

                tire_point_key = TIRE_POINT_BY_LABEL.get(
                    self.tire_point_var.get(),
                    self.tire_point_var.get(),
                )
                report = distance_report(vehicle_box, tire_box, tire_point_key)
                self._write_output(build_report_text(report, vehicle_meta, tire_meta) + "\n")
            except Exception as exc:
                messagebox.showerror("計算エラー", str(exc))

        def _write_output(self, text: str) -> None:
            self.output_text.insert("end", text + "\n")
            self.output_text.see("end")

        def _clear_output(self) -> None:
            self.output_text.delete("1.0", "end")

    app = DistanceGui()
    app.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "車両bboxの下端中央とタイヤbbox基準点のピクセル距離を計算します。"
        ),
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="このヘルプを表示して終了")
    parser._optionals.title = "オプション"
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite DBファイルのパス")
    parser.add_argument("--run-id", type=int, help="DB入力で使う Detection.run_id")
    parser.add_argument("--frame", type=int, help="DB入力で使う Detection.frame_num")
    parser.add_argument("--group-id", type=int, help="任意の Detection.group_id フィルタ")
    parser.add_argument("--vehicle-auto-id", type=int, help="車両の Detection.auto_id")
    parser.add_argument("--tire-auto-id", type=int, help="タイヤの Detection.auto_id")
    parser.add_argument("--vehicle", type=parse_bbox, help="車両bboxを直接指定: x1,y1,x2,y2")
    parser.add_argument("--tire", type=parse_bbox, help="タイヤbboxを直接指定: x1,y1,x2,y2")
    parser.add_argument(
        "--tire-point",
        choices=TIRE_POINT_CHOICES,
        default="bottom_center",
        help="距離計算に使うタイヤ基準点",
    )
    parser.add_argument("--gui", action="store_true", help="Tkinter GUIを起動")
    return parser


def main() -> None:
    if len(sys.argv) == 1:
        launch_gui()
        return

    args = build_parser().parse_args()
    if args.gui:
        launch_gui()
        return

    if args.vehicle is not None or args.tire is not None:
        if args.vehicle is None or args.tire is None:
            raise SystemExit("--vehicle と --tire はセットで指定してください")
        vehicle_box = args.vehicle
        tire_box = args.tire
        vehicle_meta = None
        tire_meta = None
    else:
        vehicle_box, tire_box, vehicle_meta, tire_meta = resolve_boxes_from_db(args)

    report = distance_report(vehicle_box, tire_box, args.tire_point)
    print_report(report, vehicle_meta, tire_meta)


if __name__ == "__main__":
    main()
