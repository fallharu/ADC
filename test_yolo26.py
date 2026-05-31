# test_yolo26.py
# -*- coding: utf-8 -*-
"""
YOLO 前処理×Tracking ベンチ(bicycle/car)
- 実行ごとに ./yolo26test/_tmp をリセット
- runs/<run_id> に全ログ・描画動画・設定を保存
- 複数同時追跡
- パターン結果を"継ぎ接ぎ"して gap を線形補間で埋めた stitched 出力を生成
- y方向(上部が弱い)改善を縦binで可視化
- GUIで進捗(全体 / 現在YOLO)を表示
"""

import os
import json
import time
import shutil
import math
import threading
import platform
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional, Any

import cv2
import numpy as np
import pandas as pd

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ultralytics import YOLO

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


# -----------------------------
# 前処理
# -----------------------------
@dataclass(frozen=True)
class PreprocSpec:
    name: str
    kind: str
    params: dict

def apply_preproc(img_bgr: np.ndarray, spec: PreprocSpec) -> np.ndarray:
    img = img_bgr

    if spec.kind == "none":
        return img

    if spec.kind == "brightness_contrast":
        alpha = float(spec.params.get("alpha", 1.0))
        beta = float(spec.params.get("beta", 0.0))
        return cv2.convertScaleAbs(img, alpha=alpha, beta=beta)

    if spec.kind == "gamma":
        gamma = float(spec.params.get("gamma", 1.0))
        inv = 1.0 / max(gamma, 1e-6)
        table = (np.array([((i / 255.0) ** inv) * 255 for i in range(256)])).astype("uint8")
        return cv2.LUT(img, table)

    if spec.kind == "grayscale":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    if spec.kind == "clahe_l":
        clip = float(spec.params.get("clip", 2.0))
        tile = int(spec.params.get("tile", 8))
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(tile, tile))
        l2 = clahe.apply(l)
        lab2 = cv2.merge((l2, a, b))
        return cv2.cvtColor(lab2, cv2.COLOR_LAB2BGR)

    if spec.kind == "denoise":
        h = float(spec.params.get("h", 7))
        return cv2.fastNlMeansDenoisingColored(img, None, h, h, 7, 21)

    if spec.kind == "sharpen":
        k = float(spec.params.get("k", 1.0))
        blur = cv2.GaussianBlur(img, (0, 0), 1.0)
        return cv2.addWeighted(img, 1.0 + k, blur, -k, 0)

    if spec.kind == "combo":
        steps = spec.params.get("steps", [])
        out = img
        for s in steps:
            sub = PreprocSpec(name=s["name"], kind=s["kind"], params=s.get("params", {}))
            out = apply_preproc(out, sub)
        return out

    return img

def default_preproc_suite() -> List[PreprocSpec]:
    return [
        PreprocSpec("baseline_none", "none", {}),
        PreprocSpec("bc_mild(+10)", "brightness_contrast", {"alpha": 1.05, "beta": 10}),
        PreprocSpec("bc_strong(+25)", "brightness_contrast", {"alpha": 1.10, "beta": 25}),
        PreprocSpec("contrast_up", "brightness_contrast", {"alpha": 1.20, "beta": 0}),
        PreprocSpec("gamma_0.8", "gamma", {"gamma": 0.8}),
        PreprocSpec("gamma_1.2", "gamma", {"gamma": 1.2}),
        PreprocSpec("grayscale", "grayscale", {}),
        PreprocSpec("clahe_clip2", "clahe_l", {"clip": 2.0, "tile": 8}),
        PreprocSpec("denoise_h7", "denoise", {"h": 7}),
        PreprocSpec("sharpen_k0.8", "sharpen", {"k": 0.8}),
        PreprocSpec("combo_bc+clahe",
                    "combo",
                    {"steps": [
                        {"name": "bc", "kind": "brightness_contrast", "params": {"alpha": 1.10, "beta": 15}},
                        {"name": "clahe", "kind": "clahe_l", "params": {"clip": 2.0, "tile": 8}},
                    ]}),
    ]


# -----------------------------
# 共通ユーティリティ
# -----------------------------
def safe_makedirs(p: str):
    os.makedirs(p, exist_ok=True)

def now_run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S")

def video_total_frames(cap: cv2.VideoCapture) -> int:
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    return max(n, 0)

def read_video_meta(video_path: str) -> Dict[str, Any]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {}
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    n = video_total_frames(cap)
    cap.release()
    return {"width": w, "height": h, "fps": fps, "frames": n}

