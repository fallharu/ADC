from __future__ import annotations

import glob
import math
import os
import re
import sqlite3
import statistics
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlencode

from .db_manager import MAIN_DB_PATH, configure_connection, resolve_output_root


METRICS = {
    "clearance_m": "離隔距離(m)",
    "approach_m": "接近距離(m)",
    "line_m": "白線距離(m)",
    "car_speed_kmh": "追い越し側速度(km/h)",
    "bike_speed_kmh": "自転車速度(km/h)",
    "car_accel": "追い越し側加速度(m/s2)",
}

_SNAPSHOT_RE = re.compile(r"overtake_(\d+)_car(\d+)_bike(\d+)_\d+\.(?:png|jpg|jpeg)$", re.IGNORECASE)


@dataclass(frozen=True)
class RegressionResult:
    x_metric: str
    y_metric: str
    count: int
    slope: Optional[float]
    intercept: Optional[float]
    r: Optional[float]
    r2: Optional[float]
    photo_url: Optional[str]


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _mean(values: list[float]) -> Optional[float]:
    return float(statistics.fmean(values)) if values else None


def _stdev(values: list[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    return float(statistics.stdev(values))


def _quantiles(values: list[float]) -> tuple[Optional[float], Optional[float]]:
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    qs = statistics.quantiles(sorted(values), n=4, method="inclusive")
    return float(qs[0]), float(qs[2])


def _summary(values: Iterable[Optional[float]]) -> dict[str, Optional[float]]:
    vals = sorted(v for v in (_float_or_none(value) for value in values) if v is not None)
    q1, q3 = _quantiles(vals)
    return {
        "count": len(vals),
        "mean": _mean(vals),
        "median": float(statistics.median(vals)) if vals else None,
        "std": _stdev(vals),
        "min": float(vals[0]) if vals else None,
        "max": float(vals[-1]) if vals else None,
        "q1": q1,
        "q3": q3,
    }


def _histogram(values: list[float], bins: int = 12) -> list[dict[str, float]]:
    vals = [v for v in values if math.isfinite(v)]
    if not vals:
        return []
    lo = min(vals)
    hi = max(vals)
    if math.isclose(lo, hi):
        return [{"start": lo, "end": hi, "count": len(vals)}]
    width = (hi - lo) / bins
    counts = [0] * bins
    for value in vals:
        idx = min(int((value - lo) / width), bins - 1)
        counts[idx] += 1
    return [
        {"start": lo + width * idx, "end": lo + width * (idx + 1), "count": count}
        for idx, count in enumerate(counts)
    ]


def _linear_regression(
    events: list[dict[str, Any]],
    x_metric: str,
    y_metric: str,
) -> RegressionResult:
    pairs: list[tuple[float, float, Optional[str]]] = []
    for event in events:
        x_val = _float_or_none(event.get(x_metric))
        y_val = _float_or_none(event.get(y_metric))
        if x_val is None or y_val is None:
            continue
        pairs.append((x_val, y_val, event.get("photo_url")))

    if len(pairs) < 2:
        return RegressionResult(x_metric, y_metric, len(pairs), None, None, None, None, None)

    xs = [item[0] for item in pairs]
    ys = [item[1] for item in pairs]
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return RegressionResult(x_metric, y_metric, len(pairs), None, None, None, None, pairs[0][2])
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    r = sxy / math.sqrt(sxx * syy)
    r2 = r * r
    return RegressionResult(
        x_metric=x_metric,
        y_metric=y_metric,
        count=len(pairs),
        slope=float(slope),
        intercept=float(intercept),
        r=float(r),
        r2=float(r2),
        photo_url=pairs[0][2],
    )


def _welch_t_test(
    group_a: list[float],
    group_b: list[float],
    label_a: str,
    label_b: str,
) -> Optional[dict[str, Any]]:
    a = [v for v in group_a if math.isfinite(v)]
    b = [v for v in group_b if math.isfinite(v)]
    if len(a) < 2 or len(b) < 2:
        return None

    mean_a = statistics.fmean(a)
    mean_b = statistics.fmean(b)
    var_a = statistics.variance(a)
    var_b = statistics.variance(b)
    denom = math.sqrt((var_a / len(a)) + (var_b / len(b)))
    if denom <= 0:
        return None
    t_stat = (mean_a - mean_b) / denom

    numerator = ((var_a / len(a)) + (var_b / len(b))) ** 2
    denominator = ((var_a / len(a)) ** 2 / (len(a) - 1)) + ((var_b / len(b)) ** 2 / (len(b) - 1))
    df = numerator / denominator if denominator > 0 else None

    approx = True
    try:
        from scipy import stats  # type: ignore

        p_value = float(stats.t.sf(abs(t_stat), df) * 2.0) if df else None
        approx = False
    except Exception:
        p_value = math.erfc(abs(t_stat) / math.sqrt(2.0))

    pooled_sd = math.sqrt(((len(a) - 1) * var_a + (len(b) - 1) * var_b) / (len(a) + len(b) - 2))
    effect = (mean_a - mean_b) / pooled_sd if pooled_sd > 0 else None

    return {
        "group_a": label_a,
        "group_b": label_b,
        "n_a": len(a),
        "n_b": len(b),
        "mean_a": float(mean_a),
        "mean_b": float(mean_b),
        "t_stat": float(t_stat),
        "df": float(df) if df is not None else None,
        "p_value": float(p_value) if p_value is not None else None,
        "p_value_approx": approx,
        "effect_size_d": float(effect) if effect is not None else None,
        "significant": bool(p_value is not None and p_value < 0.05),
    }


def _normalize_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    return [str(v).strip() for v in values if str(v).strip() and str(v).strip() != "all"]


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    except sqlite3.Error:
        return set()


def _first_existing_column(
    conn: sqlite3.Connection,
    table_name: str,
    candidates: tuple[str, ...],
) -> Optional[str]:
    columns = _table_columns(conn, table_name)
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _collect_snapshot_index(output_root: str) -> dict[tuple[int, int, int], list[str]]:
    index: dict[tuple[int, int, int], list[str]] = {}
    patterns = (
        os.path.join(output_root, "**", "overtake_snapshots", "*.png"),
        os.path.join(output_root, "**", "overtake_snapshots", "*.jpg"),
        os.path.join(output_root, "**", "overtake_snapshots", "*.jpeg"),
    )
    abs_root = os.path.abspath(output_root)
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            match = _SNAPSHOT_RE.match(os.path.basename(path))
            if not match:
                continue
            abs_path = os.path.abspath(path)
            if not abs_path.startswith(abs_root):
                continue
            key = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            rel = os.path.relpath(abs_path, abs_root).replace(os.path.sep, "/")
            index.setdefault(key, []).append(rel)
    for values in index.values():
        values.sort()
    return index


def _event_photo_url(event: Mapping[str, Any], snapshot_index: Mapping[tuple[int, int, int], list[str]], output_root: str) -> str:
    params = {
        "run_id": event.get("run_id"),
        "frame": event.get("event_frame_num"),
        "car_group_id": event.get("overtaker_group_id"),
        "bike_group_id": event.get("overtaken_group_id"),
    }
    key = (
        int(event.get("event_frame_num") or 0),
        int(event.get("overtaker_group_id") or 0),
        int(event.get("overtaken_group_id") or 0),
    )
    candidates = list(snapshot_index.get(key, []))
    output_folder = event.get("output_folder")
    if candidates and output_folder:
        abs_output = os.path.abspath(str(output_folder))
        abs_root = os.path.abspath(output_root)
        for candidate in candidates:
            abs_candidate = os.path.abspath(os.path.join(abs_root, candidate))
            if abs_candidate.startswith(abs_output):
                params["image"] = candidate
                break
    if candidates and "image" not in params:
        params["image"] = candidates[0]
    return "/overtake_gallery?" + urlencode({k: v for k, v in params.items() if v is not None})


def get_advanced_analysis_options() -> dict[str, Any]:
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        configure_connection(conn, mode="read")
        years = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT collection_year FROM Video WHERE collection_year IS NOT NULL ORDER BY collection_year"
            ).fetchall()
        ]
        road_types = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT road_type FROM Video WHERE road_type IS NOT NULL AND TRIM(road_type) != '' ORDER BY road_type"
            ).fetchall()
        ]
        auto_count = conn.execute("SELECT COUNT(*) FROM OvertakeEvents").fetchone()[0]
        try:
            manual_count = conn.execute("SELECT COUNT(*) FROM ManualOvertakeEvents").fetchone()[0]
        except sqlite3.OperationalError:
            manual_count = 0

    return {
        "years": years,
        "road_types": road_types,
        "metrics": METRICS,
        "auto_count": auto_count,
        "manual_count": manual_count,
    }


