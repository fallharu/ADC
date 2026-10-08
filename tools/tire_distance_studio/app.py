# -*- coding: utf-8 -*-
"""Tire Distance Studio メインUI。

距離解析、手動／自動アノテーション、再学習、モデル説明を1画面へ統合します。
時間のかかる推論・学習はワーカースレッドで実行し、Tkの更新はイベントキュー経由で
必ずメインスレッドへ戻します。
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import os
import queue
import subprocess
import sys
import threading
import traceback
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def enable_windows_high_dpi() -> None:
    """Enable crisp Tk rendering on high-DPI Windows displays."""
    if sys.platform != "win32":
        return
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


enable_windows_high_dpi()


APP_DIR = Path(__file__).resolve().parent
# ローカルモジュールを、通常起動とテスト用動的importの両方で解決する。
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from studio_utils import AnalysisConfig, AutoLabelConfig, TrainingConfig, clean_path_text

# 実行に必要なエンジンとタイヤモデルはStudio内へ同梱する。
ENGINE_PATH = APP_DIR / "engine" / "tire_distance_engine.py"
STUDIO_MODEL_DIR = APP_DIR / "models"
OUTPUT_DIR = APP_DIR / "outputs"
DATASET_DIR = APP_DIR / "datasets" / "tire_training_dataset"
TRAINING_DIR = APP_DIR / "training"

TIRE_MODEL = STUDIO_MODEL_DIR / "best.pt"
# 大容量のベースモデルは配布しない。再学習を使う場合だけ利用者が配置・選択する。
BASE_MODEL = STUDIO_MODEL_DIR / "yolo26x.pt"

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
VIDEO_TYPES = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v"}

MODEL_GUIDE = """\
モデル選択の結論

1. 距離解析・自動アノテーション: best.pt（推奨・実質必須）
   このプロジェクト専用に学習された物体検出モデルです。
   クラスは 0=Tire、1=Number_plate、2=Bicycle_Tires の3種類です。
   距離計算エンジンは Tire / Bicycle_Tires をタイヤとして採用し、
   Number_plate は除外します。画面下中央からタイヤまで測るときは、
   まずこのモデルを選んでください。

2. 再学習のベースモデル: yolo26x.pt（推奨）
   COCO 80クラスの汎用検出モデルで、Tireという専用クラスはありません。
   そのまま距離解析に使うとタイヤ検出ができないため不適切です。
   一方、アノテーション済みタイヤデータから再学習する際の初期重みには
   使用できます。元エンジンは必要に応じYOLO26互換パッチを適用します。

3. yolo11x.pt / yolov8x.pt（比較用のベースモデル）
   どちらもCOCO 80クラスの汎用モデルです。car、bicycle、truck等は
   検出しますが、Tire専用クラスはありません。直接の距離解析用ではなく、
   再学習の比較実験用です。

主要パラメータ

conf:
  検出を採用する最低信頼度です。初期値0.10は見逃しを減らす設定です。
  誤検出が多ければ0.20～0.35へ上げ、見逃しが多ければ0.05～0.10へ
  下げます。自動アノテーション後は必ず目視確認してください。

imgsz:
  推論時の入力サイズです。640が速度と精度の標準値です。小さなタイヤが
  潰れる場合は960または1280を試せますが、GPUメモリと処理時間が増えます。

device:
  autoはCUDA GPUが使えればGPU、使えなければCPUです。GPUを固定するなら
  0、CPUを固定するならcpuを指定します。

frame step:
  動画で何フレームごとに推論するかです。1は全フレーム、30は約30fpsの
  動画なら約1秒ごとです。距離動画を滑らかに作る場合は1、学習画像の抽出
  なら15～60が目安です。

距離の定義

