"""CVAT アノテーション(XML)から 速度・離隔距離・追い越しタイミング の CSV を作る。

動画は読まない（FPS は引数で与える）。BBOX とキャリブレーションだけで計算する。
速度・測定点・離隔距離は scripts/analyze_cvat_annotations.py の関数をそのまま使う。

測定点（速度・離隔距離・追い越し判定で共通）:
  自転車 : BBOX 下辺の中央 ((x1+x2)/2, y2)
  車     : BBOX 右下        (x2, y2)

追い越しタイミングは 2 方式で求める:
  射影方式 (主)   : 射影変換後の路面座標で、自転車と車の進行方向位置 v が入れ替わる瞬間。
                    フレーム間は線形補間してサブフレーム精度の時刻を出す。
  画像y2方式 (参考): アプリの assign_overtake と同じ。BBOX 底辺 y の差が
                    後方(±10px) -> 前方 に変わる区間で |差| が最小のフレーム（20px 以内）。
                    進行方向ラベルは射影モードで反転するため、自転車の y2 の増減から決める。

出力 (UTF-8 BOM 付き):
  overtake_events.csv       追い越し 1 件 1 行（時刻・速度・離隔距離）
  speed_per_frame.csv       トラック×フレームごとの速度と路面座標
  speed_every_6f.csv        6 フレームごとの速度中央値（自転車・車を列に並べた横持ち）
  speed_every_6f_linear.csv 同上。キーフレーム間を路面座標で線形補間した版
  speed_every_5m.csv        5 m 区間ごとの区間速度（区間長 / 通過時間）
  speed_every_5m_linear.csv 同上。キーフレーム間を路面座標で線形補間した版
  clearance_per_frame.csv   自転車×車の同一フレームごとの離隔距離
  track_speed_summary.csv   トラックごとの速度統計

使い方:
    python scripts/cvat_speed_clearance_overtake.py <annotations.xml> <calibration_profile> \
        <出力ディレクトリ> [--fps 29.97] [--margin-m 1.0] [--speed-step 6] [--section-m 5]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analyze_cvat_annotations import (  # noqa: E402
    BIKE_LABELS,
    CAR_LABELS,
    LANE_WIDTH_METERS,
    Projection,
    attach_measure_points,
    attach_world_columns,
    compute_clearance,
    compute_lane_columns,
    compute_speed,
    load_white_lines,
    parse_cvat_xml,
)

Y_MARGIN_PX = 10.0          # assign_overtake と同じ
CROSSING_THRESHOLD_PX = 20.0
AROUND_S = 1.0              # 追い越し前後の最小離隔・速度中央値を見る幅 [s]


def _timecode(sec: float) -> str:
    m, s = divmod(sec, 60.0)
    return "%02d:%06.3f" % (int(m), s)


def _median_speed(track: pd.DataFrame, frame: float, half: int) -> Optional[float]:
    win = track.loc[(track.index >= frame - half) & (track.index <= frame + half), "speed_km_h"]
    win = win[win > 0]
    return float(win.median()) if not win.empty else None


def _at(track: pd.DataFrame, frame: int, col: str) -> Optional[float]:
    val = track.at[frame, col] if frame in track.index else np.nan
    return float(val) if pd.notna(val) else None


def find_bev_crossings(gap: pd.Series, margin_m: float) -> List[float]:
    """gap = 車が自転車より進行方向に何 m 前にいるか。後方(<-margin) -> 前方(>+margin) の
    区間にある最後の符号反転を、線形補間したフレーム番号で返す。"""
    frames = gap.index.to_numpy(dtype=float)
    vals = gap.to_numpy(dtype=float)
    events: List[float] = []
    i = 0
    n = len(vals)
    while i < n:
        behind = np.where(vals[i:] < -margin_m)[0]
        if behind.size == 0:
            break
        b0 = i + behind[0]
        ahead = np.where(vals[b0:] > margin_m)[0]
        if ahead.size == 0:
            break
        a0 = b0 + ahead[0]
        last_behind = b0 + np.where(vals[b0:a0] < -margin_m)[0][-1]
        seg = vals[last_behind:a0 + 1]
        flips = np.where((seg[:-1] < 0) & (seg[1:] >= 0))[0]
        k = last_behind + (flips[-1] if flips.size else len(seg) - 2)
        v0, v1 = vals[k], vals[k + 1]
        t = 0.0 if v1 == v0 else -v0 / (v1 - v0)
        events.append(frames[k] + t * (frames[k + 1] - frames[k]))
        i = a0 + 1
    return events


def find_image_y2_crossing(car: pd.DataFrame, bike: pd.DataFrame, common) -> Optional[int]:
    diff = car.loc[common, "y2"] - bike.loc[common, "y2"]
    moving_down = bike["y2"].iloc[-1] > bike["y2"].iloc[0]   # 画面奥 -> 手前
    sign = 1.0 if moving_down else -1.0                      # 前方 = sign*diff > 0
    ahead = diff[sign * diff > Y_MARGIN_PX].index
    if ahead.empty:
        return None
    first_ahead = ahead.min()
    behind = diff[(sign * diff < -Y_MARGIN_PX) & (diff.index < first_ahead)]
    if behind.empty:
        return None
    window = diff.loc[behind.index.max():first_ahead]
    best = window.abs().idxmin()
    if abs(window.loc[best]) > CROSSING_THRESHOLD_PX:
        return None
    return int(best)


def _frame_speeds(g: pd.DataFrame, proj: Projection, fps: float, linear: bool) -> pd.Series:
    """1 フレーム間（frame -> frame+1）の速度 [km/h]。g は frame_num を index にした 1 トラック。

    linear=False : CVAT の補間座標をそのまま使う（両端とも測定区間内のときだけ）。
    linear=True  : キーフレーム間を路面座標で線形補間する。区間内の速度は
                   キーフレーム間の距離 / 時間で一定になる（両キーフレームとも測定区間内のときだけ）。
    """
    inside = g["bev_u_m"].between(0, proj.width_m) & g["bev_v_m"].between(0, proj.length_m)
    if linear:
        kf = g[g["is_keyframe"] == 1]
        spd = pd.Series(np.nan, index=g.index)
        for f0, f1 in zip(kf.index[:-1], kf.index[1:]):
            if inside[f0] and inside[f1]:
                dist = np.hypot(kf.at[f1, "bev_u_m"] - kf.at[f0, "bev_u_m"],
                                kf.at[f1, "bev_v_m"] - kf.at[f0, "bev_v_m"])
                spd.loc[f0:f1 - 1] = dist / ((f1 - f0) / fps) * 3.6
        return spd
    nxt = g.reindex(g.index + 1)
    ok = inside.values & nxt["bev_u_m"].between(0, proj.width_m).values \
        & nxt["bev_v_m"].between(0, proj.length_m).values
    dist = np.hypot(nxt["bev_u_m"].values - g["bev_u_m"].values,
                    nxt["bev_v_m"].values - g["bev_v_m"].values)
    return pd.Series(np.where(ok, dist * fps * 3.6, np.nan), index=g.index)


def speed_every_n_frames(df: pd.DataFrame, proj: Projection, fps: float,
                         step: int, linear: bool = False) -> pd.DataFrame:
    """step フレームごとの速度（代表値は中央値）を求め、トラックを列に並べる。

    1 フレーム間の速度（_frame_speeds）を、frame % step == 0 で始まる step フレームの
    区間ごとに中央値にする。frame 列は区間の先頭フレーム。
    測定点は attach_world_columns で求めた路面座標（自転車 = 下辺中央、車 = 右下）。
    区間内の有効な値が step の半分未満なら空欄にする。
    """
    is_bike = df["label"].str.lower().isin(BIKE_LABELS)
    order = (df.assign(_bike=is_bike)
             .drop_duplicates("track_id")
             .sort_values(["_bike", "track_id"], ascending=[False, True]))
    columns = {}
    for tid, label in zip(order["track_id"], order["label"]):
        g = df[df["track_id"] == tid].set_index("frame_num").sort_index()
        spd = _frame_speeds(g, proj, fps, linear)
        agg = spd.groupby(spd.index // step * step).agg(["median", "count"])
        columns["%s_%d_km_h" % (label, tid)] = agg["median"].where(agg["count"] >= max(step // 2, 1))

    out = pd.DataFrame(columns).dropna(how="all").sort_index()
    out.insert(0, "video_time_s", out.index / fps)
    out.index.name = "frame"
    return out.reset_index()


def speed_every_section(df: pd.DataFrame, proj: Projection, fps: float,
                        section_m: float, linear: bool = False) -> pd.DataFrame:
    """測定区間を進行方向に section_m ごとに区切り、区間速度（区間長 / 通過時間）を求める。

    境界 v を越えた時刻は、越える直前と直後のサンプルの間で線形補間する。
    サンプルは linear=False なら毎フレームの CVAT 補間座標、linear=True ならキーフレームのみ
    （= キーフレーム間を路面座標で線形補間）で、後者は前後のキーフレームとも測定区間内の
    ときだけ有効。最初に観測した時点で越えていた境界は通過時刻が分からないので空欄にする。
    行は進行方向の順（section_from_m = 進入側, section_to_m = 退出側）。
    """
    n = int(round(proj.length_m / section_m))
    edges = np.arange(n + 1) * section_m
    is_bike = df["label"].str.lower().isin(BIKE_LABELS)
    order = (df.assign(_bike=is_bike)
             .drop_duplicates("track_id")
             .sort_values(["_bike", "track_id"], ascending=[False, True]))
    columns = {}
    directions = []
    for tid, label in zip(order["track_id"], order["label"]):
        g = df[df["track_id"] == tid].sort_values("frame_num")
        if linear:
            g = g[g["is_keyframe"] == 1]
        if len(g) < 2:
            continue
        frames = g["frame_num"].to_numpy(dtype=float)
        v = g["bev_v_m"].to_numpy(dtype=float)
        inside = (g["bev_u_m"].between(0, proj.width_m)
                  & g["bev_v_m"].between(0, proj.length_m)).to_numpy()
        forward = -1.0 if v[-1] < v[0] else 1.0
        directions.append(forward)

        times = {}
        for k, b in enumerate(edges):
            p = forward * (v - b)
            hit = np.flatnonzero(p >= 0)
            if hit.size == 0 or hit[0] == 0:
                continue
            i = hit[0]
            if linear and not (inside[i - 1] and inside[i]):
                continue
            f = frames[i - 1] + (-p[i - 1]) / (p[i] - p[i - 1]) * (frames[i] - frames[i - 1])
            times[k] = f / fps

        speeds = {}
        for k in range(n):
            if k in times and k + 1 in times:
                dt = abs(times[k + 1] - times[k])
                if dt > 0:
                    speeds[k] = section_m / dt * 3.6
        columns["%s_%d_km_h" % (label, tid)] = pd.Series(speeds, dtype=float)

    out = pd.DataFrame(columns, index=range(n)).dropna(how="all")
    toward_near = (directions[0] if directions else -1.0) < 0
    out.insert(0, "section_from_m", edges[out.index + 1] if toward_near else edges[out.index])
    out.insert(1, "section_to_m", edges[out.index] if toward_near else edges[out.index + 1])
    return out.sort_values("section_from_m", ascending=not toward_near).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("xml")
    ap.add_argument("profile")
    ap.add_argument("outdir")
    ap.add_argument("--fps", type=float, default=29.97)
    ap.add_argument("--margin-m", type=float, default=1.0,
                    help="射影方式で後方/前方とみなす進行方向差の閾値 [m]")
    ap.add_argument("--speed-step", type=int, default=6,
                    help="speed_every_Nf.csv の速度を求めるフレーム間隔")
    ap.add_argument("--section-m", type=float, default=5.0,
                    help="speed_every_Nm.csv の区間長 [m]")
    args = ap.parse_args()
    fps = args.fps

    with open(os.path.join(ROOT, "output", "calibrations", args.profile + ".json"),
              encoding="utf-8") as fh:
        calib = json.load(fh)
    scale_meta = calib.get("scale", {}) or {}
    if (scale_meta.get("mode") or "").lower() != "homography":
        raise SystemExit("射影(homography)モードのキャリブレーションが必要です。")
    proj = Projection(scale_meta.get("homography") or {})
    if not proj.ok:
        raise SystemExit("射影変換を構築できません。")
    lines = load_white_lines(calib)
    lane_width_m = float(calib.get("lane_width_m") or LANE_WIDTH_METERS)

    df, meta = parse_cvat_xml(args.xml)
    df = df[df["is_held"] == 0].reset_index(drop=True)
    if df.empty:
        raise SystemExit("アノテーションに有効な BBOX がありません。")
    print("[入力] CVAT %s=%s %sx%s %sフレーム / track %d 本 / %s"
          % (meta["kind"], meta["task_id"], meta["width"], meta["height"], meta["size"],
             df["track_id"].nunique(), df.groupby("label")["track_id"].nunique().to_dict()))
    print("[入力] キャリブレーション %s: 幅%.1fm x 長さ%.1fm, fps=%.3f"
          % (args.profile, proj.width_m, proj.length_m, fps))

    df = attach_measure_points(df, lines)
    df = compute_speed(df, scale_meta, fps, point_x="measure_x")
    df = compute_lane_columns(df, lines, lane_width_m)
    df = attach_world_columns(df, proj)
    df["time_s"] = df["frame_num"] / fps
    df["in_region"] = (df["bev_u_m"].between(0, proj.width_m)
                       & df["bev_v_m"].between(0, proj.length_m)).astype(int)
    df.loc[df["speed_km_h"] <= 0, "speed_km_h"] = np.nan

    os.makedirs(args.outdir, exist_ok=True)

    # ---- 速度 --------------------------------------------------------------
    speed = df[[
        "frame_num", "time_s", "track_id", "label", "x1", "y1", "x2", "y2",
        "measure_x", "measure_y", "bev_u_m", "bev_v_m", "in_region",
        "speed_km_h", "acceleration_m_s2",
    ]].sort_values(["track_id", "frame_num"])

    speed_step = speed_every_n_frames(df, proj, fps, args.speed_step)
    speed_step_linear = speed_every_n_frames(df, proj, fps, args.speed_step, linear=True)
    speed_section = speed_every_section(df, proj, fps, args.section_m)
    speed_section_linear = speed_every_section(df, proj, fps, args.section_m, linear=True)

    summary = df.groupby(["track_id", "label"]).agg(
        first_frame=("frame_num", "min"), last_frame=("frame_num", "max"),
        speed_samples=("speed_km_h", "count"), mean_speed_km_h=("speed_km_h", "mean"),
        median_speed_km_h=("speed_km_h", "median"), max_speed_km_h=("speed_km_h", "max"),
    ).reset_index()
    summary.insert(4, "first_time_s", summary["first_frame"] / fps)
    summary.insert(5, "last_time_s", summary["last_frame"] / fps)

    # ---- 離隔距離 ----------------------------------------------------------
    label_lower = df["label"].str.lower()
    tracks = {tid: g.set_index("frame_num") for tid, g in df.groupby("track_id")}
    bike_ids = sorted(df.loc[label_lower.isin(BIKE_LABELS), "track_id"].unique())
    car_ids = sorted(df.loc[label_lower.isin(CAR_LABELS), "track_id"].unique())
    # 進行方向の符号: 自転車の v が減る向き（手前へ）に走っていれば -1
    forward = {
        bid: -1.0 if tracks[bid]["bev_v_m"].iloc[-1] < tracks[bid]["bev_v_m"].iloc[0] else 1.0
        for bid in bike_ids
    }

    clearance = compute_clearance(df, lines, lane_width_m, proj)
    if not clearance.empty:
        clearance = clearance.drop(columns=["bike_speed_km_h", "car_speed_km_h"])
        clearance["car_ahead_m"] = clearance["bike_track_id"].map(forward) * (
            clearance["car_bev_v_m"] - clearance["bike_bev_v_m"])
        both_in = (clearance[["bike_bev_v_m", "car_bev_v_m"]].apply(
            lambda s: s.between(0, proj.length_m)).all(axis=1))
        clearance["in_region"] = both_in.astype(int)
        clearance.insert(1, "time_s", clearance["frame_num"] / fps)

    # ---- 追い越しタイミング ------------------------------------------------
    half = int(round(AROUND_S * fps))

    events: List[dict] = []
    for bid in bike_ids:
        bike = tracks[bid]
        for cid in car_ids:
            car = tracks[cid]
            common = car.index.intersection(bike.index)
            if len(common) < 2:
                continue
            gap = forward[bid] * (car.loc[common, "bev_v_m"] - bike.loc[common, "bev_v_m"])
            y2_frame = find_image_y2_crossing(car, bike, common)
            for cross in find_bev_crossings(gap.dropna(), args.margin_m):
                f = int(round(cross))
                pair = clearance[(clearance["frame_num"] == f)
                                 & (clearance["bike_track_id"] == bid)
                                 & (clearance["car_track_id"] == cid)]
                around = clearance[(clearance["frame_num"].between(f - half, f + half))
                                   & (clearance["bike_track_id"] == bid)
                                   & (clearance["car_track_id"] == cid)]
                p = pair.iloc[0] if not pair.empty else {}
                bike_v = float(bike.at[f, "bev_v_m"])
                bike_spd = _at(bike, f, "speed_km_h")
                car_spd = _at(car, f, "speed_km_h")
                bike_med = _median_speed(bike, f, half // 2)
                car_med = _median_speed(car, f, half // 2)
                events.append({
                    "bike_track_id": bid,
                    "car_track_id": cid,
                    "overtake_frame": f,
                    "overtake_frame_interp": round(cross, 2),
                    "overtake_time_s": cross / fps,
                    "overtake_timecode": _timecode(cross / fps),
                    "bike_position_v_m": bike_v,
                    "in_region": int(0 <= bike_v <= proj.length_m),
                    "bike_speed_km_h": bike_spd,
                    "car_speed_km_h": car_spd,
                    "relative_speed_km_h": (car_spd - bike_spd) if bike_spd and car_spd else None,
                    "bike_speed_1s_median_km_h": bike_med,
                    "car_speed_1s_median_km_h": car_med,
                    "relative_speed_1s_median_km_h": (car_med - bike_med) if bike_med and car_med else None,
                    "clearance_lateral_m": p.get("bev_lateral_m"),
                    "clearance_bev_m": p.get("clearance_bev_m"),
                    "clearance_y_axis_m": p.get("clearance_y_axis_m"),
                    "min_clearance_lateral_pm1s_m": around["bev_lateral_m"].min() if not around.empty else None,
                    "bike_measure_u_m": p.get("bike_bev_u_m"),
                    "car_measure_u_m": p.get("car_bev_u_m"),
                    "image_y2_overtake_frame": y2_frame,
                    "image_y2_overtake_time_s": (y2_frame / fps) if y2_frame is not None else None,
                    "image_y2_minus_bev_s": ((y2_frame - cross) / fps) if y2_frame is not None else None,
                })

    ev = pd.DataFrame(events)
    if not ev.empty:
        ev = ev.sort_values("overtake_frame_interp").reset_index(drop=True)
        ev.insert(0, "event_no", range(1, len(ev) + 1))

    outputs = [
        ("overtake_events.csv", ev),
        ("speed_per_frame.csv", speed),
        ("speed_every_%df.csv" % args.speed_step, speed_step),
        ("speed_every_%df_linear.csv" % args.speed_step, speed_step_linear),
        ("speed_every_%gm.csv" % args.section_m, speed_section),
        ("speed_every_%gm_linear.csv" % args.section_m, speed_section_linear),
        ("clearance_per_frame.csv", clearance),
        ("track_speed_summary.csv", summary),
    ]
    for name, frame in outputs:
        frame = frame.copy()
        for c in frame.columns:
            if frame[c].dtype.kind == "f":
                frame[c] = frame[c].round(3)
        path = os.path.join(args.outdir, name)
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        print("  %s (%d 行)" % (path, len(frame)))

    if not ev.empty:
        print("\n[追い越し] %d 件" % len(ev))
        for r in ev.itertuples():
            print("  #%d 車%d -> 自転車%d  %s (frame %d)  v=%.1fm  自転車 %.1f / 車 %.1f km/h  横離隔 %.2f m"
                  % (r.event_no, r.car_track_id, r.bike_track_id, r.overtake_timecode,
                     r.overtake_frame, r.bike_position_v_m,
                     r.bike_speed_1s_median_km_h or float("nan"), r.car_speed_1s_median_km_h or float("nan"),
                     r.clearance_lateral_m if r.clearance_lateral_m is not None else float("nan")))


if __name__ == "__main__":
    main()