def _load_events(filters: Mapping[str, Any]) -> list[dict[str, Any]]:
    years = _normalize_list(filters.get("years"))
    road_types = _normalize_list(filters.get("road_types"))
    directions = _normalize_list(filters.get("directions"))
    source = str(filters.get("source") or "both")

    events: list[dict[str, Any]] = []
    where = ["1=1"]
    params: list[Any] = []
    if years:
        where.append(f"v.collection_year IN ({','.join('?' for _ in years)})")
        params.extend([int(year) for year in years])
    if road_types:
        where.append(f"v.road_type IN ({','.join('?' for _ in road_types)})")
        params.extend(road_types)
    where_sql = " AND ".join(where)

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        configure_connection(conn, mode="read")

        if source in ("auto", "both"):
            event_id_column = _first_existing_column(
                conn,
                "OvertakeEvents",
                ("overtake_event_id", "event_id"),
            ) or "rowid"
            query = f"""
                SELECT
                    'auto' AS source_type,
                    e.{event_id_column} AS event_id,
                    e.run_id,
                    e.event_frame_num,
                    e.overtaker_group_id,
                    e.overtaken_group_id,
                    v.collection_year,
                    v.road_type,
                    v.filename AS video_filename,
                    p.output_folder,
                    COALESCE(car.travel_direction, bike.travel_direction) AS direction,
                    COALESCE(e.clearance_distance_m, car.clearance_distance_m, bike.clearance_distance_m) AS clearance_m,
                    COALESCE(e.approach_distance_m, car.approach_distance_m, bike.approach_distance_m) AS approach_m,
                    COALESCE(e.line_distance_m, bike.line_distance_m, car.line_distance_m) AS line_m,
                    car.speed_km_h AS car_speed_kmh,
                    bike.speed_km_h AS bike_speed_kmh,
                    car.acceleration_m_s2 AS car_accel,
                    bike.acceleration_m_s2 AS bike_accel
                FROM OvertakeEvents e
                JOIN ProcessLog p ON e.run_id = p.run_id
                JOIN Video v ON p.video_id = v.video_id
                LEFT JOIN Detection car ON e.overtaker_auto_id = car.auto_id
                LEFT JOIN Detection bike ON e.overtaken_auto_id = bike.auto_id
                WHERE {where_sql}
                ORDER BY e.run_id, e.event_frame_num
            """
            events.extend(dict(row) for row in conn.execute(query, params).fetchall())

        if source in ("manual", "both"):
            try:
                manual_query = f"""
                    SELECT
                        'manual' AS source_type,
                        m.manual_event_id AS event_id,
                        m.run_id,
                        m.frame_num AS event_frame_num,
                        m.overtaker_group_id,
                        m.overtaken_group_id,
                        v.collection_year,
                        v.road_type,
                        v.filename AS video_filename,
                        p.output_folder,
                        NULL AS direction,
                        m.clearance_distance_m AS clearance_m,
                        m.approach_distance_m AS approach_m,
                        COALESCE(m.overtaken_line_distance_m, m.overtaker_line_distance_m) AS line_m,
                        m.overtaker_speed_km_h AS car_speed_kmh,
                        m.overtaken_speed_km_h AS bike_speed_kmh,
                        NULL AS car_accel,
                        NULL AS bike_accel
                    FROM ManualOvertakeEvents m
                    JOIN ProcessLog p ON m.run_id = p.run_id
                    JOIN Video v ON p.video_id = v.video_id
                    WHERE {where_sql}
                    ORDER BY m.run_id, m.frame_num
                """
                events.extend(dict(row) for row in conn.execute(manual_query, params).fetchall())
            except sqlite3.OperationalError:
                pass

    if directions:
        allowed = {direction.upper() for direction in directions}
        events = [
            event
            for event in events
            if not str(event.get("direction") or "").strip()
            or str(event.get("direction") or "").upper() in allowed
        ]

    output_root = resolve_output_root()
    snapshot_index = _collect_snapshot_index(output_root)
    for event in events:
        for metric in METRICS:
            event[metric] = _float_or_none(event.get(metric))
        event["photo_url"] = _event_photo_url(event, snapshot_index, output_root)

    return events