基準点は画像または動画フレームの (幅/2, 高さ) です。タイヤ側の基準点は
初期設定でbbox下端中央です。表示動画では画像下中央が赤点、タイヤbboxが
緑枠、選択点が青点、両点間が水色の線として描画されます。出力値は画像上
のユークリッド距離（px）で、実距離のメートル値ではありません。
"""


def import_engine():
    """既存の距離計算エンジンをファイル位置から安全に動的読込する。"""
    if not ENGINE_PATH.exists():
        raise FileNotFoundError(
            f"元の計算エンジンが見つかりません:\n{ENGINE_PATH}\n"
            "Studio内のengineフォルダが揃っているか確認してください。"
        )
    spec = importlib.util.spec_from_file_location("tire_distance_engine", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"計算エンジンを読み込めません: {ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def mib(path: Path) -> str:
    """ファイル容量をMiB表示へ変換し、存在しない場合は説明を返す。"""
    return f"{path.stat().st_size / 1024 / 1024:.1f} MiB" if path.exists() else "見つかりません"


def open_path(path: Path) -> None:
    """存在するファイルまたはフォルダをWindows標準アプリで開く。"""
    path = path.resolve()
    if path.is_file():
        os.startfile(str(path))
    elif path.is_dir():
        os.startfile(str(path))
    else:
        raise FileNotFoundError(path)


class StudioApp(tk.Tk):
    """距離解析から再学習までをまとめたTire Distance Studio本体。"""
    BG = "#f3f6fa"
    PANEL = "#ffffff"
    NAV = "#10243e"
    NAV_ACTIVE = "#1f6feb"
    TEXT = "#172033"
    MUTED = "#667085"
    GREEN = "#157347"
    RED = "#b42318"

    def __init__(self) -> None:
        """保存フォルダを準備し、全ページとイベント監視を初期化する。"""
        super().__init__()
        self.title("Tire Distance Studio")
        self.ui_zoom = 1.0
        self.base_tk_scaling = float(self.tk.call("tk", "scaling"))
        self._configure_display()
        self.configure(bg=self.BG)
        self.engine = None
        self.worker: Optional[threading.Thread] = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.pages: dict[str, ttk.Frame] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        self.current_page = "start"

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        DATASET_DIR.mkdir(parents=True, exist_ok=True)
        TRAINING_DIR.mkdir(parents=True, exist_ok=True)

        self._setup_style()
        self._build_shell()
        self._build_start_page()
        self._build_distance_page()
        self._build_annotation_page()
        self._build_training_page()
        self._build_model_page()
        self._build_log_page()
        self.show_page("start")
        self.after(100, self._poll_events)
        self.after(250, self.run_diagnostics)

    def _configure_display(self) -> None:
        """Size the window for the current monitor and install zoom shortcuts."""
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        # Tk scaling is about 4/3 at 100% Windows scaling. Convert it to
        # a monitor scale factor so a 4K/200% display gets a physically
        # comparable window instead of a tiny 1500px window.
        monitor_scale = max(1.0, self.base_tk_scaling / (96.0 / 72.0))
        width = max(1060, int(1240 * monitor_scale))
        height = max(700, int(820 * monitor_scale))
        width = min(width, int(screen_w * 0.94))
        height = min(height, int(screen_h * 0.90))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(1060, screen_w), min(700, screen_h))
        self.bind_all("<Control-plus>", lambda _event: self.change_ui_zoom(0.10))
        self.bind_all("<Control-equal>", lambda _event: self.change_ui_zoom(0.10))
        self.bind_all("<Control-minus>", lambda _event: self.change_ui_zoom(-0.10))
        self.bind_all("<Control-0>", lambda _event: self.reset_ui_zoom())

    def change_ui_zoom(self, delta: float) -> None:
        """UI倍率を80～150%の範囲で変更する。"""
        self.ui_zoom = max(0.80, min(1.50, round(self.ui_zoom + delta, 2)))
        self.tk.call("tk", "scaling", self.base_tk_scaling * self.ui_zoom)
        if hasattr(self, "zoom_var"):
            self.zoom_var.set(f"{int(self.ui_zoom * 100)}%")
        self.update_idletasks()

    def reset_ui_zoom(self) -> None:
        """UI倍率を起動時の100%へ戻す。"""
        self.ui_zoom = 1.0
        self.tk.call("tk", "scaling", self.base_tk_scaling)
        if hasattr(self, "zoom_var"):
            self.zoom_var.set("100%")
        self.update_idletasks()

    def _setup_style(self) -> None:
        """高DPI環境でも読みやすい共通色・フォント・余白を定義する。"""
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Yu Gothic UI", 10), background=self.BG, foreground=self.TEXT)
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT)
        style.configure("Panel.TLabel", background=self.PANEL, foreground=self.TEXT)
        style.configure("Title.TLabel", font=("Yu Gothic UI", 22, "bold"), background=self.BG)
        style.configure("Subtitle.TLabel", font=("Yu Gothic UI", 10), foreground=self.MUTED, background=self.BG)
        style.configure("Section.TLabel", font=("Yu Gothic UI", 13, "bold"), background=self.PANEL)
        style.configure("Hint.TLabel", font=("Yu Gothic UI", 9), foreground=self.MUTED, background=self.PANEL)
        style.configure("Primary.TButton", font=("Yu Gothic UI", 10, "bold"), padding=(14, 9))
        style.configure("TButton", padding=(10, 7))
        style.configure("TEntry", padding=6)
        style.configure("TCombobox", padding=5)
        style.configure("TLabelframe", background=self.PANEL, borderwidth=1, relief="solid")
        style.configure("TLabelframe.Label", background=self.PANEL, font=("Yu Gothic UI", 11, "bold"))

    def _build_shell(self) -> None:
        """左ナビゲーション、上部バー、ページ表示領域を構築する。"""
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        nav = tk.Frame(self, bg=self.NAV, width=225)
        nav.grid(row=0, column=0, sticky="ns")
        nav.grid_propagate(False)

        tk.Label(
            nav, text="TIRE DISTANCE", bg=self.NAV, fg="white",
            font=("Segoe UI", 15, "bold"), anchor="w"
        ).pack(fill="x", padx=20, pady=(24, 2))
        tk.Label(
            nav, text="STUDIO", bg=self.NAV, fg="#84b7ff",
            font=("Segoe UI", 10, "bold"), anchor="w"
        ).pack(fill="x", padx=20, pady=(0, 24))

        items = [
            ("start", "  はじめに"),
            ("distance", "  距離解析"),
            ("annotation", "  アノテーション"),
            ("training", "  再学習"),
            ("models", "  モデルガイド"),
            ("logs", "  ログ／診断"),
        ]
        for key, label in items:
            button = tk.Button(
                nav, text=label, command=lambda k=key: self.show_page(k),
                bg=self.NAV, fg="#d9e5f5", activebackground="#193b63",
                activeforeground="white", relief="flat", bd=0,
                font=("Yu Gothic UI", 10, "bold"), anchor="w",
                padx=18, pady=11, cursor="hand2",
            )
            button.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = button

        tk.Frame(nav, bg=self.NAV).pack(fill="both", expand=True)
        zoom = tk.Frame(nav, bg=self.NAV)
        zoom.pack(fill="x", padx=16, pady=(4, 8))
        tk.Label(zoom, text="表示倍率", bg=self.NAV, fg="#9fb3ca", font=("Yu Gothic UI", 8)).pack(anchor="w")
        controls = tk.Frame(zoom, bg=self.NAV)
        controls.pack(fill="x", pady=(3, 0))
        tk.Button(controls, text="−", command=lambda: self.change_ui_zoom(-0.10), bg="#193b63", fg="white", relief="flat", width=3).pack(side="left")
        self.zoom_var = tk.StringVar(value="100%")
        tk.Label(controls, textvariable=self.zoom_var, bg=self.NAV, fg="white", width=7).pack(side="left", padx=3)
        tk.Button(controls, text="＋", command=lambda: self.change_ui_zoom(0.10), bg="#193b63", fg="white", relief="flat", width=3).pack(side="left")
        tk.Button(controls, text="リセット", command=self.reset_ui_zoom, bg=self.NAV, fg="#c9d8e8", relief="flat").pack(side="right")
        self.engine_status_nav = tk.Label(
            nav, text="● エンジン確認中", bg=self.NAV, fg="#ffcc66",
            font=("Yu Gothic UI", 9), anchor="w", wraplength=185,
        )
        self.engine_status_nav.pack(fill="x", padx=20, pady=(8, 18))

        self.content = ttk.Frame(self, padding=(28, 22))
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    def _new_page(self, key: str) -> tuple[ttk.Frame, ttk.Frame]:
        """スクロール可能なページを作り、ヘッダーと本文を返す。"""
        page = ttk.Frame(self.content)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        self.pages[key] = page
        header = ttk.Frame(page)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        body = ttk.Frame(page)
        body.grid(row=1, column=0, sticky="nsew")
        return header, body

    def _page_header(self, header: ttk.Frame, title: str, subtitle: str) -> None:
        """ページ共通のタイトルと補足説明を配置する。"""
        ttk.Label(header, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text=subtitle, style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))

    def _panel(self, parent, padding=(18, 16)) -> ttk.Frame:
        """白背景の共通パネルを生成する。"""
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=padding, relief="solid", borderwidth=1)
        return frame

    def _build_start_page(self) -> None:
        """機能概要、推奨フロー、環境状態を表示する開始ページを作る。"""
        header, body = self._new_page("start")
        self._page_header(header, "はじめに", "最短3ステップで、画面下中央からタイヤまでの距離を可視化します。")
        body.grid_columnconfigure((0, 1, 2), weight=1, uniform="cards")
        body.grid_rowconfigure(1, weight=1)

        for col, (num, title, text) in enumerate([
            ("1", "入力を選択", "距離解析で画像または動画を選びます。"),
            ("2", "best.ptを確認", "タイヤ専用モデルが選ばれていることを確認します。"),
            ("3", "解析を開始", "CSVと、動画なら可視化MP4を出力します。"),
        ]):
            card = self._panel(body)
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 7, 0 if col == 2 else 7))
            ttk.Label(card, text=num, style="Section.TLabel", foreground=self.NAV_ACTIVE).pack(anchor="w")
            ttk.Label(card, text=title, style="Section.TLabel").pack(anchor="w", pady=(8, 4))
            ttk.Label(card, text=text, style="Hint.TLabel", wraplength=260).pack(anchor="w")

        guide = self._panel(body, (22, 20))
        guide.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(16, 0))
        guide.grid_columnconfigure(0, weight=2)
        guide.grid_columnconfigure(1, weight=1)
        ttk.Label(guide, text="おすすめの流れ", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        text = (
            "最初は短い動画で「最大処理フレーム数=30」を指定して試してください。\n"
            "結果が良ければ制限を0（全体）に戻します。誤検出が多い場合はconfを上げ、\n"
            "小さいタイヤを見逃す場合はimgszを960へ上げます。"
        )
        ttk.Label(guide, text=text, style="Panel.TLabel", justify="left").grid(
            row=1, column=0, sticky="nw", pady=(10, 16)
        )
        ttk.Button(
            guide, text="距離解析を開く →", style="Primary.TButton",
            command=lambda: self.show_page("distance")
        ).grid(row=2, column=0, sticky="w")

        status = ttk.LabelFrame(guide, text="環境ステータス", padding=(14, 12))
        status.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=(24, 0))
        self.start_engine_var = tk.StringVar(value="確認中…")
        self.start_model_var = tk.StringVar(value="確認中…")
        self.start_runtime_var = tk.StringVar(value=f"Python {sys.version_info.major}.{sys.version_info.minor}")
        for label, variable in [
            ("計算エンジン", self.start_engine_var),
            ("タイヤモデル", self.start_model_var),
            ("実行環境", self.start_runtime_var),
        ]:
            ttk.Label(status, text=label, style="Hint.TLabel").pack(anchor="w")
            ttk.Label(status, textvariable=variable, style="Panel.TLabel", wraplength=290).pack(
                anchor="w", pady=(1, 10)
            )

    def _labeled_entry(self, parent, row: int, label: str, variable, hint: str = "", browse=None) -> ttk.Entry:
        """ラベル、入力欄、補足、任意の参照ボタンを1行へ配置する。"""
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=6)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", padx=(12, 8), pady=6)
        if browse:
            ttk.Button(parent, text="参照", command=browse).grid(row=row, column=2, sticky="ew", pady=6)
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").grid(
                row=row + 1, column=1, columnspan=2, sticky="w", padx=(12, 0), pady=(0, 4)
            )
        return entry

    def _build_distance_page(self) -> None:
        """距離解析の入力・モデル・出力・推論設定画面を構築する。"""
        header, body = self._new_page("distance")
        self._page_header(header, "距離解析", "検出、距離計算、CSV保存、可視化動画の生成を一括実行します。")
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        form = self._panel(body)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        form.grid_columnconfigure(1, weight=1)

        self.source_var = tk.StringVar()
        self.model_var = tk.StringVar(value=str(TIRE_MODEL))
        self.csv_var = tk.StringVar(value=str(OUTPUT_DIR / "tire_distance_results.csv"))
        self.video_var = tk.StringVar(value=str(OUTPUT_DIR / "tire_distance_visualized.mp4"))
        self.device_var = tk.StringVar(value="auto")
        self.conf_var = tk.StringVar(value="0.10")
        self.imgsz_var = tk.StringVar(value="640")
        self.frame_step_var = tk.StringVar(value="1")
        self.max_frames_var = tk.StringVar(value="30")
        self.tire_point_var = tk.StringVar(value="bottom_center")
        self.nearest_var = tk.BooleanVar(value=False)

        ttk.Label(form, text="入出力", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        self._labeled_entry(form, 1, "画像／動画", self.source_var, browse=self._browse_source)
        self._labeled_entry(form, 2, "タイヤモデル", self.model_var, browse=self._browse_model)
        ttk.Label(
            form, text="推奨: best.pt（Tire / Number_plate / Bicycle_Tires）",
            style="Hint.TLabel", foreground=self.GREEN
        ).grid(row=3, column=1, columnspan=2, sticky="w", padx=(12, 0))
        self._labeled_entry(form, 4, "出力CSV", self.csv_var, browse=lambda: self._browse_save(self.csv_var, ".csv"))
        self._labeled_entry(form, 5, "可視化動画", self.video_var, browse=lambda: self._browse_save(self.video_var, ".mp4"))

        ttk.Separator(form).grid(row=6, column=0, columnspan=3, sticky="ew", pady=14)
        ttk.Label(form, text="推論設定", style="Section.TLabel").grid(row=7, column=0, columnspan=3, sticky="w")
        params = ttk.Frame(form, style="Panel.TFrame")
        params.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(10, 4))
        for col in range(5):
            params.grid_columnconfigure(col, weight=1)
        for col, (label, var, values) in enumerate([
            ("device", self.device_var, ("auto", "0", "cpu")),
            ("conf", self.conf_var, ("0.05", "0.10", "0.20", "0.30")),
            ("imgsz", self.imgsz_var, ("640", "960", "1280")),
            ("frame step", self.frame_step_var, ("1", "5", "15", "30")),
            ("最大フレーム", self.max_frames_var, ("0", "30", "100", "300")),
        ]):
            ttk.Label(params, text=label, style="Hint.TLabel").grid(row=0, column=col, sticky="w", padx=3)
            ttk.Combobox(params, textvariable=var, values=values, width=10).grid(
                row=1, column=col, sticky="ew", padx=3, pady=(3, 0)
            )

        options = ttk.Frame(form, style="Panel.TFrame")
        options.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(options, text="タイヤ側の基準点", style="Panel.TLabel").pack(side="left")
        ttk.Combobox(
            options, textvariable=self.tire_point_var,
            values=("center", "bottom_center", "bottom_left", "bottom_right", "nearest_bottom_corner", "nearest_any"),
            state="readonly", width=24
        ).pack(side="left", padx=10)
        ttk.Checkbutton(
            options, text="最も近いタイヤだけ保存", variable=self.nearest_var
        ).pack(side="left", padx=8)

        action = ttk.Frame(form, style="Panel.TFrame")
        action.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        self.analyze_button = ttk.Button(
            action, text="解析を開始", style="Primary.TButton", command=self.start_analysis
        )
        self.analyze_button.pack(side="left")
        ttk.Button(action, text="設定を標準に戻す", command=self._reset_distance_defaults).pack(side="left", padx=8)

        side = self._panel(body)
        side.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(4, weight=1)
        ttk.Label(side, text="実行状況", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.analysis_status_var = tk.StringVar(value="入力ファイルを選択してください。")
        ttk.Label(side, textvariable=self.analysis_status_var, style="Panel.TLabel", wraplength=340).grid(
            row=1, column=0, sticky="ew", pady=(10, 8)
        )
        self.analysis_progress = ttk.Progressbar(side, mode="indeterminate")
        self.analysis_progress.grid(row=2, column=0, sticky="ew")
        ttk.Label(
            side,
            text="画像入力ではCSVのみ生成します。動画入力ではCSVに加え、距離線を描いたMP4を生成します。",
            style="Hint.TLabel", wraplength=340, justify="left"
        ).grid(row=3, column=0, sticky="ew", pady=(10, 8))
        self.analysis_log = tk.Text(
            side, wrap="word", height=18, bg="#0e1726", fg="#d8e3f2",
            insertbackground="white", relief="flat", font=("Consolas", 9), padx=10, pady=10
        )
        self.analysis_log.grid(row=4, column=0, sticky="nsew")
        out_actions = ttk.Frame(side, style="Panel.TFrame")
        out_actions.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(out_actions, text="CSVを開く", command=lambda: self._safe_open(Path(clean_path_text(self.csv_var.get())))).pack(side="left")
        ttk.Button(out_actions, text="出力先を開く", command=lambda: self._safe_open(Path(clean_path_text(self.csv_var.get())).parent)).pack(
            side="left", padx=6
        )

    def _build_annotation_page(self) -> None:
        """手動編集と自動ラベル生成を選べるアノテーション画面を構築する。"""
        header, body = self._new_page("annotation")
        self._page_header(header, "アノテーション", "best.ptで自動ラベルを作り、必要に応じて元の矩形編集画面で修正します。")
        body.grid_columnconfigure((0, 1), weight=1, uniform="anno")
        body.grid_rowconfigure(0, weight=1)

        auto = self._panel(body)
        auto.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        auto.grid_columnconfigure(1, weight=1)
        ttk.Label(auto, text="自動アノテーション", style="Section.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(
            auto, text="タイヤ専用モデルの推論結果をYOLO形式（画像＋txt）で保存します。",
            style="Hint.TLabel"
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 10))

        self.anno_source_var = tk.StringVar()
        self.anno_model_var = tk.StringVar(value=str(TIRE_MODEL))
        self.dataset_var = tk.StringVar(value=str(DATASET_DIR))
        self.anno_conf_var = tk.StringVar(value="0.10")
        self.anno_device_var = tk.StringVar(value="auto")
        self.anno_imgsz_var = tk.StringVar(value="640")
        self.anno_step_var = tk.StringVar(value="30")
        self.anno_max_var = tk.StringVar(value="30")
        self.val_ratio_var = tk.StringVar(value="0.20")

        self._labeled_entry(auto, 2, "画像／動画／フォルダ", self.anno_source_var, browse=self._browse_anno_source)
        self._labeled_entry(auto, 3, "ラベル用モデル", self.anno_model_var, browse=self._browse_anno_model)
        self._labeled_entry(auto, 4, "データセット", self.dataset_var, browse=self._browse_dataset)
        p = ttk.Frame(auto, style="Panel.TFrame")
        p.grid(row=5, column=0, columnspan=3, sticky="ew", pady=10)
        for col, (label, var) in enumerate([
            ("conf", self.anno_conf_var), ("device", self.anno_device_var), ("imgsz", self.anno_imgsz_var),
            ("抽出間隔", self.anno_step_var), ("最大枚数", self.anno_max_var), ("val比率", self.val_ratio_var),
        ]):
            p.grid_columnconfigure(col, weight=1)
            ttk.Label(p, text=label, style="Hint.TLabel").grid(row=0, column=col, sticky="w", padx=3)
            ttk.Entry(p, textvariable=var, width=9).grid(row=1, column=col, sticky="ew", padx=3, pady=(3, 0))
        self.auto_label_button = ttk.Button(
            auto, text="自動ラベル作成", style="Primary.TButton", command=self.start_auto_label
        )
        self.auto_label_button.grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))

        manual = self._panel(body)
        manual.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(manual, text="目視確認と手動修正", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            manual,
            text=(
                "自動ラベルは学習前に必ず確認してください。\n\n"
                "元ツールの矩形編集画面では、画像上をドラッグしてタイヤbboxを追加し、"
                "直前の矩形削除、全削除、train/valへの保存ができます。また再学習機能も含まれます。"
            ),
            style="Panel.TLabel", justify="left", wraplength=430
        ).pack(anchor="w", pady=(12, 18))
        ttk.Button(
            manual, text="手動アノテーションエディタを開く", style="Primary.TButton",
            command=self.open_annotation_editor
        ).pack(anchor="w")
        ttk.Button(
            manual, text="旧ツールも開く", command=self.launch_original_tool
        ).pack(anchor="w", pady=(8, 0))
        ttk.Button(
            manual, text="データセットを開く",
            command=lambda: self._safe_open(Path(clean_path_text(self.dataset_var.get())))
        ).pack(anchor="w", pady=(8, 0))
        warning = ttk.LabelFrame(manual, text="重要", padding=(12, 10))
        warning.pack(fill="x", pady=(24, 0))
        ttk.Label(
            warning,
            text=(
                "自動ラベルは正解データではありません。誤検出、見逃し、タイヤ以外のbboxを"
                "修正せずに学習すると、モデル品質が低下します。val画像は学習用train画像と"
                "重複させず、評価専用に残してください。"
            ),
            style="Panel.TLabel", foreground=self.RED, wraplength=410, justify="left"
        ).pack(anchor="w")

    def _build_training_page(self) -> None:
        """YOLO再学習のデータ、モデル、出力、学習条件画面を構築する。"""
        header, body = self._new_page("training")
        self._page_header(header, "再学習", "確認済みYOLOデータセットから、既存モデルを壊さず別モデルとして学習します。")
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        form = self._panel(body)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        form.grid_columnconfigure(1, weight=1)
        self.train_dataset_var = tk.StringVar(value=str(DATASET_DIR))
        self.base_model_var = tk.StringVar(value=str(BASE_MODEL))
        self.train_output_var = tk.StringVar(value=str(TRAINING_DIR))
        self.run_name_var = tk.StringVar(value="tire_retrain")
        self.train_device_var = tk.StringVar(value="auto")
        self.epochs_var = tk.StringVar(value="50")
        self.train_imgsz_var = tk.StringVar(value="640")
        self.batch_var = tk.StringVar(value="8")
        self.export_var = tk.StringVar()

        ttk.Label(form, text="学習設定", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        self._labeled_entry(form, 1, "データセット", self.train_dataset_var, browse=self._browse_train_dataset)
        self._labeled_entry(form, 2, "ベースモデル", self.base_model_var, browse=self._browse_base_model)
        ttk.Label(
            form, text="推奨: yolo26x.pt。距離解析用のbest.ptとは役割が異なります。",
            style="Hint.TLabel", foreground=self.GREEN
        ).grid(row=3, column=1, columnspan=2, sticky="w", padx=(12, 0))
        self._labeled_entry(form, 4, "学習出力先", self.train_output_var, browse=self._browse_train_output)
        self._labeled_entry(form, 5, "run名", self.run_name_var)
        self._labeled_entry(form, 6, "完成モデルのコピー先（任意）", self.export_var, browse=self._browse_export_model)

        p = ttk.Frame(form, style="Panel.TFrame")
        p.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        for col, (label, var) in enumerate([
            ("device", self.train_device_var), ("epochs", self.epochs_var),
            ("imgsz", self.train_imgsz_var), ("batch", self.batch_var),
        ]):
            p.grid_columnconfigure(col, weight=1)
            ttk.Label(p, text=label, style="Hint.TLabel").grid(row=0, column=col, sticky="w", padx=4)
            ttk.Entry(p, textvariable=var).grid(row=1, column=col, sticky="ew", padx=4, pady=(3, 0))
        self.train_button = ttk.Button(
            form, text="再学習を開始", style="Primary.TButton", command=self.start_training
        )
        self.train_button.grid(row=8, column=0, columnspan=3, sticky="w", pady=(20, 0))

        info = self._panel(body)
        info.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(info, text="開始前チェック", style="Section.TLabel").pack(anchor="w")
        for text in [
            "trainとvalの両方に画像がある",
            "すべてのbboxを目視確認した",
            "Number_plateをタイヤとして囲っていない",
            "GPUメモリ不足時はbatchを下げる",
            "既存best.ptは直接上書きしない",
        ]:
            ttk.Label(info, text=f"✓  {text}", style="Panel.TLabel", wraplength=380).pack(
                anchor="w", pady=(10, 0)
            )
        ttk.Separator(info).pack(fill="x", pady=20)
        ttk.Label(info, text="目安", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            info,
            text=(
                "最初は epochs=20、imgsz=640、batch=4～8 で動作確認し、"
                "学習曲線とval結果を見て50～100 epochsへ増やします。"
                "CUDA out of memoryが出たらbatchを半分にしてください。"
            ),
            style="Panel.TLabel", justify="left", wraplength=390
        ).pack(anchor="w", pady=(10, 0))

    def _build_model_page(self) -> None:
        """モデルの役割と主要パラメータの詳細説明を表示する。"""
        header, body = self._new_page("models")
        self._page_header(header, "モデルガイド", "「検出に使うモデル」と「再学習の土台にするモデル」を混同しないことが重要です。")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        panel = self._panel(body, (6, 6))
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(0, weight=1)
        text = tk.Text(
            panel, wrap="word", bg="white", fg=self.TEXT, relief="flat",
            font=("Yu Gothic UI", 10), padx=20, pady=18, spacing1=2, spacing3=7
        )
        text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(panel, command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        text.insert("1.0", MODEL_GUIDE)
        text.configure(state="disabled")

    def _build_log_page(self) -> None:
        """診断・推論・学習の共通ログ画面を構築する。"""
        header, body = self._new_page("logs")
        self._page_header(header, "ログ／診断", "エンジン、依存ライブラリ、モデル配置を確認します。")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)
        actions = ttk.Frame(body)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(actions, text="診断を再実行", command=self.run_diagnostics).pack(side="left")
        ttk.Button(actions, text="ログをクリア", command=lambda: self.global_log.delete("1.0", "end")).pack(
            side="left", padx=6
        )
        ttk.Button(actions, text="アプリフォルダを開く", command=lambda: self._safe_open(APP_DIR)).pack(side="left")
        self.global_log = tk.Text(
            body, wrap="word", bg="#0e1726", fg="#d8e3f2",
            insertbackground="white", relief="flat", font=("Consolas", 10), padx=12, pady=12
        )
        self.global_log.grid(row=1, column=0, sticky="nsew")

    def show_page(self, key: str) -> None:
        """指定ページを前面へ出し、ナビゲーションの選択状態を更新する。"""
        self.current_page = key
        self.pages[key].tkraise()
        for name, button in self.nav_buttons.items():
            button.configure(bg=self.NAV_ACTIVE if name == key else self.NAV, fg="white" if name == key else "#d9e5f5")

    def _append(self, widget: tk.Text, message: str) -> None:
        """時刻付きメッセージを指定ログ欄の末尾へ追記する。"""
        stamp = datetime.now().strftime("%H:%M:%S")
        widget.insert("end", f"[{stamp}] {message}\n")
        widget.see("end")

    def log(self, message: str) -> None:
        """共通ログが構築済みならメッセージを記録する。"""
        if hasattr(self, "global_log"):
            self._append(self.global_log, message)

    def _ensure_engine(self):
        """距離計算エンジンを必要になった時点で1度だけ読み込む。"""
        if self.engine is None:
            self.engine = import_engine()
        return self.engine

    def _run_worker(self, name: str, job: Callable[[], object], done: Callable[[object], None]) -> None:
        """重い処理をデーモンスレッドで実行し、結果をイベントキューへ渡す。"""
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("処理中", "別の処理が実行中です。完了までお待ちください。")
            return

        def target() -> None:
            """ワーカー処理の成功結果または例外情報をUIイベントへ変換する。"""
            try:
                result = job()
                self.events.put(("done", (name, done, result)))
            except Exception as exc:
                self.events.put(("error", (name, exc, traceback.format_exc())))

        self.worker = threading.Thread(target=target, daemon=True, name=name)
        self.worker.start()

    def _progress(self, message: str) -> None:
        """任意スレッドから進捗メッセージをUIキューへ送る。"""
        self.events.put(("progress", message))

    def _poll_events(self) -> None:
        """ワーカーイベントをメインスレッドで取り出し、UIへ反映する。"""
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    message = str(payload)
                    self.log(message)
                    if self.current_page == "distance":
                        self._append(self.analysis_log, message)
                        self.analysis_status_var.set(message)
                elif kind == "done":
                    name, callback, result = payload
                    self._set_busy(False)
                    self.log(f"{name} 完了")
                    callback(result)
                elif kind == "error":
                    name, exc, trace = payload
                    self._set_busy(False)
                    self.log(f"{name} 失敗: {exc}\n{trace}")
                    messagebox.showerror(f"{name} エラー", str(exc))
                else:
                    self.log(f"未対応のワーカーイベントを無視: {kind}")
        except queue.Empty:
            pass
        except Exception as exc:
            # 完了通知側で例外が起きても、以後のイベント監視は必ず継続する。
            self._set_busy(False)
            self.log(f"UIイベント処理エラー: {exc}\n{traceback.format_exc()}")
            messagebox.showerror("UIイベント処理エラー", str(exc))
        finally:
            self.after(100, self._poll_events)

    def _set_busy(self, busy: bool) -> None:
        """多重実行を防ぐため主要ボタンと進捗表示を切り替える。"""
        state = "disabled" if busy else "normal"
        for button_name in ("analyze_button", "auto_label_button", "train_button"):
            if hasattr(self, button_name):
                getattr(self, button_name).configure(state=state)
        if busy:
            self.analysis_progress.start(10)
        else:
            self.analysis_progress.stop()

    def _browse_source(self) -> None:
        """解析入力を選び、元ファイル名から出力名も初期設定する。"""
        path = filedialog.askopenfilename(
            title="解析する画像または動画を選択",
            filetypes=(("画像・動画", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff *.mp4 *.avi *.mov *.mkv *.wmv *.m4v"), ("すべて", "*.*")),
        )
        if path:
            source = Path(path)
            self.source_var.set(path)
            self.csv_var.set(str(OUTPUT_DIR / f"{source.stem}_distance.csv"))
            self.video_var.set(str(OUTPUT_DIR / f"{source.stem}_visualized.mp4"))

    def _browse_model(self) -> None:
        """距離解析用モデルファイルを選択する。"""
        path = filedialog.askopenfilename(title="タイヤ検出モデル", initialdir=STUDIO_MODEL_DIR, filetypes=(("PyTorch", "*.pt"), ("すべて", "*.*")))
        if path:
            self.model_var.set(path)

    def _browse_save(self, variable: tk.StringVar, extension: str) -> None:
        """指定拡張子の保存先を選び、対象Tk変数へ設定する。"""
        path = filedialog.asksaveasfilename(
            title="出力先を選択", initialdir=OUTPUT_DIR,
            defaultextension=extension, filetypes=((extension.upper(), f"*{extension}"), ("すべて", "*.*"))
        )
        if path:
            variable.set(path)

    def _browse_anno_source(self) -> None:
        """アノテーション元のファイルまたはフォルダを選択する。"""
        path = filedialog.askopenfilename(title="アノテーション元", filetypes=(("画像・動画", "*.jpg *.jpeg *.png *.bmp *.webp *.mp4 *.avi *.mov *.mkv"), ("すべて", "*.*")))
        if not path:
            path = filedialog.askdirectory(title="または画像・動画フォルダを選択")
        if path:
            self.anno_source_var.set(path)

    def _browse_anno_model(self) -> None:
        """自動アノテーション用モデルを選択する。"""
        path = filedialog.askopenfilename(title="自動ラベル用モデル", initialdir=STUDIO_MODEL_DIR, filetypes=(("PyTorch", "*.pt"),))
        if path:
            self.anno_model_var.set(path)

    def _browse_dataset(self) -> None:
        """アノテーションデータセットの保存先を選択する。"""
        path = filedialog.askdirectory(title="YOLOデータセット", initialdir=APP_DIR)
        if path:
            self.dataset_var.set(path)

    def _browse_train_dataset(self) -> None:
        """再学習に使うYOLOデータセットを選択する。"""
        path = filedialog.askdirectory(title="学習データセット", initialdir=APP_DIR)
        if path:
            self.train_dataset_var.set(path)

    def _browse_base_model(self) -> None:
        """再学習の初期重みに使うベースモデルを選択する。"""
        path = filedialog.askopenfilename(title="ベースモデル", initialdir=STUDIO_MODEL_DIR, filetypes=(("PyTorch", "*.pt"),))
        if path:
            self.base_model_var.set(path)

    def _browse_train_output(self) -> None:
        """学習runを保存するルートフォルダを選択する。"""
        path = filedialog.askdirectory(title="学習出力先", initialdir=APP_DIR)
        if path:
            self.train_output_var.set(path)

    def _browse_export_model(self) -> None:
        """完成したbest.ptの任意コピー先を選択する。"""
        path = filedialog.asksaveasfilename(title="完成モデルのコピー先", initialdir=TRAINING_DIR, defaultextension=".pt", filetypes=(("PyTorch", "*.pt"),))
        if path:
            self.export_var.set(path)

    def _safe_open(self, path: Path) -> None:
        """対象を開き、失敗時は利用者向けダイアログを表示する。"""
        try:
            open_path(path)
        except Exception as exc:
            messagebox.showerror("開けません", str(exc))

    def _reset_distance_defaults(self) -> None:
        """距離解析設定を推奨初期値へ戻す。"""
        self.model_var.set(str(TIRE_MODEL))
        self.device_var.set("auto")
        self.conf_var.set("0.10")
        self.imgsz_var.set("640")
        self.frame_step_var.set("1")
        self.max_frames_var.set("30")
        self.tire_point_var.set("bottom_center")
        self.nearest_var.set(False)

    def _validate_tire_model(self, path: Path) -> None:
        """選択モデルのクラス構成を確認し、汎用COCOモデルの誤使用を防ぐ。"""
        if not path.is_file():
            raise FileNotFoundError(f"モデルが見つかりません: {path}")
        if path.resolve() == TIRE_MODEL.resolve():
            return

        names: list[str] = []
        inspection_error: Optional[Exception] = None
        try:
            from ultralytics import YOLO

            model = YOLO(str(path))
            raw_names = getattr(model, "names", {})
            values = raw_names.values() if isinstance(raw_names, dict) else raw_names
            names = [str(name) for name in values]
        except Exception as exc:
            inspection_error = exc

        # 別名で保存した再学習モデルでも、Tire系クラスがあれば利用可能。
        if any(any(token in name.lower() for token in ("tire", "tyre", "wheel")) for name in names):
            self.log(f"タイヤクラスを確認したモデルを使用: {path.name} / {names}")
            return

        details = ", ".join(names[:12]) if names else f"クラスを確認できません ({inspection_error})"
        answer = messagebox.askyesno(
            "モデル確認",
            f"{path.name} からTire系クラスを確認できません。\n"
            f"検出クラス: {details}\n\n"
            "COCO汎用モデルを直接使うとタイヤ検出が0件になる可能性があります。\n"
            "このモデルで続けますか？",
        )
        if not answer:
            raise RuntimeError("モデル選択を中止しました。")

    def _avoid_output_collision(self, config: AnalysisConfig) -> AnalysisConfig:
        """既存結果へのCSV追記を避け、日時付きの新しい出力名へ切り替える。"""
        csv_exists = config.csv_path.exists()
        video_exists = config.video_path is not None and config.video_path.exists()
        if not csv_exists and not video_exists:
            return config

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        counter = 1
        while True:
            token = stamp if counter == 1 else f"{stamp}_{counter}"
            csv_path = config.csv_path.with_name(f"{config.csv_path.stem}_{token}{config.csv_path.suffix}")
            video_path = config.video_path
            if video_path is not None:
                video_path = video_path.with_name(f"{video_path.stem}_{token}{video_path.suffix}")
            if not csv_path.exists() and (video_path is None or not video_path.exists()):
                break
            counter += 1
        self.csv_var.set(str(csv_path))
        if video_path is not None:
            self.video_var.set(str(video_path))
        self.log("同名出力があるため、日時付きの新規ファイル名へ切り替えました。")
        return replace(config, csv_path=csv_path, video_path=video_path)

    def start_analysis(self) -> None:
        """距離解析設定を確定し、推論をバックグラウンドで開始する。"""
        try:
            # Tk変数はメインスレッドで全て読み、不変configへコピーする。
            config = AnalysisConfig.build(
                source=self.source_var.get(),
                model=self.model_var.get(),
                csv_path=self.csv_var.get(),
                video_path=self.video_var.get(),
                tire_point=self.tire_point_var.get(),
                device=self.device_var.get(),
                confidence=self.conf_var.get(),
                image_size=self.imgsz_var.get(),
                frame_step=self.frame_step_var.get(),
                max_frames=self.max_frames_var.get(),
                nearest_only=self.nearest_var.get(),
            )
            self._validate_tire_model(config.model)
            config = self._avoid_output_collision(config)
            config.csv_path.parent.mkdir(parents=True, exist_ok=True)
            if config.video_path is not None:
                config.video_path.parent.mkdir(parents=True, exist_ok=True)
            engine = self._ensure_engine()
        except RuntimeError as exc:
            if str(exc) != "モデル選択を中止しました。":
                messagebox.showerror("入力エラー", str(exc))
            return
        except Exception as exc:
            messagebox.showerror("入力エラー", str(exc))
            return

        self.analysis_log.delete("1.0", "end")
        self.analysis_status_var.set("解析を準備しています…")
        self._set_busy(True)

        def job():
            """検証済み設定だけを使い、UI外のワーカースレッドで処理する。"""
            # ワーカースレッドではTk変数へアクセスしない。
            return engine.run_tire_model_gpu_to_csv(
                source_path=config.source,
                tire_point=config.tire_point,
                model_path=config.model,
                csv_path=config.csv_path,
                output_video_path=config.video_path,
                device=config.device,
                conf=config.confidence,
                imgsz=config.image_size,
                frame_step=config.frame_step,
                max_frames=config.max_frames,
                nearest_only=config.nearest_only,
                progress_cb=self._progress,
            )

        def done(count):
            """距離解析の完了件数と保存先をメインスレッドで通知する。"""
            self.analysis_status_var.set(f"完了: {count}件をCSVへ保存しました。")
            video_result = config.video_path if config.source.suffix.lower() in VIDEO_TYPES else "画像入力のため生成なし"
            messagebox.showinfo(
                "解析完了",
                f"保存件数: {count}\nCSV: {config.csv_path}\n可視化動画: {video_result}",
            )

        self._run_worker("距離解析", job, done)

    def start_auto_label(self) -> None:
        """自動ラベル設定を確定し、データセット生成を開始する。"""
        try:
            config = AutoLabelConfig.build(
                source=self.anno_source_var.get(),
                model=self.anno_model_var.get(),
                dataset=self.dataset_var.get(),
                device=self.anno_device_var.get(),
                confidence=self.anno_conf_var.get(),
                image_size=self.anno_imgsz_var.get(),
                frame_step=self.anno_step_var.get(),
                max_frames=self.anno_max_var.get(),
                validation_ratio=self.val_ratio_var.get(),
            )
            self._validate_tire_model(config.model)
            engine = self._ensure_engine()
        except RuntimeError as exc:
            if str(exc) != "モデル選択を中止しました。":
                messagebox.showerror("入力エラー", str(exc))
            return
        except Exception as exc:
            messagebox.showerror("入力エラー", str(exc))
            return

        if not messagebox.askyesno(
            "自動ラベル作成",
            "自動生成結果は目視確認が必要です。\n既存の同名画像・ラベルは上書きされる場合があります。続けますか？",
        ):
            return
        self._set_busy(True)

        def job():
            """検証済み設定だけを使い、UI外のワーカースレッドで処理する。"""
            return engine.auto_label_dataset_from_model(
                source_path=config.source,
                model_path=config.model,
                dataset_dir=config.dataset,
                conf=config.confidence,
                device=config.device,
                imgsz=config.image_size,
                frame_step=config.frame_step,
                max_frames=config.max_frames,
                val_ratio=config.validation_ratio,
                progress_cb=self._progress,
            )

        def done(result):
            """ワーカーの完了結果をメインスレッドで通知する。"""
            images, boxes = result
            messagebox.showinfo(
                "自動ラベル完了",
                f"画像: {images}\nbbox: {boxes}\n保存先: {config.dataset}",
            )

        self._run_worker("自動アノテーション", job, done)

    def start_training(self) -> None:
        """再学習設定を確定し、長時間処理の確認後に学習を開始する。"""
        try:
            config = TrainingConfig.build(
                dataset=self.train_dataset_var.get(),
                base_model=self.base_model_var.get(),
                output_root=self.train_output_var.get(),
                run_name=self.run_name_var.get(),
                device=self.train_device_var.get(),
                epochs=self.epochs_var.get(),
                image_size=self.train_imgsz_var.get(),
                batch=self.batch_var.get(),
                export_model=self.export_var.get(),
            )
            engine = self._ensure_engine()
        except Exception as exc:
            messagebox.showerror("入力エラー", str(exc))
            return

        if not messagebox.askyesno(
            "再学習を開始",
            f"長時間のGPU処理を開始します。\n\nベース: {config.base_model.name}\n"
            f"epochs: {config.epochs}\nimgsz: {config.image_size}\nbatch: {config.batch}\n\n続けますか？",
        ):
            return
        self._set_busy(True)

        def job():
            """検証済み設定だけを使い、UI外のワーカースレッドで処理する。"""
            return engine.run_full_retraining(
                dataset_dir=config.dataset,
                base_model_path=config.base_model,
                output_root=config.output_root,
                run_name=config.run_name,
                device=config.device,
                epochs=config.epochs,
                imgsz=config.image_size,
                batch=config.batch,
                replace_run=False,
                export_model_path=config.export_model,
                progress_cb=self._progress,
            )

        def done(result):
            """ワーカーの完了結果をメインスレッドで通知する。"""
            messagebox.showinfo("再学習完了", f"完成モデル:\n{result['final_model']}")

        self._run_worker("再学習", job, done)

    def open_annotation_editor(self) -> None:
        """現在の入力と保存先を引き継いで手動編集画面を開く。"""
        try:
            engine = self._ensure_engine()
            editor_path = APP_DIR / "annotation_editor.py"
            spec = importlib.util.spec_from_file_location("tire_annotation_editor", editor_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"アノテーションエディタを読み込めません: {editor_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            window = module.IntegratedAnnotationEditor(
                self,
                engine,
                dataset_dir=Path(clean_path_text(self.dataset_var.get()) or str(DATASET_DIR)),
                initial_source=clean_path_text(self.anno_source_var.get()),
            )
            window.transient(self)
            window.focus_set()
            self.log("手動アノテーションエディタを開きました。")
        except Exception as exc:
            messagebox.showerror("アノテーションエディタ", str(exc))

    def launch_original_tool(self) -> None:
        """互換性確認用に既存の元ツールを別プロセスで起動する。"""
        try:
            if not ENGINE_PATH.exists():
                raise FileNotFoundError(ENGINE_PATH)
            subprocess.Popen([sys.executable, str(ENGINE_PATH)], cwd=str(ENGINE_PATH.parent))
            self.log(f"元ツールを起動: {ENGINE_PATH}")
            messagebox.showinfo(
                "元ツールを起動しました",
                "元ツールで「アノテーション/再トレーニングを開く」を押してください。"
            )
        except Exception as exc:
            messagebox.showerror("起動エラー", str(exc))

    def run_diagnostics(self) -> None:
        """エンジン、モデル、主要Pythonパッケージの利用可否を診断する。"""
        checks = []
        checks.append(("計算エンジン", ENGINE_PATH.exists(), str(ENGINE_PATH)))
        checks.append(("タイヤモデル best.pt", TIRE_MODEL.exists(), f"{TIRE_MODEL} ({mib(TIRE_MODEL)})"))
        checks.append(("ベースモデル yolo26x.pt（再学習時のみ）", BASE_MODEL.exists(), f"{BASE_MODEL} ({mib(BASE_MODEL)})"))
        for package in ("cv2", "PIL", "ultralytics", "torch"):
            try:
                module = __import__(package)
                version = getattr(module, "__version__", "version不明")
                checks.append((package, True, str(version)))
            except Exception as exc:
                checks.append((package, False, str(exc)))

        ok = all(item[1] for item in checks[:2])
        self.engine_status_nav.configure(
            text="● エンジン利用可能" if ok else "● 設定を確認してください",
            fg="#69db9b" if ok else "#ff8a80"
        )
        self.start_engine_var.set("利用可能" if ENGINE_PATH.exists() else "見つかりません")
        self.start_model_var.set(f"best.pt / {mib(TIRE_MODEL)}")
        self.log("=== 診断結果 ===")
        for name, passed, detail in checks:
            self.log(f"{'OK' if passed else 'NG'}  {name}: {detail}")


def cli_check() -> int:
    """GUIを開かず必須ファイルとエンジンimportを検査する。"""
    required_checks = {
        "engine": ENGINE_PATH,
        "tire_model": TIRE_MODEL,
    }
    failed = False
    for name, path in required_checks.items():
        ok = path.exists()
        failed |= not ok
        print(f"[{'OK' if ok else 'NG'}] {name}: {path}")
    if BASE_MODEL.exists():
        print(f"[OK] base_model (optional): {BASE_MODEL}")
    else:
        print(f"[WARN] base_model (optional): 未配置。再学習時に選択してください: {BASE_MODEL}")
    try:
        engine = import_engine()
        print(f"[OK] engine import: {engine.__name__}")
    except Exception as exc:
        print(f"[NG] engine import: {exc}")
        failed = True
    return 1 if failed else 0


def main() -> int:
    """コマンドライン引数を処理し、診断またはGUIを開始する。"""
    parser = argparse.ArgumentParser(description="Tire Distance Studio")
    parser.add_argument("--check", action="store_true", help="GUIを開かず環境診断を実行")
    args = parser.parse_args()
    if args.check:
        return cli_check()
    StudioApp().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
