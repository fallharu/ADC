"""CVAT アノテーション(XML)を入力として速度・離隔距離を算出する。

YOLO を実行せず、CVAT for video 1.1 形式の BBOX をそのまま使う。
計算はプロジェクト既存ロジックを再利用する:
  速度       Source_code/modules/speed_y_axis (縦スケール) / speed_homography (射影)
  白線距離   Source_code/modules/manual_metrics
  測定点     Source_code/modules/measure_points._fallback_measure_point

離隔距離は 2 通り記録する:
  clearance_y_axis_m  : y軸判定（縦スケール + 車線幅スケール、既存 approach_distance と同じ式）
  clearance_bev_m     : 射影変換後に y 軸を反転した俯瞰座標でのユークリッド距離

使い方:
    python scripts/analyze_cvat_annotations.py <annotations.xml> <video.mp4> \
        <calibration_profile> <出力ディレクトリ> [--no-video] [--no-bev]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from Source_code.modules.manual_metrics import (  # noqa: E402
    LANE_WIDTH_METERS,
    compute_lane_distance,
    lane_scale_at_point,
    load_white_lines,
)
from Source_code.modules.speed_homography import apply_homography_speed  # noqa: E402
from Source_code.modules.speed_y_axis import (  # noqa: E402
    apply_vertical_speed,
    prepare_vertical_context,
)

BIKE_LABELS = {"bicycle", "bike", "cyclist"}
CAR_LABELS = {"car", "automobile", "vehicle", "truck", "bus", "van", "motorcycle"}
SMOOTH_WINDOW = 11
MODE_WINDOW = 10

BEV_HEIGHT = 190          # 俯瞰ストリップの高さ [px]
BEV_MARGIN_X = 40         # 左右余白 [px]


# --------------------------------------------------------------------------
# CVAT XML パース
# --------------------------------------------------------------------------
def parse_cvat_xml(path: str):
    root = ET.parse(path).getroot()

    # タスク単位(meta/task)とジョブ単位(meta/job)の両方のエクスポートに対応する。
    node = root.find("meta/task")
    kind = "task"
    if node is None:
        node = root.find("meta/job")
        kind = "job"

    def _text(rel):
        return node.findtext(rel) if node is not None else None

    width = _text("original_size/width") or root.findtext("meta/original_size/width")
    height = _text("original_size/height") or root.findtext("meta/original_size/height")
    size = _text("size")
    meta = {
        "kind": kind,
        "task_id": _text("id"),
        "task_name": _text("name"),
        "source": _text("source"),
        "size": int(size) if size else None,
        "width": int(width) if width else None,
        "height": int(height) if height else None,
        "dumped": root.findtext("meta/dumped"),
    }

    rows: List[dict] = []
    for track in root.findall("track"):
        track_id = int(track.get("id"))
        label = (track.get("label") or "").strip()
        boxes = [b for b in track.findall("box") if b.get("outside") != "1"]
        if not boxes:
            continue
        keyframes = [int(b.get("frame")) for b in boxes if b.get("keyframe") == "1"]
        last_kf = max(keyframes) if keyframes else None

        # 最終キーフレーム以降で座標が変化しない区間は CVAT の保持挙動であり実データではない
        last_box = None
        for b in boxes:
            frame = int(b.get("frame"))
            coords = (
                float(b.get("xtl")), float(b.get("ytl")),
                float(b.get("xbr")), float(b.get("ybr")),
            )
            held = bool(
                last_kf is not None
                and frame > last_kf
                and last_box is not None
                and all(abs(a - c) < 1e-6 for a, c in zip(coords, last_box))
            )
            rows.append({
                "track_id": track_id,
                "label": label,
                "frame_num": frame,
                "x1": coords[0], "y1": coords[1], "x2": coords[2], "y2": coords[3],
                "is_keyframe": int(b.get("keyframe") == "1"),
                "occluded": int(b.get("occluded") or 0),
                "is_held": int(held),
            })
            last_box = coords

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["track_id", "frame_num"]).reset_index(drop=True)
    return df, meta


# --------------------------------------------------------------------------
# 射影変換（俯瞰座標）
# --------------------------------------------------------------------------
class Projection:
    """image -> world(u,v) [m] の射影。u は横断方向、v は進行方向。

    画像の y は奥ほど小さいのに対し v は奥ほど大きい。つまり射影結果は
    y 軸が反転した座標系にある。この反転は進行方向の判定にも効くので、
    compute_speed 側で travel_direction の符号を揃えている。
    """

    def __init__(self, homography_meta: dict):
        pts = homography_meta.get("image_points") or []
        self.width_m = float(homography_meta.get("width_m") or 0)
        self.length_m = float(homography_meta.get("length_m") or 0)
        self.interval_m = float(homography_meta.get("interval_m") or 5.0)
        self.ok = len(pts) == 4 and self.width_m > 0 and self.length_m > 0
        self.H = None
        if self.ok:
            src = np.array(pts, dtype=np.float32)
            dst = np.array(
                [[0, 0], [self.width_m, 0], [self.width_m, self.length_m], [0, self.length_m]],
                dtype=np.float32,
            )
            self.H, _ = cv2.findHomography(src, dst, 0)
            self.ok = self.H is not None
        self.image_points = np.array(pts, dtype=np.float32) if pts else None

    def to_world(self, x, y):
        """画像座標 -> (u, v)。

        u は横断方向 [0, width_m]、v は進行方向 [0, length_m] で
        手前（区間起点）が 0、奥ほど大きい。画像の y は奥ほど小さいので、
        この v は y 軸を反転した座標系にあたる。
        """
        pts = np.stack([np.asarray(x, float), np.asarray(y, float),
                        np.ones(np.size(x), float)], axis=-1)
        m = pts @ self.H.T
        w = m[..., 2]
        u = np.where(w != 0, m[..., 0] / w, np.nan)
        v = np.where(w != 0, m[..., 1] / w, np.nan)
        return u, v

    def rungs(self) -> List[List[List[float]]]:
        """interval_m ごとの横断線を画像座標で返す。"""
        Hi = np.linalg.inv(self.H)
        out = []
        v = 0.0
        while v <= self.length_m + 1e-6:
            seg = []
            for u in (0.0, self.width_m):
                p = np.array([u, v, 1.0]) @ Hi.T
                seg.append([float(p[0] / p[2]), float(p[1] / p[2])])
            out.append(seg)
            v += self.interval_m
        return out


# --------------------------------------------------------------------------
# 速度
# --------------------------------------------------------------------------
def compute_speed(df: pd.DataFrame, scale_meta: dict, fps: float,
                  invert_direction: bool = False,
                  point_x: Optional[str] = None) -> pd.DataFrame:
    """アプリ(assign_kinematics)と同じ手順で速度を求める。

    point_x に列名を渡すと、射影速度の測定点の x をその列にする（省略時は BBOX 中央）。
    """
    work = df.copy()
    work["center_x"] = work[point_x] if point_x else (work["x1"] + work["x2"]) / 2.0
    work["center_y"] = (work["y1"] + work["y2"]) / 2.0

    for col in ("center_x", "center_y"):
        work["smooth_" + col] = work.groupby("track_id")[col].transform(
            lambda s: s.rolling(SMOOTH_WINDOW, center=True, min_periods=1).mean()
        )
    work["smooth_y2"] = work.groupby("track_id")["y2"].transform(
        lambda s: s.rolling(SMOOTH_WINDOW, center=True, min_periods=1).mean()
    )

    work["frame_diff"] = work.groupby("track_id")["frame_num"].diff()
    work["speed_mps"] = 0.0
    work["speed_km_h"] = 0.0
    work["acceleration_m_s2"] = 0.0
    work["travel_direction"] = "N"
    work["scale_pixels_per_meter"] = np.nan
    work["y_delta"] = np.nan

    time_s = work["frame_diff"] / fps
    frame_window = max(int(round(fps)), 1)
    mode = str(scale_meta.get("mode") or "vertical").lower()

    context = prepare_vertical_context(work, scale_meta)
    applied = False
    if mode == "homography":
        applied = apply_homography_speed(
            work, time_s, fps, frame_window, scale_meta.get("homography") or {}, context
        )
        if applied and invert_direction:
            # 射影後の world_y は画像 y と向きが逆（手前が 0、奥が length_m）。
            # apply_homography_speed はこれをそのまま使うため、縦スケール方式
            # （y が減る = 奥へ = "F"）と進行方向の符号が逆になる。
            # --invert-direction 指定時のみ y 軸を反転して縦方式と揃える。
            work["travel_direction_raw"] = work["travel_direction"]
            work["travel_direction"] = np.where(
                work["world_dy"].fillna(0) > 0, "F", "B"
            )
    if not applied:
        applied = apply_vertical_speed(work, time_s, fps, frame_window, context)
    if not applied:
        work["scale_unavailable"] = 1
        return work
    work["scale_unavailable"] = 0

    def _mode_value(window: pd.Series) -> float:
        valid = window.dropna()
        if valid.empty:
            return float("nan")
        rounded = valid.round(2)
        counts = rounded.value_counts()
        if counts.empty:
            return float("nan")
        top = counts.idxmax()
        return float(valid[rounded == top].mean())

    smoothed = work.groupby("track_id")["speed_mps"].transform(
        lambda s: s.rolling(MODE_WINDOW, min_periods=1).apply(_mode_value, raw=False)
    )
    work["speed_mps"] = smoothed.fillna(work["speed_mps"])
    work["speed_km_h"] = work["speed_mps"] * 3.6
    work["speed_diff"] = work.groupby("track_id")["speed_mps"].diff(periods=frame_window)
    work["time_diff_accel"] = (
        work.groupby("track_id")["frame_num"].diff(periods=frame_window) / fps
    )
    valid = work["time_diff_accel"] > 0
    work.loc[valid, "acceleration_m_s2"] = (
        work["speed_diff"][valid] / work["time_diff_accel"][valid]
    )
    return work


# --------------------------------------------------------------------------
# 測定点 / 白線距離 / 離隔距離
# --------------------------------------------------------------------------
def attach_measure_points(df: pd.DataFrame, lines) -> pd.DataFrame:
    """測定点を固定する。

    自転車 : BBOX 下辺の中央 ((x1+x2)/2, y2)
    車     : BBOX 右下        (x2, y2)

    プロジェクトの _fallback_measure_point は車の左右を travel_direction で
    切り替えるが、射影モードでは world_y の向きの影響で判定が反転する。
    ここでは進行方向に依存しない固定の測定点を使う。
    """
    work = df.copy()
    is_bike = work["label"].str.lower().isin(BIKE_LABELS)
    work["measure_x"] = np.where(is_bike, (work["x1"] + work["x2"]) / 2.0, work["x2"])
    work["measure_y"] = work["y2"]
    return work


def compute_lane_columns(df: pd.DataFrame, lines, lane_width_m: float) -> pd.DataFrame:
    out: List[dict] = []
    for row in df.itertuples():
        det = {
            "x1": row.x1, "y1": row.y1, "x2": row.x2, "y2": row.y2,
            "measure_x": row.measure_x, "measure_y": row.measure_y,
        }
        res = compute_lane_distance(
            det, lines.left, lines.right, lines.center,
            lines.left_inner, lines.right_inner,
            lane_width_m=lane_width_m,
        )
        out.append({
            "measure_x": res.measure_x,
            "measure_y": res.measure_y,
            "l_line_distance_m": res.left_distance_m,
            "r_line_distance_m": res.right_distance_m,
            "line_distance_m": res.distance_m,
            "lane_inner": int(bool(res.is_inner)),
        })
    base = df.reset_index(drop=True).drop(columns=["measure_x", "measure_y"], errors="ignore")
    return pd.concat([base, pd.DataFrame(out)], axis=1)


def attach_world_columns(df: pd.DataFrame, proj: Optional[Projection]) -> pd.DataFrame:
    work = df.copy()
    work["bev_u_m"] = np.nan
    work["bev_v_m"] = np.nan
    if proj is not None and proj.ok:
        u, v = proj.to_world(work["measure_x"].values, work["measure_y"].values)
        work["bev_u_m"] = u
        work["bev_v_m"] = v
    return work


def compute_clearance(df: pd.DataFrame, lines, lane_width_m: float,
                      proj: Optional[Projection]) -> pd.DataFrame:
    """同一フレーム内の自転車×車について離隔距離を 2 方式で算出する。"""
    label_lower = df["label"].str.lower()
    if not label_lower.isin(BIKE_LABELS).any() or not label_lower.isin(CAR_LABELS).any():
        return pd.DataFrame()

    rows: List[dict] = []
    for frame, frame_df in df.groupby("frame_num"):
        low = frame_df["label"].str.lower()
        fb = frame_df[low.isin(BIKE_LABELS)]
        fc = frame_df[low.isin(CAR_LABELS)]
        if fb.empty or fc.empty:
            continue
        for b in fb.itertuples():
            for c in fc.itertuples():
                pts = [b.measure_x, b.measure_y, c.measure_x, c.measure_y]
                if any(p is None for p in pts) or not all(np.isfinite(pts)):
                    continue
                dx_px = float(b.measure_x) - float(c.measure_x)
                dy_px = float(b.measure_y) - float(c.measure_y)
                distance_px = float(math.hypot(dx_px, dy_px))

                # --- (1) y軸判定: 既存 approach_distance と同じ式 ---
                x_scales = []
                for r in (b, c):
                    s = lane_scale_at_point(
                        r.measure_x, r.measure_y, lines.left, lines.right,
                        lines.center, lines.left_inner, lines.right_inner,
                        lane_width_m=lane_width_m,
                    )
                    if s and s > 0:
                        x_scales.append(float(s))
                y_scales = [
                    v for v in (getattr(b, "scale_pixels_per_meter", None),
                                getattr(c, "scale_pixels_per_meter", None))
                    if v is not None and np.isfinite(v) and v > 0
                ]
                avg_x = float(np.mean(x_scales)) if x_scales else None
                avg_y = float(np.mean(y_scales)) if y_scales else None
                d_yaxis = None
                if avg_x and avg_y:
                    d_yaxis = float(math.hypot(abs(dx_px) / avg_x, abs(dy_px) / avg_y))
                elif avg_x:
                    d_yaxis = abs(dx_px) / avg_x
                elif avg_y:
                    d_yaxis = abs(dy_px) / avg_y

                # --- (2) 射影計算 + y軸反転の俯瞰座標 ---
                d_bev = d_lat = d_lon = None
                bu = getattr(b, "bev_u_m", np.nan)
                bv = getattr(b, "bev_v_m", np.nan)
                cu = getattr(c, "bev_u_m", np.nan)
                cv_ = getattr(c, "bev_v_m", np.nan)
                if all(np.isfinite([bu, bv, cu, cv_])):
                    d_lat = abs(float(bu) - float(cu))
                    d_lon = abs(float(bv) - float(cv_))
                    d_bev = float(math.hypot(d_lat, d_lon))

                rows.append({
                    "frame_num": frame,
                    "bike_track_id": b.track_id,
                    "car_track_id": c.track_id,
                    "clearance_distance_px": round(distance_px, 2),
                    "clearance_y_axis_m": round(d_yaxis, 3) if d_yaxis else None,
                    "clearance_y_axis_cm": round(d_yaxis * 100, 1) if d_yaxis else None,
                    "clearance_bev_m": round(d_bev, 3) if d_bev else None,
                    "clearance_bev_cm": round(d_bev * 100, 1) if d_bev else None,
                    "bev_lateral_m": round(d_lat, 3) if d_lat is not None else None,
                    "bev_longitudinal_m": round(d_lon, 3) if d_lon is not None else None,
                    "bike_bev_u_m": round(float(bu), 3) if np.isfinite(bu) else None,
                    "bike_bev_v_m": round(float(bv), 3) if np.isfinite(bv) else None,
                    "car_bev_u_m": round(float(cu), 3) if np.isfinite(cu) else None,
                    "car_bev_v_m": round(float(cv_), 3) if np.isfinite(cv_) else None,
                    "bike_speed_km_h": round(float(getattr(b, "speed_km_h", float("nan"))), 2),
                    "car_speed_km_h": round(float(getattr(c, "speed_km_h", float("nan"))), 2),
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 描画
# --------------------------------------------------------------------------
def _draw_calibration(frame, polys, line_style, rungs, interval_m, z0, proj):
    overlay = frame.copy()
    for key, poly in polys.items():
        cv2.polylines(overlay, [poly], False, line_style[key], 2)
    # 測定区間の平行四辺形
    if proj is not None and proj.ok and proj.image_points is not None:
        quad = proj.image_points.astype(np.int32)
        cv2.fillPoly(overlay, [quad], (40, 120, 255))
    cv2.addWeighted(overlay, 0.22, frame, 0.78, 0, frame)
    if proj is not None and proj.ok and proj.image_points is not None:
        cv2.polylines(frame, [proj.image_points.astype(np.int32)], True, (40, 120, 255), 2)
    font = cv2.FONT_HERSHEY_SIMPLEX
    for i, seg in enumerate(rungs):
        p1 = (int(seg[0][0]), int(seg[0][1]))
        p2 = (int(seg[1][0]), int(seg[1][1]))
        cv2.line(frame, p1, p2, (0, 255, 255), 1, cv2.LINE_AA)
        # ラベルは 20m ごと（5m 刻みだと密すぎる）
        if (i * interval_m) % 20 == 0:
            lx = max(4, min(p1[0], 1200))
            cv2.putText(frame, "%dm" % (z0 + i * interval_m), (lx, p1[1] - 3),
                        font, 0.42, (0, 255, 255), 1, cv2.LINE_AA)


def _draw_detections(frame, dets, font):
    for det in dets:
        held = int(det.get("is_held") or 0)
        color = (0, 200, 255) if held else (0, 255, 0)
        p1 = (int(det["x1"]), int(det["y1"]))
        p2 = (int(det["x2"]), int(det["y2"]))
        cv2.rectangle(frame, p1, p2, color, 2)
        mx, my = det.get("measure_x"), det.get("measure_y")
        if mx is not None and np.isfinite(mx):
            cv2.circle(frame, (int(mx), int(my)), 4, (0, 0, 255), -1)

        labels = ["#%d %s" % (int(det["track_id"]), det["label"])]
        spd = det.get("speed_km_h")
        if spd is not None and np.isfinite(spd) and spd > 0:
            labels.append("%.1f km/h" % spd)
        ld, rd = det.get("l_line_distance_m"), det.get("r_line_distance_m")
        if ld is not None and np.isfinite(ld):
            labels.append("L %.2f m" % ld)
        if rd is not None and np.isfinite(rd):
            labels.append("R %.2f m" % rd)
        if held:
            labels.append("HOLD (no keyframe)")

        ty = max(14, p1[1] - 6 - 15 * (len(labels) - 1))
        for line in labels:
            (tw, th), _ = cv2.getTextSize(line, font, 0.5, 1)
            cv2.rectangle(frame, (p1[0], ty - th - 3), (p1[0] + tw + 6, ty + 3), (0, 0, 0), -1)
            cv2.putText(frame, line, (p1[0] + 3, ty), font, 0.5, color, 1, cv2.LINE_AA)
            ty += 15


def _draw_clearance(frame, pairs, point_of, idx, font):
    """離隔線を引き、数値ラベルは自動車側に置く。"""
    for pair in pairs:
        bp = point_of.get((idx, int(pair["bike_track_id"])))
        cp = point_of.get((idx, int(pair["car_track_id"])))
        if not bp or not cp:
            continue
        b = (int(bp[0]), int(bp[1]))
        c = (int(cp[0]), int(cp[1]))
        cv2.line(frame, b, c, (255, 0, 255), 2)

        parts = []
        if pair.get("clearance_bev_m") is not None and np.isfinite(pair["clearance_bev_m"]):
            parts.append("%.2f m" % pair["clearance_bev_m"])
        if pair.get("clearance_y_axis_m") is not None and np.isfinite(pair["clearance_y_axis_m"]):
            parts.append("(y %.2f)" % pair["clearance_y_axis_m"])
        if not parts:
            continue
        txt = " ".join(parts)
        (tw, th), _ = cv2.getTextSize(txt, font, 0.5, 2)
        # 自動車側の測定点に寄せる。画面外に出ないよう調整
        ax = int(np.clip(c[0] - tw // 2, 2, frame.shape[1] - tw - 6))
        ay = int(np.clip(c[1] + th + 12, th + 6, frame.shape[0] - 6))
        cv2.rectangle(frame, (ax - 3, ay - th - 4), (ax + tw + 4, ay + 4), (0, 0, 0), -1)
        cv2.putText(frame, txt, (ax, ay), font, 0.5, (255, 120, 255), 2, cv2.LINE_AA)


def _bev_canvas(frame, proj: Projection, ppm: float, width: int):
    """frame を俯瞰ストリップへワープする。左端が手前(v_inv=0)。"""
    # world(u, v) -> BEV px :  bx = MARGIN + v*ppm (手前が左),  by = u*ppm + off
    off_y = (BEV_HEIGHT - proj.width_m * ppm) / 2.0
    S = np.array([
        [0.0, ppm, BEV_MARGIN_X],
        [ppm, 0.0, off_y],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    M = S @ proj.H
    return cv2.warpPerspective(frame, M, (width, BEV_HEIGHT)), M


def render_videos(
    video_path: str,
    out_main: str,
    out_bev: Optional[str],
    df: pd.DataFrame,
    calib: dict,
    fps: float,
    clearance: pd.DataFrame,
    proj: Optional[Projection],
    z0: float,
) -> None:
    by_frame: Dict[int, List[dict]] = {}
    point_of: Dict[tuple, tuple] = {}
    for row in df.to_dict("records"):
        f = int(row["frame_num"])
        by_frame.setdefault(f, []).append(row)
        point_of[(f, int(row["track_id"]))] = (row.get("measure_x"), row.get("measure_y"))

    # 描画はフレームごと・自転車ごとに最も近い車の 1 組だけ（CSV には全ペアを残す）
    clear_by_frame: Dict[int, List[dict]] = {}
    if clearance is not None and not clearance.empty:
        key = "clearance_bev_m" if clearance["clearance_bev_m"].notna().any() else "clearance_y_axis_m"
        nearest = (clearance.dropna(subset=[key])
                   .sort_values(key)
                   .groupby(["frame_num", "bike_track_id"], as_index=False)
                   .first())
        for row in nearest.to_dict("records"):
            clear_by_frame.setdefault(int(row["frame_num"]), []).append(row)

    lines = calib.get("lines", {}) or {}
    line_style = {
        "left_white_line": (60, 60, 255),
        "right_white_line": (255, 120, 60),
        "center_line": (0, 230, 230),
        "left_mid_line": (80, 200, 80),
        "right_mid_line": (230, 80, 230),
    }
    polys = {k: np.array(v, dtype=np.int32)
             for k, v in lines.items() if k in line_style and len(v) > 1}
    rungs = proj.rungs() if (proj is not None and proj.ok) else []
    interval_m = proj.interval_m if proj is not None else 5.0

    cap = cv2.VideoCapture(video_path)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_main, fourcc, fps, (w, h))

    make_bev = bool(out_bev and proj is not None and proj.ok)
    bev_writer = None
    ppm = 0.0
    if make_bev:
        ppm = (w - 2 * BEV_MARGIN_X) / proj.length_m
        bev_writer = cv2.VideoWriter(out_bev, fourcc, fps, (w, h + BEV_HEIGHT))

    font = cv2.FONT_HERSHEY_SIMPLEX
    # cv2.putText は日本語を描けないので ASCII のみで組み立てる
    if proj is not None and proj.ok:
        footer = ("frame %%d/%%d  t=%%6.2fs   src=CVAT   scale=%.0fm dash homography"
                  "   region %.0fm wide x Z %.0f-%.0fm"
                  % (proj.interval_m, proj.width_m, z0, z0 + proj.length_m))
    else:
        footer = "frame %d/%d  t=%6.2fs   src=CVAT  scale=vertical ladder"
    idx = 0
    while True:
        ok, src = cap.read()
        if not ok:
            break

        bev_img = None
        if make_bev:
            bev_img, M = _bev_canvas(src, proj, ppm, w)

        frame = src
        _draw_calibration(frame, polys, line_style, rungs, interval_m, z0, proj)
        _draw_detections(frame, by_frame.get(idx, []), font)
        _draw_clearance(frame, clear_by_frame.get(idx, []), point_of, idx, font)
        cv2.rectangle(frame, (0, h - 26), (w, h), (0, 0, 0), -1)
        cv2.putText(frame, footer % (idx, total - 1, idx / fps),
                    (8, h - 8), font, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        writer.write(frame)

        if make_bev:
            # 俯瞰側の重畳
            def bev_pt(u, v):
                return (int(BEV_MARGIN_X + ppm * v),
                        int((BEV_HEIGHT - proj.width_m * ppm) / 2.0 + ppm * u))

            # 5m グリッド（ラベルは 20m ごと）
            for k in range(int(proj.length_m / interval_m) + 1):
                v = k * interval_m
                p1 = bev_pt(0, v)
                p2 = bev_pt(proj.width_m, v)
                cv2.line(bev_img, p1, p2, (0, 255, 255), 1)
                if (k * interval_m) % 20 == 0:
                    cv2.putText(bev_img, "%dm" % (z0 + v), (p1[0] - 12, 14),
                                font, 0.38, (0, 255, 255), 1, cv2.LINE_AA)
            for det in by_frame.get(idx, []):
                if int(det.get("is_held") or 0):
                    continue
                u, v = det.get("bev_u_m"), det.get("bev_v_m")
                if u is None or not np.isfinite(u) or not np.isfinite(v):
                    continue
                if not (0 <= u <= proj.width_m and 0 <= v <= proj.length_m):
                    continue
                col = (0, 255, 255) if str(det["label"]).lower() in BIKE_LABELS else (0, 255, 0)
                p = bev_pt(u, v)
                cv2.circle(bev_img, p, 6, col, -1)
                cv2.putText(bev_img, "#%d" % int(det["track_id"]), (p[0] + 8, p[1] - 6),
                            font, 0.45, col, 1, cv2.LINE_AA)
            for pair in clear_by_frame.get(idx, []):
                if pair.get("clearance_bev_m") is None or not np.isfinite(pair["clearance_bev_m"]):
                    continue
                bu, bv = pair.get("bike_bev_u_m"), pair.get("bike_bev_v_m")
                cu, cvv = pair.get("car_bev_u_m"), pair.get("car_bev_v_m")
                if bu is None or cu is None:
                    continue
                if not (0 <= bu <= proj.width_m and 0 <= cu <= proj.width_m):
                    continue
                pb, pc = bev_pt(bu, bv), bev_pt(cu, cvv)
                cv2.line(bev_img, pb, pc, (255, 0, 255), 2)
                txt = "%.2f m" % pair["clearance_bev_m"]
                cv2.putText(bev_img, txt, (pc[0] - 30, pc[1] + 22),
                            font, 0.5, (255, 120, 255), 2, cv2.LINE_AA)
            cv2.putText(bev_img, "BEV uniform %.2f px/m   left = near (%.0fm)  right = far (%.0fm)" % (ppm, z0, z0 + proj.length_m),
                        (8, BEV_HEIGHT - 6), font, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
            bev_writer.write(np.vstack([frame, bev_img]))

        idx += 1
        if idx % 2000 == 0:
            print("      描画 %d/%d" % (idx, total), flush=True)

    cap.release()
    writer.release()
    if bev_writer is not None:
        bev_writer.release()


# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("xml")
    ap.add_argument("video")
    ap.add_argument("profile")
    ap.add_argument("outdir")
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--no-bev", action="store_true")
    ap.add_argument("--invert-direction", action="store_true",
                    help="射影モードで travel_direction の y 軸を反転し縦方式と揃える")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    calib_path = os.path.join("output", "calibrations", args.profile + ".json")
    with open(calib_path, encoding="utf-8") as fh:
        calib = json.load(fh)
    scale_meta = calib.get("scale", {}) or {}
    lines = load_white_lines(calib)
    lane_width_m = float(calib.get("lane_width_m") or LANE_WIDTH_METERS)

    proj = None
    z0 = 0.0
    if (scale_meta.get("mode") or "").lower() == "homography":
        proj = Projection(scale_meta.get("homography") or {})
        z0 = float((calib.get("ground_plane", {}) or {}).get("region", {}).get("z0", 0.0))

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    vframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    print("[入力] 動画 %dx%d %.3ffps %dフレーム" % (vw, vh, fps, vframes), flush=True)
    print("[入力] キャリブレーション %s (mode=%s)"
          % (args.profile, scale_meta.get("mode")), flush=True)
    if proj is not None and proj.ok:
        print("       測定区間 幅%.1fm x 長さ%.1fm, 横断線間隔 %.1fm, 起点 Z=%.0fm"
              % (proj.width_m, proj.length_m, proj.interval_m, z0), flush=True)

    df, meta = parse_cvat_xml(args.xml)
    print("[入力] CVAT %s=%s '%s' source=%s %sx%s %sフレーム"
          % (meta["kind"], meta["task_id"], meta["task_name"], meta["source"],
             meta["width"], meta["height"], meta["size"]), flush=True)
    if df.empty:
        raise SystemExit("アノテーションに有効な BBOX がありません。")
    real = df[df["is_held"] == 0]
    print("[入力] track %d 本 / box %d 個 (実データ %d 個, CVAT保持 %d 個)"
          % (df["track_id"].nunique(), len(df), len(real), len(df) - len(real)), flush=True)
    print("[入力] ラベル内訳: %s"
          % df.groupby("label")["track_id"].nunique().to_dict(), flush=True)

    if meta["width"] and meta["width"] != vw:
        s = vw / meta["width"]
        print("[調整] アノテーション解像度 %dx%d を %dx%d へ %.6f 倍でスケールします。"
              % (meta["width"], meta["height"], vw, vh, s), flush=True)
        for c in ("x1", "y1", "x2", "y2"):
            df[c] = df[c] * s

    print("[1/5] 速度を算出します…", flush=True)
    df = compute_speed(df, scale_meta, fps, invert_direction=args.invert_direction)
    live = (df["is_held"] == 0).values
    n_live = int(live.sum())
    print("      速度が得られた実データ box: %d/%d"
          % (int((df.loc[live, "speed_km_h"] > 0).sum()), n_live), flush=True)

    print("[2/5] 測定点と白線距離を算出します…", flush=True)
    df = attach_measure_points(df, lines)
    df = compute_lane_columns(df, lines, lane_width_m)

    print("[3/5] 射影変換で俯瞰座標を求めます…", flush=True)
    df = attach_world_columns(df, proj)
    if proj is not None and proj.ok:
        inside = df.loc[live, "bev_u_m"].between(0, proj.width_m) & \
            df.loc[live, "bev_v_m"].between(0, proj.length_m)
        print("      測定区間内の実データ box: %d/%d" % (int(inside.sum()), n_live), flush=True)

    print("[4/5] 離隔距離を算出します（y軸判定 / 射影+y反転）…", flush=True)
    clearance = compute_clearance(df[df["is_held"] == 0], lines, lane_width_m, proj)
    if clearance.empty:
        print("      自転車と車が同一フレームに存在しないため 0 件です。", flush=True)

    detail_cols = [
        "frame_num", "track_id", "label", "is_keyframe", "is_held", "occluded",
        "x1", "y1", "x2", "y2", "measure_x", "measure_y",
        "scale_pixels_per_meter", "speed_km_h",
        "acceleration_m_s2", "travel_direction", "travel_direction_raw",
        "bev_u_m", "bev_v_m",
        "l_line_distance_m", "r_line_distance_m", "line_distance_m", "lane_inner",
    ]
    detail = df[[c for c in detail_cols if c in df.columns]].copy()
    detail.insert(1, "time_s", (detail["frame_num"] / fps).round(3))
    for c in detail.columns:
        if detail[c].dtype.kind == "f":
            detail[c] = detail[c].round(3)
    detail_path = os.path.join(args.outdir, "detections_speed_clearance.csv")
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    print("      %s (%d 行)" % (detail_path, len(detail)), flush=True)

    valid = df[df["is_held"] == 0]
    summary = valid.groupby(["track_id", "label"]).agg(
        first_frame=("frame_num", "min"),
        last_frame=("frame_num", "max"),
        boxes=("frame_num", "count"),
        keyframes=("is_keyframe", "sum"),
        min_l_line_distance_m=("l_line_distance_m", "min"),
        min_r_line_distance_m=("r_line_distance_m", "min"),
    ).reset_index()

    def _speed_stats(col: str, suffix: str) -> pd.DataFrame:
        sub = valid[valid[col] > 0]
        if sub.empty:
            return pd.DataFrame(columns=["track_id"])
        return sub.groupby("track_id").agg(**{
            "mean_speed_km_h" + suffix: (col, "mean"),
            "median_speed_km_h" + suffix: (col, "median"),
            "max_speed_km_h" + suffix: (col, "max"),
            "speed_samples" + suffix: (col, "count"),
        }).reset_index()

    stats = _speed_stats("speed_km_h", "")
    if not stats.empty:
        summary = summary.merge(stats, on="track_id", how="left")

    summary["first_time_s"] = (summary["first_frame"] / fps).round(2)
    summary["last_time_s"] = (summary["last_frame"] / fps).round(2)
    summary["duration_s"] = ((summary["last_frame"] - summary["first_frame"]) / fps).round(2)
    for c in summary.columns:
        if summary[c].dtype.kind == "f":
            summary[c] = summary[c].round(3)
    summary_path = os.path.join(args.outdir, "track_summary.csv")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print("      %s (%d 行)" % (summary_path, len(summary)), flush=True)

    clearance_path = os.path.join(args.outdir, "clearance_pairs.csv")
    clearance.to_csv(clearance_path, index=False, encoding="utf-8-sig")
    print("      %s (%d 行)" % (clearance_path, len(clearance)), flush=True)

    if not args.no_video:
        print("[5/5] 動画を描画します…", flush=True)
        main_out = os.path.join(args.outdir, "annotated_cvat.mp4")
        bev_out = None if args.no_bev else os.path.join(args.outdir, "annotated_bev.mp4")
        render_videos(args.video, main_out, bev_out, df, calib, fps, clearance, proj, z0)
        print("      %s" % main_out, flush=True)
        if bev_out:
            print("      %s" % bev_out, flush=True)

    print("DONE")


if __name__ == "__main__":
    main()
