# 役割: 自転車と車の接近距離・離隔距離を計算し、Detectionテーブルに保存する
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from ..calibration_loader import load_calibration_json
from ..db_manager import MAIN_DB_PATH, configure_connection
from ..manual_metrics import lane_scale_at_point
from ..measure_points import attach_measure_points, compute_front_right_tire_points
from ..perf_utils import resolve_worker_count

DEFAULT_BICYCLE_CLASSES = {"bicycle", "bike", "cyclist"}
DEFAULT_CAR_CLASSES = {"car", "automobile", "vehicle", "truck", "bus", "van"}


@dataclass(frozen=True)
class _DistanceResult:
    distance_px: float
    distance_m: Optional[float]
    distance_cm: Optional[float]


def _parse_class_list(env_value: Optional[str], fallback: Iterable[str]) -> set[str]:
    if not env_value:
        return {c.lower() for c in fallback}
    parsed = {token.strip().lower() for token in env_value.split(',') if token.strip()}
    return parsed or {c.lower() for c in fallback}


def _float_or_none(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, (float, np.floating)) and np.isnan(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Optional[float]) -> Optional[int]:
    if value is None:
        return None
    try:
        if isinstance(value, (float, np.floating)) and np.isnan(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _compute_distance(
    row_a: pd.Series,
    row_b: pd.Series,
    left_line,
    right_line,
    center_line,
    left_inner_line,
    right_inner_line,
    lane_width_m: float = 3.5,
) -> _DistanceResult:
    ax, ay = float(row_a['measure_x']), float(row_a['measure_y'])
    bx, by = float(row_b['measure_x']), float(row_b['measure_y'])
    dx_px = ax - bx
    dy_px = ay - by
    distance_px = float(np.hypot(dx_px, dy_px))

    x_scales: list[float] = []
    if left_line or right_line:
        for row in (row_a, row_b):
            scale = lane_scale_at_point(
                _float_or_none(row.get('measure_x')),
                _float_or_none(row.get('measure_y')),
                left_line,
                right_line,
                center_line,
                left_inner_line,
                right_inner_line,
                lane_width_m=lane_width_m,
            )
            if scale and scale > 0:
                x_scales.append(float(scale))

    y_scales = [
        _float_or_none(row_a.get('scale_pixels_per_meter')),
        _float_or_none(row_b.get('scale_pixels_per_meter')),
    ]
    y_scales = [val for val in y_scales if val and val > 0]

    avg_x = float(np.mean(x_scales)) if x_scales else None
    avg_y = float(np.mean(y_scales)) if y_scales else None

    # ユーザー要望: Verifyで作成したスケール(lane_width_mに基づくスケール)を優先利用する
    # lane_scale_at_point が返すスケールは lane_width_m に基づくため、
    # avg_x が存在すればそれを優先的に距離換算に利用する。
    
    distance_m: Optional[float] = None
    if avg_x and avg_y:
        dx_m = abs(dx_px) / avg_x
        dy_m = abs(dy_px) / avg_y
        distance_m = float(np.hypot(dx_m, dy_m))
    elif avg_x:
        distance_m = abs(dx_px) / avg_x
    elif avg_y:
        distance_m = abs(dy_px) / avg_y

    distance_cm: Optional[float] = None
    if distance_m is not None:
        distance_cm = float(distance_m * 100.0)

    return _DistanceResult(distance_px, distance_m, distance_cm)


def assign_approach_and_clearance(run_id: int) -> None:
    """
    指定Run IDに対し、同一フレーム内に存在する自転車と車の組み合わせについて
    接近距離（全フレーム）と、追い越し判定のあるフレームでの離隔距離を計算する。
    結果は Detection テーブルの各行へ保存する。
    """

    load_dotenv()
    bicycle_classes = _parse_class_list(os.getenv("APPROACH_BICYCLE_CLASSES"), DEFAULT_BICYCLE_CLASSES)
    car_classes = _parse_class_list(os.getenv("APPROACH_CAR_CLASSES"), DEFAULT_CAR_CLASSES)

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        profile_row = conn.execute(
            "SELECT calibration_profile FROM ProcessLog WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        df = pd.read_sql_query(
            """
            SELECT d.auto_id, d.frame_num, d.group_id, d.x1, d.y1, d.x2, d.y2,
                   d.overtake, d.overtake_by, d.scale_pixels_per_meter, d.x_pixels_per_meter,
                   d.travel_direction,
                   d.model_name, c.class_name
            FROM Detection d
            JOIN Class c ON d.class_id = c.class_id
            WHERE d.run_id = ? AND d.group_id IS NOT NULL
            ORDER BY d.frame_num, d.group_id
            """,
            conn,
            params=(run_id,),
        )

    profile_name = profile_row[0] if profile_row and profile_row[0] else None
    calibration_data = None
    try:
        calibration_data, _ = load_calibration_json(run_id, profile_name)
    except FileNotFoundError:
        calibration_data = None
    except Exception as exc:  # noqa: BLE001
        calibration_data = None
        print(f"[assign_approach_and_clearance] キャリブレーション読込に失敗しました: {exc}")

    from ..manual_metrics import load_white_lines, LANE_WIDTH_METERS
    lane_lines = load_white_lines(calibration_data)
    left_line, right_line, center_line = lane_lines
    left_inner_line = lane_lines.left_inner
    right_inner_line = lane_lines.right_inner
    
    # 校正データから車線幅を取得 (検証済みスケール)
    calib_lane_width = LANE_WIDTH_METERS
    if calibration_data:
        # JSONキーは lane_width_m と想定
        val = _float_or_none(calibration_data.get("lane_width_m"))
        if val is not None and val > 0:
            calib_lane_width = val

    if df.empty:
        print(f"Run ID {run_id}: 接近距離を計算する対象データがありません。")
        return

    df['class_lower'] = df['class_name'].str.lower()

    vehicles = df[df['model_name'] != 'best'].copy()
    
    # ユーザー要望対応: グループ中心座標を事前計算 (タイヤの左右判定に使用)
    # 車両(Car/Bus/Truck)のグループBBOX中心を基準にタイヤをフィルタリングする
    vehicles['center_x'] = (vehicles['x1'] + vehicles['x2']) / 2.0
    group_centers = {}
    # フレーム番号とグループIDをキーにして中心座標を辞書化
    for row in vehicles.itertuples():
         group_centers[(float(row.frame_num), float(row.group_id))] = float(row.center_x)

    tyre_points = compute_front_right_tire_points(
        df[df['model_name'] == 'best'],
        left_line,
        right_line,
        group_centers=group_centers,
    )

    vehicles = attach_measure_points(
        vehicles,
        tyre_points,
        left_line=left_line,
        right_line=right_line,
    )

    vehicles['valid_measure'] = np.isfinite(vehicles['measure_x']) & np.isfinite(vehicles['measure_y'])

    vehicles['approach_distance_px'] = np.nan
    vehicles['approach_distance_m'] = np.nan
    vehicles['approach_partner_group_id'] = np.nan
    vehicles['clearance_distance_px'] = np.nan
    vehicles['clearance_distance_m'] = np.nan
    vehicles['clearance_distance_cm'] = np.nan

    def process_frame(args: Tuple[int, pd.DataFrame]) -> Dict[int, Dict[str, Optional[float]]]:
        frame_num, frame_df = args
        local_updates: Dict[int, Dict[str, Optional[float]]] = {}

        bikes = frame_df[
            frame_df['class_lower'].isin(bicycle_classes) & frame_df['valid_measure']
        ]
        cars = frame_df[
            frame_df['class_lower'].isin(car_classes) & frame_df['valid_measure']
        ]
        if bikes.empty or cars.empty:
            return {}

        distance_cache: Dict[Tuple[int, int], _DistanceResult] = {}

        for bike_idx, bike_row in bikes.iterrows():
            for car_idx, car_row in cars.iterrows():
                gid_bike = _int_or_none(bike_row['group_id'])
                gid_car = _int_or_none(car_row['group_id'])
                if gid_bike is None or gid_car is None:
                    continue

                distance_cache[(bike_idx, car_idx)] = _compute_distance(
                    bike_row,
                    car_row,
                    left_line,
                    right_line,
                    center_line,
                    left_inner_line,
                    right_inner_line,
                    lane_width_m=calib_lane_width,
                )

                dir_bike = str(bike_row.get('travel_direction') or '').strip()
                dir_car = str(car_row.get('travel_direction') or '').strip()
                if dir_bike and dir_car and dir_bike != dir_car:
                    local_updates.setdefault(int(bike_idx), {})['oncoming_flag'] = 1
                    local_updates.setdefault(int(car_idx), {})['oncoming_flag'] = 1

        for bike_idx in bikes.index:
            candidates = [
                (car_idx, distance_cache[(bike_idx, car_idx)])
                for car_idx in cars.index
                if (bike_idx, car_idx) in distance_cache
            ]
            if not candidates:
                continue
            best_car_idx, best_dist = min(candidates, key=lambda item: item[1].distance_px)
            partner_group = _int_or_none(frame_df.at[best_car_idx, 'group_id'])
            entry = local_updates.setdefault(int(bike_idx), {})
            entry['approach_distance_px'] = best_dist.distance_px
            entry['approach_distance_m'] = best_dist.distance_m
            entry['approach_partner_group_id'] = partner_group

        for car_idx in cars.index:
            candidates = [
                (bike_idx, distance_cache[(bike_idx, car_idx)])
                for bike_idx in bikes.index
                if (bike_idx, car_idx) in distance_cache
            ]
            if not candidates:
                continue
            best_bike_idx, best_dist = min(candidates, key=lambda item: item[1].distance_px)
            partner_group = _int_or_none(frame_df.at[best_bike_idx, 'group_id'])
            entry = local_updates.setdefault(int(car_idx), {})
            entry['approach_distance_px'] = best_dist.distance_px
            entry['approach_distance_m'] = best_dist.distance_m
            entry['approach_partner_group_id'] = partner_group

        pair_distances: Dict[Tuple[int, int], Dict[str, Optional[float]]] = {}
        for (bike_idx, car_idx), distance in distance_cache.items():
            gid_bike = _int_or_none(frame_df.at[bike_idx, 'group_id'])
            gid_car = _int_or_none(frame_df.at[car_idx, 'group_id'])
            if gid_bike is None or gid_car is None:
                continue
            pair_key = (min(gid_bike, gid_car), max(gid_bike, gid_car))
            current = pair_distances.get(pair_key)
            if current is None or distance.distance_px < current['px']:
                pair_distances[pair_key] = {
                    'px': distance.distance_px,
                    'm': distance.distance_m,
                    'cm': distance.distance_cm,
                }

        if not pair_distances:
            return local_updates

        for (gid_small, gid_large), distance in pair_distances.items():
            frame_rows = frame_df[
                frame_df['group_id'].isin([gid_small, gid_large])
            ]
            overtaking = frame_rows[
                (frame_rows['overtake'] == 1) & frame_rows['overtake_by'].notna()
            ]
            if overtaking.empty:
                continue
            for idx in overtaking.index:
                entry = local_updates.setdefault(int(idx), {})
                entry['clearance_distance_px'] = distance['px']
                entry['clearance_distance_m'] = distance['m']
                entry['clearance_distance_cm'] = distance['cm']

        return local_updates

    grouped = vehicles.groupby('frame_num')
    tasks = list(grouped)

    task_count = len(tasks)
    if task_count == 0:
        print(f"Run ID {run_id}: 接近距離を計算するフレームがありません。")
        return

    cpu_workers = max(1, (os.cpu_count() or 1) - 1)
    fallback_workers = min(task_count, cpu_workers)
    worker_count = resolve_worker_count(
        "APPROACH_DISTANCE_WORKERS",
        fallback=fallback_workers,
        max_workers=task_count,
    )
    updates: Dict[int, Dict[str, Optional[float]]] = {}

    if worker_count > 1:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for result in executor.map(process_frame, tasks):
                updates.update(result)
    else:
        for task in tasks:
            updates.update(process_frame(task))

    if not updates:
        print(f"Run ID {run_id}: 接近距離の更新対象がありません。")
        return

    vehicles_updates = []
    for idx, data in updates.items():
        vehicles_updates.append(
            (
                data.get('approach_distance_px'),
                data.get('approach_distance_m'),
                data.get('approach_partner_group_id'),
                data.get('clearance_distance_px'),
                data.get('clearance_distance_m'),
                data.get('clearance_distance_cm'),
                1 if data.get('oncoming_flag') else 0,
                int(vehicles.at[idx, 'auto_id']),
            )
        )

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        conn.executemany(
            """
            UPDATE Detection
            SET approach_distance_px = ?,
                approach_distance_m = ?,
                approach_partner_group_id = ?,
                clearance_distance_px = ?,
                clearance_distance_m = ?,
                clearance_distance_cm = ?,
                oncoming_flag = ?
            WHERE auto_id = ?
            """,
            vehicles_updates,
        )

    print(f"Run ID {run_id}: 接近距離・離隔距離を更新しました（{len(vehicles_updates)}件）。")