def build_advanced_analysis(filters: Mapping[str, Any]) -> dict[str, Any]:
    events = _load_events(filters)

    metric_summaries = {
        metric: _summary(event.get(metric) for event in events)
        for metric in METRICS
    }

    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        road = event.get("road_type") or "未設定"
        year = event.get("collection_year") or "未設定"
        key = f"{road}_{year}"
        entry = grouped.setdefault(
            key,
            {
                "key": key,
                "road_type": road,
                "collection_year": year,
                "count": 0,
                "photo_url": event.get("photo_url"),
                "metrics": {},
            },
        )
        entry["count"] += 1
        for metric in METRICS:
            entry.setdefault("_values", {}).setdefault(metric, []).append(event.get(metric))

    for entry in grouped.values():
        values_map = entry.pop("_values", {})
        entry["metrics"] = {
            metric: _summary(values_map.get(metric, []))
            for metric in METRICS
        }

    by_road: dict[str, dict[str, list[float]]] = {}
    for event in events:
        road = str(event.get("road_type") or "未設定")
        by_road.setdefault(road, {metric: [] for metric in METRICS})
        for metric in METRICS:
            value = event.get(metric)
            if value is not None:
                by_road[road][metric].append(value)

    tests = []
    road_keys = sorted(by_road)
    if len(road_keys) >= 2:
        label_a, label_b = road_keys[0], road_keys[1]
        for metric in METRICS:
            result = _welch_t_test(by_road[label_a][metric], by_road[label_b][metric], label_a, label_b)
            if result:
                result["metric"] = metric
                result["metric_label"] = METRICS[metric]
                tests.append(result)

    regressions = [
        _linear_regression(events, "car_speed_kmh", "clearance_m"),
        _linear_regression(events, "line_m", "clearance_m"),
        _linear_regression(events, "approach_m", "clearance_m"),
    ]

    histograms = {
        metric: _histogram([event[metric] for event in events if event.get(metric) is not None])
        for metric in ("clearance_m", "line_m", "car_speed_kmh")
    }

    scatter = []
    for event in events:
        x_val = event.get("car_speed_kmh")
        y_val = event.get("clearance_m")
        if x_val is None or y_val is None:
            continue
        scatter.append(
            {
                "x": x_val,
                "y": y_val,
                "road_type": event.get("road_type"),
                "year": event.get("collection_year"),
                "photo_url": event.get("photo_url"),
            }
        )
        if len(scatter) >= 1000:
            break

    event_rows = [
        {
            "source_type": event.get("source_type"),
            "run_id": event.get("run_id"),
            "frame": event.get("event_frame_num"),
            "road_type": event.get("road_type"),
            "collection_year": event.get("collection_year"),
            "clearance_m": event.get("clearance_m"),
            "line_m": event.get("line_m"),
            "car_speed_kmh": event.get("car_speed_kmh"),
            "photo_url": event.get("photo_url"),
        }
        for event in events[:200]
    ]

    return {
        "ok": True,
        "filters": dict(filters),
        "metrics": METRICS,
        "total_events": len(events),
        "metric_summaries": metric_summaries,
        "groups": list(grouped.values()),
        "tests": tests,
        "regressions": [reg.__dict__ for reg in regressions],
        "histograms": histograms,
        "scatter": scatter,
        "events": event_rows,
    }