def iou_xyxy(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(ix2 - ix1, 0.0), max(iy2 - iy1, 0.0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    aa = max(ax2 - ax1, 0.0) * max(ay2 - ay1, 0.0)
    bb = max(bx2 - bx1, 0.0) * max(by2 - by1, 0.0)
    denom = aa + bb - inter
    return float(inter / denom) if denom > 0 else 0.0

def bbox_center_wh(x1,y1,x2,y2):
    cx = (x1+x2)/2.0
    cy = (y1+y2)/2.0
    w = max(x2-x1, 0.0)
    h = max(y2-y1, 0.0)
    return cx, cy, w, h

def clamp_bbox(x1,y1,x2,y2,W,H):
    x1 = max(0.0, min(float(W-1), x1))
    x2 = max(0.0, min(float(W-1), x2))
    y1 = max(0.0, min(float(H-1), y1))
    y2 = max(0.0, min(float(H-1), y2))
    if x2 < x1: x1, x2 = x2, x1
    if y2 < y1: y1, y2 = y2, y1
    return x1,y1,x2,y2


# -----------------------------
# 検出・トラッキング
# -----------------------------
@dataclass
class RunConfig:
    video_path: str
    model_path: str
    out_root: str
    conf: float = 0.25
    iou: float = 0.7
    imgsz: int = 640
    device: str = ""
    tracker: str = "bytetrack.yaml"
    every_n: int = 1
    max_frames: int = 0
    seed: int = 123
    # y-bin
    y_bins: int = 12
    # overlay
    write_overlay: bool = True

@dataclass
class PatternResult:
    pattern_name: str
    csv_path: str
    overlay_path: str
    summary_path: str
    ybins_path: str
    summary: dict

def resolve_class_ids(model: YOLO, want_names=("bicycle", "car")) -> Dict[str, Optional[int]]:
    names = model.names
    out = {n: None for n in want_names}
    if isinstance(names, dict):
        for k, v in names.items():
            for n in want_names:
                if str(v).lower() == n.lower():
                    out[n] = int(k)
    else:
        for i, v in enumerate(names):
            for n in want_names:
                if str(v).lower() == n.lower():
                    out[n] = int(i)
    return out

def draw_box(img, x1,y1,x2,y2, text, color=(0,255,0)):
    cv2.rectangle(img, (int(x1),int(y1)), (int(x2),int(y2)), color, 2)
    if text:
        cv2.putText(img, text, (int(x1), max(0,int(y1)-5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

def compute_ybins(df: pd.DataFrame, H: int, bins: int) -> pd.DataFrame:
    if len(df) == 0 or H <= 0:
        return pd.DataFrame(columns=["bin", "y0", "y1", "det_count", "frame_hits"])
    cy = (df["y1"].values + df["y2"].values) / 2.0
    yn = np.clip(cy / float(H), 0.0, 0.999999)
    b = (yn * bins).astype(int)
    df2 = df.copy()
    df2["ybin"] = b
    det_count = df2.groupby("ybin").size()
    frame_hits = df2.groupby("ybin")["frame"].nunique()
    rows = []
    for i in range(bins):
        rows.append({
            "bin": i,
            "y0": i / bins,
            "y1": (i+1) / bins,
            "det_count": int(det_count.get(i, 0)),
            "frame_hits": int(frame_hits.get(i, 0)),
        })
    return pd.DataFrame(rows)

class Progress:
    """スレッド間で進捗共有するだけの軽量構造"""
    def __init__(self):
        self.lock = threading.Lock()
        self.phase = "idle"
        self.pattern = ""
        self.pattern_i = 0
        self.pattern_n = 0
        self.frame = 0
        self.frame_n = 0
        self.global_done = 0
        self.global_total = 0
        self.message = ""

    def set(self, **kwargs):
        with self.lock:
            for k,v in kwargs.items():
                setattr(self, k, v)

    def get(self):
        with self.lock:
            return dict(
                phase=self.phase,
                pattern=self.pattern,
                pattern_i=self.pattern_i,
                pattern_n=self.pattern_n,
                frame=self.frame,
                frame_n=self.frame_n,
                global_done=self.global_done,
                global_total=self.global_total,
                message=self.message,
            )

def run_pattern_tracking(cfg: RunConfig, spec: PreprocSpec,
                         class_filter: Tuple[int, ...],
                         out_dir_pattern: str,
                         progress: Progress,
                         stop_event: threading.Event) -> PatternResult:
    """
    重要:patternごとに YOLO(model) を作り直して tracker state をリセットする
    (環境差を受けにくく、公平な比較になる)
    """
    safe_makedirs(out_dir_pattern)
    csv_path = os.path.join(out_dir_pattern, "detections.csv")
    overlay_path = os.path.join(out_dir_pattern, "overlay.mp4")
    summary_path = os.path.join(out_dir_pattern, "summary.json")
    ybins_path = os.path.join(out_dir_pattern, "y_bins.csv")

    # model create per pattern (tracker reset)
    model = YOLO(cfg.model_path)

    cap = cv2.VideoCapture(cfg.video_path)
    if not cap.isOpened():
        raise RuntimeError(f"動画を開けません: {cfg.video_path}")

    meta = read_video_meta(cfg.video_path)
    W, H = int(meta.get("width", 0)), int(meta.get("height", 0))
    fps = float(meta.get("fps", 0.0) or 30.0)
    total = int(meta.get("frames", 0))

    writer = None
    if cfg.write_overlay:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(overlay_path, fourcc, fps / max(cfg.every_n,1), (W,H))

    rows = []
    frame_idx = -1
    processed = 0
    dets = 0
    t0 = time.time()

    # global total estimation (rough): handled in caller
    progress.set(phase="tracking", frame=0, frame_n=(cfg.max_frames if cfg.max_frames>0 else total))

    while True:
        if stop_event.is_set():
            break
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1

        if cfg.max_frames > 0 and processed >= cfg.max_frames:
            break
        if cfg.every_n > 1 and (frame_idx % cfg.every_n) != 0:
            continue

        processed += 1
        progress.set(frame=processed, message=f"{spec.name} tracking frame {processed}")

        img = apply_preproc(frame, spec)

        res = model.track(
            source=img,
            conf=cfg.conf,
            iou=cfg.iou,
            imgsz=cfg.imgsz,
            device=cfg.device if cfg.device else None,
            classes=list(class_filter) if class_filter else None,
            tracker=cfg.tracker,
            persist=True,
            verbose=False,
        )

        r0 = res[0]
        draw = frame.copy()  # overlayは元画に描く(前処理後を見たければ img に変更)

        if r0.boxes is not None and len(r0.boxes) > 0:
            boxes = r0.boxes
            xyxy = boxes.xyxy.cpu().numpy()
            cls = boxes.cls.cpu().numpy().astype(int)
            conf = boxes.conf.cpu().numpy()
            tid = None
            try:
                if boxes.id is not None:
                    tid = boxes.id.cpu().numpy().astype(int)
            except Exception:
                tid = None

            for i in range(len(xyxy)):
                x1,y1,x2,y2 = map(float, xyxy[i])
                c = int(cls[i])
                cf = float(conf[i])
                track_id = int(tid[i]) if tid is not None else -1

                rows.append({
                    "pattern": spec.name,
                    "frame": frame_idx,
                    "cls": c,
                    "conf": cf,
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "track_id": track_id,
                    "is_interpolated": 0,
                    "chosen_pattern": spec.name,
                })
                dets += 1

                # draw
                txt = f"id:{track_id} c:{c} {cf:.2f}"
                color = (0,255,0) if c == (class_filter[0] if len(class_filter)>0 else c) else (255,128,0)
                draw_box(draw, x1,y1,x2,y2, txt, color=color)

        if writer is not None:
            writer.write(draw)

        # global progress is updated by caller

    cap.release()
    if writer is not None:
        writer.release()

    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    ydf = compute_ybins(df, H=H, bins=cfg.y_bins)
    ydf.to_csv(ybins_path, index=False, encoding="utf-8-sig")

    dt = time.time() - t0
    summary = {
        "pattern": spec.name,
        "video": cfg.video_path,
        "processed_frames": int(processed),
        "seconds": float(dt),
        "detections": int(len(df)),
        "tracks": int(df["track_id"].nunique()) if len(df) else 0,
        "y_bins": int(cfg.y_bins),
    }

    if len(df):
        cls_frame = df.groupby("cls")["frame"].nunique().to_dict()
        summary["class_detected_frames"] = {str(k): int(v) for k,v in cls_frame.items()}
        dft = df[df["track_id"] >= 0]
        if len(dft):
            per_track = dft.groupby("track_id")["frame"].nunique()
            summary["frames_per_track_mean"] = float(per_track.mean())
        else:
            summary["frames_per_track_mean"] = 0.0

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return PatternResult(
        pattern_name=spec.name,
        csv_path=csv_path,
        overlay_path=overlay_path if cfg.write_overlay else "",
        summary_path=summary_path,
        ybins_path=ybins_path,
        summary=summary
    )


# -----------------------------
# 継ぎ接ぎ(複数同時)
# -----------------------------
@dataclass
class Tracklet:
    cls: int
    start: int
    end: int
    pattern: str
    track_id: int
    frames: np.ndarray          # shape (T,)
    boxes: np.ndarray           # shape (T,4) xyxy
    confs: np.ndarray           # shape (T,)

def extract_tracklets(df: pd.DataFrame, min_len: int = 3) -> List[Tracklet]:
    if len(df) == 0:
        return []
    out = []
    for (pat, c, tid), g in df.groupby(["chosen_pattern","cls","track_id"]):
        if int(tid) < 0:
            continue
        g2 = g.sort_values("frame")
        frames = g2["frame"].to_numpy().astype(int)
        boxes = g2[["x1","y1","x2","y2"]].to_numpy().astype(float)
        confs = g2["conf"].to_numpy().astype(float)

        # 連続区間に分割(gapで切る)
        cuts = [0]
        for i in range(1, len(frames)):
            if frames[i] != frames[i-1] + 1:
                cuts.append(i)
        cuts.append(len(frames))

        for a,b in zip(cuts[:-1], cuts[1:]):
            if b-a < min_len:
                continue
            fr = frames[a:b]
            bx = boxes[a:b]
            cf = confs[a:b]
            out.append(Tracklet(
                cls=int(c),
                start=int(fr[0]),
                end=int(fr[-1]),
                pattern=str(pat),
                track_id=int(tid),
                frames=fr,
                boxes=bx,
                confs=cf
            ))
    return out

def stitch_multi_object(
    all_patterns_df: pd.DataFrame,
    meta: Dict[str,Any],
    max_gap: int = 10,
    iou_thr_connect: float = 0.1,
    dist_thr: float = 80.0,
) -> pd.DataFrame:
    """
    複数同時前提の"継ぎ接ぎ":
    - 各patternのtrackをtracklet化
    - 同一cls内で「時間順につながりを探索し、複数のstitched trackを生成
    - gapは前後がある場合、線形補間で埋める
    """
    W, H = int(meta.get("width",0)), int(meta.get("height",0))
    if len(all_patterns_df) == 0:
        return pd.DataFrame()

    # Tracklet化
    tls = extract_tracklets(all_patterns_df, min_len=3)

    # clsごとに分ける
    stitched_rows = []
    stitched_id_counter = 0

    for cls_id in sorted(set([t.cls for t in tls])):
        cls_tls = [t for t in tls if t.cls == cls_id]
        cls_tls.sort(key=lambda t: (t.start, t.end))

        used = set()

        def end_state(t: Tracklet):
            x1,y1,x2,y2 = t.boxes[-1]
            cx,cy,w,h = bbox_center_wh(x1,y1,x2,y2)
            return np.array([cx,cy,w,h], dtype=float)

        def start_state(t: Tracklet):
            x1,y1,x2,y2 = t.boxes[0]
            cx,cy,w,h = bbox_center_wh(x1,y1,x2,y2)
            return np.array([cx,cy,w,h], dtype=float)

        # greedyに複数トラックを組む(研究用途として堅牢)
        for i, t0 in enumerate(cls_tls):
            if i in used:
                continue
            chain = [i]
            used.add(i)

            cur = t0
            while True:
                best_j = None
                best_score = -1e9
                cur_end = cur.end

                cur_end_box = cur.boxes[-1]
                cur_end_st = end_state(cur)

                for j, cand in enumerate(cls_tls):
                    if j in used:
                        continue
                    if cand.start <= cur_end:
                        continue
                    gap = cand.start - cur_end - 1
                    if gap < 0 or gap > max_gap:
                        continue

                    # 接続評価:IoU(終端box vs 始端box) + 距離
                    iou = iou_xyxy(tuple(cur_end_box.tolist()), tuple(cand.boxes[0].tolist()))
                    st = start_state(cand)
                    dist = float(np.linalg.norm((st[:2] - cur_end_st[:2])))

                    if iou < iou_thr_connect and dist > dist_thr:
                        continue

                    # スコア:IoU優先、距離小、gap短、conf高
                    score = (2.0*iou) - (0.01*dist) - (0.2*gap) + float(np.mean(cand.confs))
                    if score > best_score:
                        best_score = score
                        best_j = j

                if best_j is None:
                    break
                chain.append(best_j)
                used.add(best_j)
                cur = cls_tls[best_j]

            # chainから stitched track を構築(gapは線形補間)
            stitched_id_counter += 1
            sid = stitched_id_counter

            # まずchainの実測を全部入れる(後でgap埋め)
            # frame->rowを辞書で保持
            fmap: Dict[int, Dict[str,Any]] = {}

            # chain順に追加
            chain_tls = [cls_tls[k] for k in chain]
            chain_tls.sort(key=lambda t: t.start)

            for t in chain_tls:
                for fr, bx, cf in zip(t.frames, t.boxes, t.confs):
                    fr = int(fr)
                    x1,y1,x2,y2 = bx.tolist()
                    fmap[fr] = {
                        "frame": fr,
                        "cls": cls_id,
                        "x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2),
                        "conf": float(cf),
                        "stitched_track_id": sid,
                        "chosen_pattern": t.pattern,
                        "original_track_id": t.track_id,
                        "is_interpolated": 0,
                    }

            # gap補間(前後がある場合は線形補間)
            frames_sorted = sorted(fmap.keys())
            if len(frames_sorted) >= 2:
                for a,b in zip(frames_sorted[:-1], frames_sorted[1:]):
                    if b == a + 1:
                        continue
                    # gap存在
                    fa = fmap[a]
                    fb = fmap[b]
                    gap = b - a - 1
                    # 線形補間
                    xa = np.array([fa["x1"],fa["y1"],fa["x2"],fa["y2"]], dtype=float)
                    xb = np.array([fb["x1"],fb["y1"],fb["x2"],fb["y2"]], dtype=float)
                    for k in range(1, gap+1):
                        t = k / float(gap+1)
                        x = (1-t)*xa + t*xb
                        x1,y1,x2,y2 = x.tolist()
                        x1,y1,x2,y2 = clamp_bbox(x1,y1,x2,y2,W,H)
                        fr = a + k
                        if fr in fmap:
                            continue
                        fmap[fr] = {
                            "frame": int(fr),
                            "cls": cls_id,
                            "x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2),
                            "conf": 0.0,  # 補間はconf=0(検知ではない)
                            "stitched_track_id": sid,
                            "chosen_pattern": fa.get("chosen_pattern",""),
                            "original_track_id": fa.get("original_track_id",-1),
                            "is_interpolated": 1,
                        }

            # stitched track rows
            for fr in sorted(fmap.keys()):
                stitched_rows.append(fmap[fr])

    df_out = pd.DataFrame(stitched_rows).sort_values(["cls","stitched_track_id","frame"])
    return df_out

def write_stitched_overlay(video_path: str, meta: Dict[str,Any], stitched_df: pd.DataFrame, out_mp4: str,
                          every_n: int = 1):
    W, H = int(meta.get("width",0)), int(meta.get("height",0))
    fps = float(meta.get("fps",0.0) or 30.0)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_mp4, fourcc, fps / max(every_n,1), (W,H))

    # frame -> rows
    g = {int(f): gg for f, gg in stitched_df.groupby("frame")} if len(stitched_df) else {}

    frame_idx = -1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        if every_n > 1 and (frame_idx % every_n) != 0:
            continue

        draw = frame.copy()
        if frame_idx in g:
            gg = g[frame_idx]
            for _, r in gg.iterrows():
                x1,y1,x2,y2 = float(r.x1),float(r.y1),float(r.x2),float(r.y2)
                sid = int(r.stitched_track_id)
                c = int(r.cls)
                interp = int(r.is_interpolated)
                color = (0,255,0) if interp==0 else (0,255,255)  # 実測=緑, 補間=黄
                txt = f"sid:{sid} c:{c}" + (" interp" if interp else "")
                draw_box(draw, x1,y1,x2,y2, txt, color=color)

        writer.write(draw)

    cap.release()
    writer.release()


# -----------------------------
# GUI
# -----------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YOLO 前処理×Tracking ベンチ(複数同時 + 継ぎ接ぎ)")
        self.geometry("1380x900")

        # Initialize Tkinter variables after super().__init__()
        self.video_path = tk.StringVar(master=self)
        self.model_path = tk.StringVar(master=self)
        self.root_dir = tk.StringVar(master=self, value=os.path.join(os.getcwd(), "yolo26test"))

        self.conf = tk.DoubleVar(master=self, value=0.25)
        self.iou = tk.DoubleVar(master=self, value=0.7)
        self.imgsz = tk.IntVar(master=self, value=640)
        self.every_n = tk.IntVar(master=self, value=1)
        self.max_frames = tk.IntVar(master=self, value=0)
        self.seed = tk.IntVar(master=self, value=123)
        self.tracker = tk.StringVar(master=self, value="bytetrack.yaml")

        # y bins / stitch
        self.y_bins = tk.IntVar(master=self, value=12)
        self.stitch_max_gap = tk.IntVar(master=self, value=10)
        self.stitch_iou_thr = tk.DoubleVar(master=self, value=0.10)
        self.stitch_dist_thr = tk.DoubleVar(master=self, value=80.0)

        # auto explore
        self.auto_iters = tk.IntVar(master=self, value=20)

        self.patterns: List[PreprocSpec] = default_preproc_suite()

        self._worker = None
        self._stop = threading.Event()
        self.progress = Progress()

        # Initialize status variable before _build_ui
        self.status = tk.StringVar(master=self, value="待機中")
        
        self._build_ui()

        # progress poll
        self.after(100, self._poll_progress)

    def _build_ui(self):
        top = ttk.Frame(self); top.pack(fill="x", padx=10, pady=8)

        row1 = ttk.Frame(top); row1.pack(fill="x", pady=3)
        ttk.Label(row1, text="動画").pack(side="left", padx=(0,8))
        ttk.Entry(row1, textvariable=self.video_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row1, text="選択", command=self.pick_video).pack(side="left", padx=6)

        row2 = ttk.Frame(top); row2.pack(fill="x", pady=3)
        ttk.Label(row2, text="YOLO model(.pt)").pack(side="left", padx=(0,8))
        ttk.Entry(row2, textvariable=self.model_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row2, text="選択", command=self.pick_model).pack(side="left", padx=6)

        row3 = ttk.Frame(top); row3.pack(fill="x", pady=3)
        ttk.Label(row3, text="root(yolo26test)").pack(side="left", padx=(0,8))
        ttk.Entry(row3, textvariable=self.root_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(row3, text="選択", command=self.pick_root).pack(side="left", padx=6)

        opts = ttk.LabelFrame(self, text="推論設定"); opts.pack(fill="x", padx=10, pady=8)
        grid = ttk.Frame(opts); grid.pack(fill="x", padx=8, pady=6)

        def add(r, c, label, var, w=10):
            ttk.Label(grid, text=label).grid(row=r, column=c, sticky="w", padx=6, pady=3)
            ttk.Entry(grid, textvariable=var, width=w).grid(row=r, column=c+1, sticky="w", padx=6, pady=3)

        add(0,0,"conf", self.conf)
        add(0,2,"iou", self.iou)
        add(0,4,"imgsz", self.imgsz)
        add(0,6,"every_n", self.every_n)
        add(0,8,"max_frames(0=全)", self.max_frames, w=12)

        add(1,0,"seed", self.seed)
        ttk.Label(grid, text="tracker").grid(row=1, column=2, sticky="w", padx=6, pady=3)
        ttk.Entry(grid, textvariable=self.tracker, width=20).grid(row=1, column=3, sticky="w", padx=6, pady=3)
        add(1,4,"y_bins", self.y_bins)

        stitch = ttk.LabelFrame(self, text="継ぎ接ぎ(複数同時)"); stitch.pack(fill="x", padx=10, pady=8)
        sgrid = ttk.Frame(stitch); sgrid.pack(fill="x", padx=8, pady=6)
        add(0,0,"max_gap(frames)", self.stitch_max_gap)
        add(0,2,"connect IoU thr", self.stitch_iou_thr)
        add(0,4,"connect dist thr(px)", self.stitch_dist_thr, w=12)

        auto = ttk.LabelFrame(self, text="自動探索(簡易)"); auto.pack(fill="x", padx=10, pady=8)
        agrid = ttk.Frame(auto); agrid.pack(fill="x", padx=8, pady=6)
        add(0,0,"auto_iters", self.auto_iters)

        btns = ttk.Frame(self); btns.pack(fill="x", padx=10, pady=6)
        self.run_btn = ttk.Button(btns, text="実行", command=self.start); self.run_btn.pack(side="left")
        ttk.Button(btns, text="停止", command=self.stop).pack(side="left", padx=8)

        # progress bars - status label now uses pre-initialized self.status
        ttk.Label(btns, textvariable=self.status).pack(side="left", padx=12)

        pb = ttk.Frame(self); pb.pack(fill="x", padx=10, pady=(0,8))
        self.pb_global = ttk.Progressbar(pb, orient="horizontal", mode="determinate")
        self.pb_global.pack(fill="x", expand=True, side="top")
        self.pb_pattern = ttk.Progressbar(pb, orient="horizontal", mode="determinate")
        self.pb_pattern.pack(fill="x", expand=True, side="top", pady=(6,0))

        mid = ttk.Frame(self); mid.pack(fill="both", expand=True, padx=10, pady=8)
        left = ttk.Frame(mid); left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(mid); right.pack(side="right", fill="both", expand=True)

        self.tree = ttk.Treeview(left, columns=("pattern","detections","tracks","sec"),
                                 show="headings", height=18)
        for c,t,w in [
            ("pattern","pattern",220),
            ("detections","detections",100),
            ("tracks","tracks",90),
            ("sec","sec",80),
        ]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)

        # plot (y-bins)
        fig = Figure(figsize=(6.4, 6.0), dpi=100)
        self.ax = fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def pick_video(self):
        p = filedialog.askopenfilename(
            title="動画を選択",
            filetypes=[("Video","*.mp4;*.avi;*.mov;*.mkv;*.m4v;*.wmv"), ("All","*.*")]
        )
        if p: self.video_path.set(p)

    def pick_model(self):
        p = filedialog.askopenfilename(title="YOLO重み(.pt)を選択",
                                       filetypes=[("PyTorch","*.pt"),("All","*.*")])
        if p: self.model_path.set(p)

    def pick_root(self):
        p = filedialog.askdirectory(title="rootフォルダを選択")
        if p: self.root_dir.set(p)

    def stop(self):
        if self._worker and self._worker.is_alive():
            self._stop.set()
            self.status.set("停止要求を送信しました(安全に停止中)")

    def start(self):
        if not self.video_path.get() or not self.model_path.get():
            messagebox.showerror("不足", "動画とモデル(.pt)を選択してください。")
            return
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("実行中", "すでに実行中です。")
            return

        self._stop.clear()
        self.run_btn.configure(state="disabled")
        self.tree.delete(*self.tree.get_children())
        self.ax.clear(); self.canvas.draw()

        self._worker = threading.Thread(target=self._run_all, daemon=True)
        self._worker.start()

    def _poll_progress(self):
        p = self.progress.get()
        # status
        if p["phase"] != "idle":
            msg = f'{p["phase"]} | {p["pattern"]} ({p["pattern_i"]}/{p["pattern_n"]}) | {p["message"]}'
            self.status.set(msg)

        # global bar
        gt = max(int(p["global_total"]), 1)
        gd = int(p["global_done"])
        self.pb_global["maximum"] = gt
        self.pb_global["value"] = min(gd, gt)

        # pattern bar
        ft = max(int(p["frame_n"]), 1)
        fd = int(p["frame"])
        self.pb_pattern["maximum"] = ft
        self.pb_pattern["value"] = min(fd, ft)

        self.after(120, self._poll_progress)

    def _random_specs(self, iters: int, seed: int) -> List[PreprocSpec]:
        rng = np.random.default_rng(seed + 999)
        out = []
        for k in range(iters):
            alpha = float(rng.uniform(0.85, 1.45))
            beta  = float(rng.uniform(-25, 45))
            gamma = float(rng.uniform(0.70, 1.45))
            use_clahe = bool(rng.random() < 0.35)
            use_denoise = bool(rng.random() < 0.25)
            use_sharp = bool(rng.random() < 0.25)
            steps = [
                {"name":"bc","kind":"brightness_contrast","params":{"alpha":alpha,"beta":beta}},
                {"name":"gamma","kind":"gamma","params":{"gamma":gamma}},
            ]
            if use_clahe:
                steps.append({"name":"clahe","kind":"clahe_l","params":{"clip":float(rng.uniform(1.5,3.5)),"tile":8}})
            if use_denoise:
                steps.append({"name":"denoise","kind":"denoise","params":{"h":float(rng.uniform(5,12))}})
            if use_sharp:
                steps.append({"name":"sharpen","kind":"sharpen","params":{"k":float(rng.uniform(0.4,1.2))}})

            name = f"auto_{k:03d}_a{alpha:.2f}_b{beta:.0f}_g{gamma:.2f}" \
                   + ("_clahe" if use_clahe else "") \
                   + ("_dn" if use_denoise else "") \
                   + ("_sh" if use_sharp else "")
            out.append(PreprocSpec(name, "combo", {"steps":steps}))
        return out

    def _render_table_and_yplot(self, results: List[PatternResult], best_name: Optional[str] = None):
        self.tree.delete(*self.tree.get_children())

        # y-bin plot uses best vs baseline
        baseline = next((r for r in results if r.pattern_name=="baseline_none"), None)
        best = next((r for r in results if r.pattern_name==best_name), None) if best_name else None

        for r in results:
            s = r.summary
            self.tree.insert("", "end", values=(
                r.pattern_name,
                s.get("detections",0),
                s.get("tracks",0),
                f'{s.get("seconds",0.0):.1f}',
            ))

        self.ax.clear()
        # y-bins compare (frame_hits)
        def load_ybins(path):
            if path and os.path.exists(path):
                d = pd.read_csv(path)
                return d
            return None

        by = load_ybins(baseline.ybins_path) if baseline else None
        if by is not None:
            y = by["bin"].to_numpy()
            self.ax.plot(by["frame_hits"].to_numpy(), y, label="baseline frame_hits", linewidth=2)

        if best is not None:
            dy = load_ybins(best.ybins_path)
            if dy is not None:
                self.ax.plot(dy["frame_hits"].to_numpy(), dy["bin"].to_numpy(), label=f"best({best.pattern_name}) frame_hits", linewidth=2)

                # diff (best - baseline)
                if by is not None and len(by)==len(dy):
                    diff = (dy["frame_hits"] - by["frame_hits"]).to_numpy()
                    self.ax.plot(diff, dy["bin"].to_numpy(), label="diff(best-baseline)", linestyle="--")

        self.ax.set_xlabel("frame_hits (per y-bin)")
        self.ax.set_ylabel("y-bin (0=top)")
        self.ax.invert_yaxis()  # 上が上に見えるように
        self.ax.grid(True, alpha=0.3)
        self.ax.legend()
        self.canvas.draw()

    def _run_all(self):
        try:
            root = self.root_dir.get()
            tmp_dir = os.path.join(root, "_tmp")
            runs_dir = os.path.join(root, "runs")
            safe_makedirs(root); safe_makedirs(runs_dir)

            # reset tmp
            self.progress.set(phase="setup", message="reset tmp folder")
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
            safe_makedirs(tmp_dir)

            run_id = now_run_id()
            out_root = os.path.join(runs_dir, run_id)
            safe_makedirs(out_root)

            # meta
            meta = read_video_meta(self.video_path.get())

            # resolve classes (once)
            self.progress.set(phase="setup", message="load model to resolve classes")
            model_probe = YOLO(self.model_path.get())
            cls_map = resolve_class_ids(model_probe, ("bicycle","car"))
            class_filter = tuple([c for c in cls_map.values() if c is not None])

            cfg = RunConfig(
                video_path=self.video_path.get(),
                model_path=self.model_path.get(),
                out_root=out_root,
                conf=float(self.conf.get()),
                iou=float(self.iou.get()),
                imgsz=int(self.imgsz.get()),
                tracker=self.tracker.get(),
                every_n=max(int(self.every_n.get()),1),
                max_frames=max(int(self.max_frames.get()),0),
                seed=int(self.seed.get()),
                y_bins=max(int(self.y_bins.get()), 4),
                write_overlay=True,
            )

            # patterns + auto
            iters = max(int(self.auto_iters.get()), 0)
            auto_specs = self._random_specs(iters, cfg.seed) if iters>0 else []
            patterns = self.patterns + auto_specs

            # config save
            env = {
                "python": platform.python_version(),
                "platform": platform.platform(),
            }
            with open(os.path.join(out_root, "config.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "run_id": run_id,
                    "run_config": asdict(cfg),
                    "video_meta": meta,
                    "class_map": cls_map,
                    "patterns": [asdict(p) for p in patterns],
                    "env": env,
                }, f, ensure_ascii=False, indent=2)

            # progress total
            total_frames_est = cfg.max_frames if cfg.max_frames>0 else int(meta.get("frames",0))
            total_frames_est = max(total_frames_est, 1)
            self.progress.set(phase="tracking", pattern_n=len(patterns),
                              global_total=len(patterns)*total_frames_est,
                              global_done=0)

            results: List[PatternResult] = []
            for pi, spec in enumerate(patterns, start=1):
                if self._stop.is_set():
                    break
                self.progress.set(pattern=spec.name, pattern_i=pi, message="start pattern")
                out_dir_pattern = os.path.join(out_root, "patterns", spec.name)
                pr = run_pattern_tracking(cfg, spec, class_filter, out_dir_pattern, self.progress, self._stop)
                results.append(pr)

                # update global done roughly (processed frames)
                self.progress.set(global_done=min(self.progress.get()["global_total"],
                                                 self.progress.get()["global_done"] + pr.summary.get("processed_frames",0)))

                # update ui
                self.after(0, lambda rr=results: self._render_table_and_yplot(rr, best_name=None))

            if self._stop.is_set():
                self.progress.set(phase="stopped", message="user stop")
                return

            # choose best by simple heuristic: total detections + top-y improvement bonus
            self.progress.set(phase="select_best", message="select best pattern")
            baseline = next((r for r in results if r.pattern_name=="baseline_none"), results[0])

            def score_pattern(r: PatternResult) -> float:
                # 上部改善を重視(上位3binに重み)
                by = pd.read_csv(baseline.ybins_path) if os.path.exists(baseline.ybins_path) else None
                ry = pd.read_csv(r.ybins_path) if os.path.exists(r.ybins_path) else None
                base = 0.0
                if by is not None and ry is not None and len(by)==len(ry):
                    topk = min(3, len(by))
                    base = float((ry.loc[:topk-1,"frame_hits"] - by.loc[:topk-1,"frame_hits"]).sum())
                return float(r.summary.get("detections",0)) + 5.0*base - 0.1*float(r.summary.get("tracks",0))

            best = max(results, key=score_pattern)
            best_name = best.pattern_name
            self.after(0, lambda rr=results, bn=best_name: self._render_table_and_yplot(rr, best_name=bn))

            # build stitched
            self.progress.set(phase="stitch", message="load all pattern CSVs")
            dfs = []
            for r in results:
                dfp = pd.read_csv(r.csv_path) if os.path.exists(r.csv_path) else pd.DataFrame()
                if len(dfp):
                    # chosen_pattern列は既に入っているが念のため
                    dfp["chosen_pattern"] = r.pattern_name
                    dfs.append(dfp)
            all_df = pd.concat(dfs, ignore_index=True) if len(dfs) else pd.DataFrame()

            self.progress.set(phase="stitch", message="stitch tracks + interpolate gaps")
            stitched_df = stitch_multi_object(
                all_df, meta=meta,
                max_gap=int(self.stitch_max_gap.get()),
                iou_thr_connect=float(self.stitch_iou_thr.get()),
                dist_thr=float(self.stitch_dist_thr.get()),
            )

            stitched_dir = os.path.join(out_root, "stitched")
            safe_makedirs(stitched_dir)
            stitched_csv = os.path.join(stitched_dir, "stitched.csv")
            stitched_df.to_csv(stitched_csv, index=False, encoding="utf-8-sig")

            # stitched overlay
            self.progress.set(phase="stitch", message="write stitched overlay.mp4")
            stitched_mp4 = os.path.join(stitched_dir, "stitched_overlay.mp4")
            write_stitched_overlay(cfg.video_path, meta, stitched_df, stitched_mp4, every_n=cfg.every_n)

            # stitched summary
            interp_cnt = int(stitched_df["is_interpolated"].sum()) if len(stitched_df) else 0
            stitched_summary = {
                "stitched_csv": stitched_csv,
                "stitched_overlay": stitched_mp4,
                "rows": int(len(stitched_df)),
                "tracks": int(stitched_df["stitched_track_id"].nunique()) if len(stitched_df) else 0,
                "interpolated_rows": interp_cnt,
            }
            with open(os.path.join(stitched_dir, "stitched_summary.json"), "w", encoding="utf-8") as f:
                json.dump(stitched_summary, f, ensure_ascii=False, indent=2)

            # bench summary
            self.progress.set(phase="finalize", message="write bench summaries")
            sum_rows = []
            for r in results:
                s = dict(r.summary)
                s["pattern"] = r.pattern_name
                s["csv"] = r.csv_path
                s["overlay"] = r.overlay_path
                s["y_bins_csv"] = r.ybins_path
                sum_rows.append(s)
            df_sum = pd.DataFrame(sum_rows)
            df_sum.to_csv(os.path.join(out_root, "bench_summary.csv"), index=False, encoding="utf-8-sig")
            with open(os.path.join(out_root, "bench_summary.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "run_id": run_id,
                    "best_pattern": best_name,
                    "stitched": stitched_summary,
                    "results": sum_rows
                }, f, ensure_ascii=False, indent=2)

            self.progress.set(phase="done", message=f"完了 best={best_name}")
        except Exception as e:
            self.progress.set(phase="error", message=str(e))
            messagebox.showerror("エラー", str(e))
        finally:
            self.run_btn.configure(state="normal")


if __name__ == "__main__":
    App().mainloop()