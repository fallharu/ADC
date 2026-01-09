"""Utility helpers for selecting canonical measurement points per group.

The system derives several metrics (speed, lane distance, approach distance)
from a single representative point on each vehicle.  Historically the
bottom-right corner of the vehicle bounding box was used; current
requirements mandate that we prioritise the tyre detection closest to the
white lines and fall back to the vehicle corner only when tyre data is not
available.  This module centralises the selection logic so that every
consumer uses the same definition.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


Point = Tuple[float, float]

VERTICAL_TOLERANCE_PX = 5.0


def _as_float(value: object) -> Optional[float]:
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _horizontal_distance_to_line(
    point: Point, line: Optional[Sequence[Sequence[object]]]
) -> float:
    if not line:
        return float("inf")

    px, py = point
    best = float("inf")

    for idx in range(len(line) - 1):
        try:
            x1 = _as_float(line[idx][0])
            y1 = _as_float(line[idx][1])
            x2 = _as_float(line[idx + 1][0])
            y2 = _as_float(line[idx + 1][1])
        except (IndexError, TypeError, ValueError):
            continue

        if None in (x1, y1, x2, y2):
            continue

        y_low = min(y1, y2) - VERTICAL_TOLERANCE_PX
        y_high = max(y1, y2) + VERTICAL_TOLERANCE_PX
        if py < y_low or py > y_high:
            continue

        if y2 == y1:
            # 水平線は除外
            continue

        if x2 == x1:
            x_line = x1
        else:
            slope = (x2 - x1) / (y2 - y1)
            clamped_y = min(max(py, min(y1, y2)), max(y1, y2))
            x_line = x1 + slope * (clamped_y - y1)

        dist = abs(px - x_line)
        if dist < best:
            best = dist

    return best


def _euclid_distance_to_line(point: Point, line: Optional[Sequence[Sequence[object]]]) -> float:
    if not line:
        return float("inf")

    px, py = point
    best = float("inf")

    for idx in range(len(line) - 1):
        try:
            x1 = _as_float(line[idx][0])
            y1 = _as_float(line[idx][1])
            x2 = _as_float(line[idx + 1][0])
            y2 = _as_float(line[idx + 1][1])
        except (IndexError, TypeError, ValueError):
            continue

        if None in (x1, y1, x2, y2):
            continue

        dx = x2 - x1
        dy = y2 - y1
        denom = dx * dx + dy * dy
        if denom <= 0:
            dist = np.hypot(px - x1, py - y1)
        else:
            t = ((px - x1) * dx + (py - y1) * dy) / denom
            t = max(0.0, min(1.0, t))
            proj_x = x1 + t * dx
            proj_y = y1 + t * dy
            dist = np.hypot(px - proj_x, py - proj_y)
        if dist < best:
            best = dist

    return best


def _distance_to_white_lines(
    point: Point,
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
) -> float:
    horiz_left = _horizontal_distance_to_line(point, left_line)
    horiz_right = _horizontal_distance_to_line(point, right_line)
    best = min(horiz_left, horiz_right)

    if np.isfinite(best):
        return best

    euclid_left = _euclid_distance_to_line(point, left_line)
    euclid_right = _euclid_distance_to_line(point, right_line)
    return min(euclid_left, euclid_right)


def compute_front_right_tire_points(
    df_tires: pd.DataFrame,
    left_line: Optional[Sequence[Sequence[object]]] = None,
    right_line: Optional[Sequence[Sequence[object]]] = None,
) -> pd.DataFrame:
    """Return the canonical measurement point per (frame, group).

    Parameters
    ----------
    df_tires:
        DataFrame containing tyre detections.  The frame number, group ID and
        bounding box coordinates ``x2``/``y2`` must be present.

    Returns
    -------
    pandas.DataFrame
        Columns: ``frame_num``, ``group_id``, ``measure_x``, ``measure_y``.
        Each row corresponds to the tyre corner that is closest to either
        white line within the frame/group combination.  If no valid tyre data
        exists the returned DataFrame will be empty.
    """

    required_cols: Iterable[str] = ("frame_num", "group_id", "x1", "x2", "y2")
    missing = [col for col in required_cols if col not in df_tires.columns]
    if missing:
        raise KeyError(f"Tyre DataFrame is missing required columns: {missing}")

    if df_tires.empty:
        return df_tires.iloc[0:0][["frame_num", "group_id"]].assign(
            measure_x=pd.Series(dtype=float),
            measure_y=pd.Series(dtype=float),
        )

    tyres = df_tires.copy()

    # 正規化: 数値化できない値を除外
    tyres["frame_num"] = tyres["frame_num"].apply(_as_float)
    tyres["group_id"] = tyres["group_id"].apply(_as_float)
    tyres["x1"] = tyres["x1"].apply(_as_float)
    tyres["x2"] = tyres["x2"].apply(_as_float)
    tyres["y2"] = tyres["y2"].apply(_as_float)

    tyres = tyres.dropna(subset=["frame_num", "group_id", "x2", "y2"])
    if tyres.empty:
        return tyres.iloc[0:0][["frame_num", "group_id"]].assign(
            measure_x=pd.Series(dtype=float),
            measure_y=pd.Series(dtype=float),
        )

    selections: dict[tuple[float, float], tuple[float, float, float, float]] = {}

    for row in tyres.itertuples():
        frame = float(row.frame_num)
        group = float(row.group_id)
        key = (frame, group)

        # 進行方向を取得 (ない場合はNone)
        direction = getattr(row, "travel_direction", None)
        if hasattr(direction, "strip"):
            direction = direction.strip()

        y2_val = _as_float(row.y2)
        if y2_val is None:
            continue

        best_x = None
        best_y = None
        best_rank_val = float("inf") # 小さいほど良い

        # B (Top-to-Bottom) => 車の右側 => 右タイヤ => x2
        # F (Bottom-to-Top) => 車の左側 => 左タイヤ => x1
        
        target_side = None
        if direction == "B":
            target_side = "right" # x2
        elif direction == "F":
            target_side = "left"  # x1

        candidates: list[tuple[float, float, float]] = [] # (metric, x, y)
        
        # タイヤの両端 (x1, x2) を候補にするか、ターゲット側だけにするか
        # 既存ロジックは両端から「白線に近い方」を選んでいたが、
        # 要件は「白線に近い方」ではなく「車の右側/左側」を指定している。
        # 車の右側にあるタイヤの座標は x2, 左側は x1 と仮定できる。
        
        check_x_list = []
        if target_side == "right":
             check_x_list = [row.x2]
        elif target_side == "left":
             check_x_list = [row.x1]
        else:
             # 方向不明の場合は両方見て白線に近い方（既存ロジック）
             check_x_list = [row.x1, row.x2]

        for raw_x in check_x_list:
            x_val = _as_float(raw_x)
            if x_val is None:
                continue
            
            # 評価値の計算
            if target_side:
                # 方向指定がある場合
                # 複数のタイヤが見つかった場合（例えば前輪と後輪）、
                # 右側(B)なら、より右にあるもの(xが大きい)を優先したい?
                # 左側(F)なら、より左にあるもの(xが小さい)を優先したい?
                # 一旦、タイヤごとの座標採用は決まったので、
                # ここでは「そのタイヤの採用座標」が決まる。
                # タイヤ間の競合（前後輪）は後段の selections で解決される。
                
                # metricは selections の比較に使われる
                if target_side == "right":
                    # 右側優先: xが大きいほうが優先 (rankは小さいほうが勝ちなので -x)
                    metric = -x_val
                else: 
                     # 左側優先: xが小さいほうが優先
                    metric = x_val
            else:
                 # 既存: 白線距離
                 metric = _distance_to_white_lines((x_val, y2_val), left_line, right_line)
            
            candidates.append((metric, x_val, y2_val))

        if candidates:
            # 最も良い候補を選択
            # metricが小さい順
            best_cand = min(candidates, key=lambda item: item[0])
            best_rank_val = best_cand[0]
            best_x = best_cand[1]
            best_y = best_cand[2]
        else:
            # 候補なし (x1, x2ともに無効など)
            continue

        if best_x is None or best_y is None:
            continue

        current = selections.get(key)
        # selectionの比較:
        # rank (metric) が小さい方を採用
        # 同着なら y (下にある方=手前?) を優先 (既存実装: -y, -x で比較していた)
        # ここではシンプルに metric で比較する
        
        # 既存実装の rank のタプル構造:
        # (distance, -y, -x) => 距離最小、y最大、x最大
        
        candidate_full_rank = (
            best_rank_val,
            -(best_y if np.isfinite(best_y) else float("-inf")),
            -(best_x if np.isfinite(best_x) else float("-inf")),
        )
        
        if current is None or candidate_full_rank < current[2:]:
            selections[key] = (best_x, best_y, *candidate_full_rank)

    if not selections:
        return tyres.iloc[0:0][["frame_num", "group_id"]].assign(
            measure_x=pd.Series(dtype=float),
            measure_y=pd.Series(dtype=float),
        )

    records = [
        {
            "frame_num": key[0],
            "group_id": key[1],
            "measure_x": values[0],
            "measure_y": values[1],
        }
        for key, values in selections.items()
    ]

    result = pd.DataFrame.from_records(records)
    return result.astype(
        {
            "frame_num": float,
            "group_id": float,
            "measure_x": float,
            "measure_y": float,
        }
    )


def _fallback_measure_point(
    row: pd.Series,
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
) -> tuple[Optional[float], Optional[float]]:
    """BBOX から、進行方向に応じた測定点（進行方向左側または右側）を推定する。
    
    travel_direction:
      - 'B' (Top-to-Bottom, Downward): 右側通行の対向車線(奥から手前)想定 -> 右側(x2)
      - 'F' (Bottom-to-Top, Upward): 左側通行(手前から奥)想定 -> 左側(x1)
      
      ※要件: 「上から下の場合車（右側の車のタイヤ）は右側、下から上の場合は（左側車のタイヤ）は左側」
    """

    if not left_line and not right_line:
        return None, None

    y_candidates: Iterable[object] = (
        row.get("measure_y"),
        row.get("manual_measure_y"),
        row.get("y2"),
    )
    y_val = next((val for val in map(_as_float, y_candidates) if val is not None), None)
    if y_val is None:
        return None, None

    # 進行方向を取得
    direction = getattr(row, "travel_direction", None)
    if not isinstance(direction, str):
        # Seriesから取る場合、getattrで取れるか？ 
        # rowはpd.Seriesなので row.get("travel_direction")
        direction = row.get("travel_direction")
    
    if hasattr(direction, "strip"):
        direction = direction.strip()

    target_side = None
    if direction == "B":
        target_side = "right" # x2
    elif direction == "F":
        target_side = "left"  # x1

    best: Optional[tuple[float, float]] = None
    
    # チェックする座標リスト
    check_keys = []
    if target_side == "right":
        check_keys = ["x2"]
    elif target_side == "left":
        check_keys = ["x1"]
    else:
        # 方向不明なら従来通り両方チェック
        check_keys = ["x1", "x2"]

    for key in check_keys:
        x_val = _as_float(row.get(key))
        if x_val is None:
            continue
        
        # 評価値 (rank)
        if target_side == "right":
             # 右側優先: xが大きいほうが優先 (rankは小さいほうが勝ちなので -x)
             # fallbackの場合、候補は1つ(x2)しかないが、一貫性のため
             rank_metric = -x_val
        elif target_side == "left":
             # 左側優先: xが小さいほうが優先
             rank_metric = x_val
        else:
             # 従来: 白線距離
             rank_metric = _distance_to_white_lines((x_val, y_val), left_line, right_line)

        rank = (
            rank_metric,
            -(y_val if np.isfinite(y_val) else float("-inf")),
            -(x_val if np.isfinite(x_val) else float("-inf")),
        )
        if best is None or rank < best[0]:
            best = (rank, x_val)

    if best is None:
        return None, None

    return best[1], y_val


def attach_measure_points(
    df: pd.DataFrame,
    measure_points: pd.DataFrame,
    left_line: Optional[Sequence[Sequence[object]]] = None,
    right_line: Optional[Sequence[Sequence[object]]] = None,
) -> pd.DataFrame:
    """Attach measurement points to a vehicle DataFrame.

    Parameters
    ----------
    df:
        Vehicle DataFrame containing ``frame_num``, ``group_id``, ``x2`` and
        ``y2`` columns that will be used as fallbacks when tyre data is not
        available.
    measure_points:
        Output of :func:`compute_front_right_tire_points`.

    Returns
    -------
    pandas.DataFrame
        The original DataFrame with two new columns: ``measure_x`` and
        ``measure_y``.
    """

    if df.empty:
        df = df.copy()
        df["measure_x"] = np.nan
        df["measure_y"] = np.nan
        return df

    if not {"frame_num", "group_id", "x2", "y2"}.issubset(df.columns):
        missing = {"frame_num", "group_id", "x2", "y2"} - set(df.columns)
        raise KeyError(f"Vehicle DataFrame is missing required columns: {missing}")

    merged = df.merge(
        measure_points,
        on=["frame_num", "group_id"],
        how="left",
    )

    if left_line or right_line:
        missing_mask = merged["measure_x"].isna() | merged["measure_y"].isna()
        if missing_mask.any():
            fallback_rows = merged.loc[missing_mask].copy()
            fallback_values = fallback_rows.apply(
                _fallback_measure_point,
                axis=1,
                left_line=left_line,
                right_line=right_line,
                result_type="expand",
            )
            if isinstance(fallback_values, pd.DataFrame):
                fallback_values.columns = ["fallback_x", "fallback_y"]
                merged.loc[missing_mask, "measure_x"] = merged.loc[missing_mask, "measure_x"].combine_first(
                    fallback_values["fallback_x"]
                )
                merged.loc[missing_mask, "measure_y"] = merged.loc[missing_mask, "measure_y"].combine_first(
                    fallback_values["fallback_y"]
                )

    merged["measure_x"] = merged["measure_x"].combine_first(merged["x2"])
    merged["measure_y"] = merged["measure_y"].combine_first(merged["y2"])

    return merged

