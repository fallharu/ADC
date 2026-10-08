import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import json
import os
import cv2
from PIL import Image, ImageTk, ImageDraw, ImageFont
import re
import shutil
import sys
import sqlite3
import subprocess

APP_DIR = Path(__file__).resolve().parent
sys.path.append(str(APP_DIR / "Source_code"))

try:
    from modules.db_manager import MAIN_DB_PATH, resolve_output_root
except ImportError:
    MAIN_DB_PATH = str(APP_DIR / "database" / "main.db")
    resolve_output_root = None

DEFAULT_INPUT_CSV = APP_DIR / "前回データ処理.csv"
DEFAULT_OVERRIDES_NAME = "video_calibration_overrides.json"
DEFAULT_SAVE_COUNTS_NAME = "video_save_counts.json"
GUI_CONFIG_PATH = APP_DIR / "gui_config.json"
FRAME_CACHE_LIMIT = 4


@dataclass
class VideoRecord:
    name: str
    display: str
    run_id: Optional[int] = None


def resolve_output_root_path() -> Path:
    if resolve_output_root is not None:
        try:
            return Path(resolve_output_root())
        except Exception:
            pass
    env = os.getenv("Opt_files")
    if env:
        return Path(env)
    return APP_DIR / "output"


def safe_int(value: object) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class CalibrationGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Calibration Override Studio")
        self.root.geometry("1280x820")
        self.root.minsize(1100, 700)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.app_dir = APP_DIR
        self.output_root = resolve_output_root_path()
        self.calib_dir = self.output_root / "calibrations"
        self.video_search_dirs = [
            self.app_dir / "uploads",
            self.output_root / "videos",
            self.app_dir,
        ]

        self.video_records: List[VideoRecord] = []
        self.filtered_records: List[VideoRecord] = []
        self.video_run_map: Dict[str, int] = {}
        self.calib_files: List[str] = []
        self.calib_files_set: set[str] = set()
        self.overrides: Dict[str, str] = {}
        self.save_counts: Dict[str, int] = {}

        self.current_record: Optional[VideoRecord] = None
        self.current_video_path: Optional[Path] = None
        self.current_default_profile: Optional[str] = None
        self.current_default_reason = ""
        self.csv_path: Optional[Path] = None
        self.csv_encoding: Optional[str] = None
        self.is_dirty = False

        self.frame_cache: Dict[str, Any] = {}
        self.frame_cache_order: List[str] = []

        self._ignore_calib_event = False
        self.last_video_name: Optional[str] = None

        self.load_config()
        self.data_dir = self.resolve_data_dir()
        self.overrides_path = self.data_dir / DEFAULT_OVERRIDES_NAME
        self.save_counts_path = self.data_dir / DEFAULT_SAVE_COUNTS_NAME
        self.load_overrides()
        self.load_save_counts()
        self.refresh_calibration_profiles()
        self.create_widgets()

        default_csv = self.csv_path or (DEFAULT_INPUT_CSV if DEFAULT_INPUT_CSV.exists() else None)
        self.load_csv(default_csv, notify=False)
        self.refresh_video_list()
        self.restore_last_selection()

    def apply_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.base_font = ("Yu Gothic UI", 10)
        self.header_font = ("Yu Gothic UI", 16, "bold")
        style.configure("Header.TLabel", font=self.header_font)
        style.configure("TLabel", font=self.base_font)
        style.configure("TButton", font=self.base_font)

    def create_widgets(self) -> None:
        self.apply_styles()

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(10, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="Calibration Override Studio", style="Header.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        self.csv_path_var = tk.StringVar()
        self.data_dir_var = tk.StringVar()
        self._update_csv_label()
        self._update_data_dir_label()
        ttk.Label(header, textvariable=self.csv_path_var).grid(
            row=1, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(header, textvariable=self.data_dir_var).grid(
            row=2, column=0, columnspan=2, sticky="w"
        )

        csv_actions = ttk.Frame(header)
        csv_actions.grid(row=0, column=2, rowspan=2, sticky="e")
        ttk.Button(csv_actions, text="CSV選択", command=self.select_csv).pack(side=tk.LEFT, padx=4)
        ttk.Button(csv_actions, text="再読み込み", command=self.reload_csv).pack(side=tk.LEFT, padx=4)
        ttk.Button(csv_actions, text="保存先変更", command=self.select_data_dir).pack(side=tk.LEFT, padx=4)

        main = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=1)
        main.add(right, weight=3)

        filter_frame = ttk.LabelFrame(left, text="フィルタ")
        filter_frame.pack(fill=tk.X, pady=(0, 6))
        filter_frame.columnconfigure(1, weight=1)

        ttk.Label(filter_frame, text="検索").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.filter_var = tk.StringVar()
        filter_entry = ttk.Entry(filter_frame, textvariable=self.filter_var)
        filter_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        filter_entry.bind("<Escape>", lambda _e: self.clear_filter())
        ttk.Button(filter_frame, text="クリア", command=self.clear_filter).grid(
            row=0, column=2, padx=6, pady=4
        )
        self.filter_var.trace_add("write", lambda *_: self.refresh_video_list())

        list_frame = ttk.LabelFrame(left, text="動画リスト")
        list_frame.pack(fill=tk.BOTH, expand=True)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.video_listbox = tk.Listbox(list_frame, activestyle="none", exportselection=False)
        self.video_listbox.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        self.video_listbox.configure(font=self.base_font)
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.video_listbox.yview)
        list_scroll.grid(row=0, column=1, sticky="ns", pady=6)
        self.video_listbox.config(yscrollcommand=list_scroll.set)
        self.video_listbox.bind("<<ListboxSelect>>", self.on_video_select)

        self.stats_var = tk.StringVar()
        ttk.Label(left, textvariable=self.stats_var).pack(anchor="w", padx=6, pady=(4, 6))

        ttk.Button(
            left, text="デフォルト割り当て状況を確認", command=self.auto_assign_defaults
        ).pack(fill=tk.X, padx=6, pady=(0, 8))

        process_frame = ttk.LabelFrame(left, text="CSV再出力")
        process_frame.pack(fill=tk.X, pady=(0, 6))
        process_frame.columnconfigure(1, weight=1)

        ttk.Label(process_frame, text="出力モード").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.mode_var = tk.StringVar(value="1")
        modes = [
            "1: フラグのみ (Flags Only)",
            "2: 全行出力 (All Rows)",
            "3: グループ全行 (Group All)",
        ]
        self.mode_combo = ttk.Combobox(
            process_frame, textvariable=self.mode_var, values=modes, state="readonly", width=28
        )
        self.mode_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        self.mode_combo.current(0)

        self.reprocess_button = ttk.Button(
            process_frame, text="reprocess_csv_cui.py 実行", command=self.run_reprocess
        )
        self.reprocess_button.grid(row=1, column=0, columnspan=2, padx=6, pady=(0, 6), sticky="ew")

        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        preview_frame = ttk.LabelFrame(right, text="プレビュー")
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.image_label = tk.Label(
            preview_frame,
            text="動画を選択してください",
            bg="#1f1f1f",
            fg="#f2f2f2",
        )
        self.image_label.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        details_frame = ttk.LabelFrame(right, text="詳細")
        details_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        details_frame.columnconfigure(1, weight=1)

        self.detail_video_var = tk.StringVar(value="-")
        self.detail_run_var = tk.StringVar(value="-")
        self.detail_path_var = tk.StringVar(value="-")
        self.detail_default_var = tk.StringVar(value="-")
        self.detail_override_var = tk.StringVar(value="-")
        self.detail_save_count_var = tk.StringVar(value="-")

        self._add_detail(details_frame, 0, "動画", self.detail_video_var)
        self._add_detail(details_frame, 1, "Run ID", self.detail_run_var)
        self._add_detail(details_frame, 2, "動画パス", self.detail_path_var)
        self._add_detail(details_frame, 3, "デフォルト", self.detail_default_var)
        self._add_detail(details_frame, 4, "上書き", self.detail_override_var)
        self._add_detail(details_frame, 5, "保存回数", self.detail_save_count_var)

        actions_frame = ttk.LabelFrame(right, text="キャリブレーション")
        actions_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        actions_frame.columnconfigure(1, weight=1)

        ttk.Label(actions_frame, text="プロファイル").grid(
            row=0, column=0, sticky="w", padx=6, pady=4
        )
        self.calib_var = tk.StringVar()
        self.calib_combo = ttk.Combobox(
            actions_frame, textvariable=self.calib_var, values=self.calib_files, state="readonly"
        )
        self.calib_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        self.calib_combo.bind("<<ComboboxSelected>>", self.on_calib_change)

        self.refresh_profiles_button = ttk.Button(
            actions_frame, text="更新", command=self.refresh_calibration_profiles
        )
        self.refresh_profiles_button.grid(row=0, column=2, padx=6, pady=4)

        buttons_frame = ttk.Frame(actions_frame)
        buttons_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=6, pady=(0, 6))
        for idx in range(4):
            buttons_frame.columnconfigure(idx, weight=1)

        self.save_button = ttk.Button(buttons_frame, text="保存", command=self.save_override)
        self.save_button.grid(row=0, column=0, sticky="ew", padx=2)
        self.save_next_button = ttk.Button(buttons_frame, text="保存→次へ", command=self.save_and_next)
        self.save_next_button.grid(row=0, column=1, sticky="ew", padx=2)
        self.clear_button = ttk.Button(buttons_frame, text="設定解除", command=self.clear_override)
        self.clear_button.grid(row=0, column=2, sticky="ew", padx=2)
        self.create_button = ttk.Button(buttons_frame, text="複製/作成", command=self.create_new_profile)
        self.create_button.grid(row=0, column=3, sticky="ew", padx=2)

        open_frame = ttk.Frame(actions_frame)
        open_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=6, pady=(0, 6))
        open_frame.columnconfigure(0, weight=1)
        open_frame.columnconfigure(1, weight=1)
        open_frame.columnconfigure(2, weight=1)

        self.open_video_button = ttk.Button(open_frame, text="動画を開く", command=self.open_video)
        self.open_video_button.grid(row=0, column=0, sticky="ew", padx=2)
        self.open_calib_button = ttk.Button(
            open_frame, text="プロファイルを開く", command=self.open_calibration
        )
        self.open_calib_button.grid(row=0, column=1, sticky="ew", padx=2)
        self.open_calib_dir_button = ttk.Button(
            open_frame, text="キャリブフォルダ", command=self.open_calibration_folder
        )
        self.open_calib_dir_button.grid(row=0, column=2, sticky="ew", padx=2)

        nav_frame = ttk.Frame(actions_frame)
        nav_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=6, pady=(0, 6))
        nav_frame.columnconfigure(0, weight=1)
        nav_frame.columnconfigure(1, weight=1)

        self.prev_button = ttk.Button(nav_frame, text="前へ", command=self.go_prev_video)
        self.prev_button.grid(row=0, column=0, sticky="ew", padx=2)
        self.next_button = ttk.Button(nav_frame, text="次へ", command=self.go_next_video)
        self.next_button.grid(row=0, column=1, sticky="ew", padx=2)

        status_frame = ttk.Frame(self.root, padding=(10, 6))
        status_frame.grid(row=2, column=0, sticky="ew")
        self.status_var = tk.StringVar(value="準備完了")
        self.status_label = tk.Label(status_frame, textvariable=self.status_var, anchor="w")
        self.status_label.pack(fill=tk.X)

        self.update_action_state()

    def _add_detail(self, frame: ttk.Frame, row: int, label: str, var: tk.StringVar) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=2)
        ttk.Label(frame, textvariable=var).grid(row=row, column=1, sticky="w", padx=6, pady=2)

    def _update_csv_label(self) -> None:
        if self.csv_path:
            self.csv_path_var.set(f"CSV: {self.csv_path}")
        else:
            self.csv_path_var.set("CSV: 未設定")

    def _update_data_dir_label(self) -> None:
        if hasattr(self, "data_dir") and self.data_dir:
            self.data_dir_var.set(f"保存先: {self.data_dir}")
        else:
            self.data_dir_var.set("保存先: 未設定")

    def set_status(self, text: str, level: str = "info") -> None:
        self.status_var.set(text)
        colors = {
            "info": "#334b6e",
            "success": "#107c10",
            "warning": "#9a6700",
            "error": "#a80000",
        }
        self.status_label.config(fg=colors.get(level, "#334b6e"))

    def load_config(self) -> None:
        self.config = {}
        if GUI_CONFIG_PATH.exists():
            try:
                with open(GUI_CONFIG_PATH, "r", encoding="utf-8") as f:
                    self.config = json.load(f) or {}
            except Exception:
                self.config = {}
        last_csv = self.config.get("last_csv")
        if last_csv:
            self.csv_path = Path(last_csv)
        self.last_video_name = self.config.get("last_video")

    def resolve_data_dir(self) -> Path:
        data_dir = self.config.get("data_dir")
        if data_dir:
            try:
                return Path(data_dir)
            except Exception:
                pass
        return APP_DIR

    def save_config(self) -> None:
        data = {
            "last_video": self.current_record.name if self.current_record else self.last_video_name,
            "last_csv": str(self.csv_path) if self.csv_path else "",
            "data_dir": str(self.data_dir) if hasattr(self, "data_dir") else "",
            "window": self.root.winfo_geometry(),
        }
        try:
            with open(GUI_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def load_overrides(self) -> None:
        self.overrides = {}
        if self.overrides_path.exists():
            try:
                with open(self.overrides_path, "r", encoding="utf-8") as f:
                    self.overrides = json.load(f) or {}
            except Exception:
                self.overrides = {}

    def load_save_counts(self) -> None:
        self.save_counts = {}
        if self.save_counts_path.exists():
            try:
                with open(self.save_counts_path, "r", encoding="utf-8") as f:
                    self.save_counts = json.load(f) or {}
            except Exception:
                self.save_counts = {}

    def refresh_calibration_profiles(self) -> None:
        if self.calib_dir.exists():
            files = sorted(self.calib_dir.glob("*.json"))
            self.calib_files = [p.stem for p in files]
        else:
            self.calib_files = []
        self.calib_files_set = set(self.calib_files)
        if hasattr(self, "calib_combo"):
            self.calib_combo["values"] = self.calib_files

    def load_csv(self, path: Optional[Path], notify: bool = True) -> None:
        self.video_records = []
        self.filtered_records = []
        self.video_run_map = {}
        if not path:
            if notify:
                messagebox.showwarning("CSV未設定", "入力CSVが設定されていません。")
            self.set_status("CSVが未設定です。", "warning")
            return
        if not path.exists():
            if notify:
                messagebox.showwarning("CSV未発見", f"CSVが見つかりません: {path}")
            self.set_status(f"CSVが見つかりません: {path}", "error")
            return
        try:
            df, encoding = self._read_csv(path)
        except Exception as e:
            if notify:
                messagebox.showerror("CSV読み込み失敗", f"読み込みに失敗しました: {e}")
            self.set_status("CSV読み込み失敗", "error")
            return

        video_col = self._find_column(
            df,
            ["動画ファイル", "動画名", "動画", "video", "Video", "video_filename", "filename"],
            ["動画", "video", "movie", "file", "filename"],
        )
        if not video_col:
            if notify:
                messagebox.showerror("CSV列不明", "動画ファイル列が見つかりませんでした。")
            self.set_status("動画ファイル列が見つかりません。", "error")
            return

        run_col = self._find_column(
            df,
            ["Run", "run", "run_id", "RunID", "Run Id", "run id"],
            ["run"],
        )

        names = df[video_col].dropna().astype(str).tolist()
        seen = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            run_id = None
            if run_col:
                row = df.loc[df[video_col] == name, run_col]
                if not row.empty:
                    run_id = safe_int(row.iloc[0])
            display = Path(name).name
            self.video_records.append(VideoRecord(name=name, display=display, run_id=run_id))
            if run_id is not None:
                self.video_run_map[name] = run_id

        self.csv_path = path
        csv_dir = self.csv_path.parent
        if csv_dir not in self.video_search_dirs:
            self.video_search_dirs.insert(0, csv_dir)
        self.csv_encoding = encoding
        self._update_csv_label()
        self.set_status(f"CSV読み込み完了 ({len(self.video_records)} 件, {encoding})", "success")

    def _read_csv(self, path: Path) -> Tuple[pd.DataFrame, str]:
        encodings = ["utf-8-sig", "cp932", "utf-8"]
        last_error = None
        for enc in encodings:
            try:
                df = pd.read_csv(path, encoding=enc)
                return df, enc
            except Exception as e:
                last_error = e
        raise last_error or ValueError("CSV読み込み失敗")

    def _find_column(self, df: pd.DataFrame, direct: List[str], partials: List[str]) -> Optional[str]:
        for name in direct:
            if name in df.columns:
                return name
        for col in df.columns:
            col_text = str(col)
            col_low = col_text.lower()
            for part in partials:
                if part.lower() in col_low:
                    return col
        return None

    def refresh_video_list(self, keep_selection: bool = True) -> None:
        current_name = self.current_record.name if self.current_record else None
        filter_text = (self.filter_var.get() or "").strip().lower()
        self.video_listbox.delete(0, tk.END)
        self.filtered_records = []

        for record in self.video_records:
            if not self._record_matches_filter(record, filter_text):
                continue
            display = self._format_video_display(record)
            index = self.video_listbox.size()
            self.video_listbox.insert(tk.END, display)
            if record.name in self.overrides:
                self.video_listbox.itemconfig(index, fg="#b00020")
            self.filtered_records.append(record)

        self.update_stats()
        if keep_selection and current_name:
            if not self.select_video_by_name(current_name):
                self.clear_selection()
        elif not self.filtered_records:
            self.clear_selection()

    def _record_matches_filter(self, record: VideoRecord, filter_text: str) -> bool:
        if not filter_text:
            return True
        if filter_text in record.display.lower():
            return True
        if filter_text in record.name.lower():
            return True
        if record.run_id is not None and filter_text in str(record.run_id):
            return True
        return False

    def _format_video_display(self, record: VideoRecord) -> str:
        label = record.display
        if record.run_id is not None:
            label = f"{label}  [Run {record.run_id}]"
        if record.name in self.overrides:
            label = f"{label}  [Override]"
        return label

    def update_stats(self) -> None:
        total = len(self.video_records)
        filtered = len(self.filtered_records)
        overrides = sum(1 for rec in self.video_records if rec.name in self.overrides)
        self.stats_var.set(f"動画: {filtered}/{total} | 上書き: {overrides}")

    def clear_selection(self) -> None:
        self.current_record = None
        self.current_video_path = None
        self.current_default_profile = None
        self.current_default_reason = ""
        self.is_dirty = False
        self.calib_var.set("")
        self.image_label.config(image="", text="動画を選択してください")
        self.detail_video_var.set("-")
        self.detail_run_var.set("-")
        self.detail_path_var.set("-")
        self.detail_default_var.set("-")
        self.detail_override_var.set("-")
        self.detail_save_count_var.set("-")
        self.update_action_state()

    def select_video_by_name(self, name: str) -> bool:
        for idx, record in enumerate(self.filtered_records):
            if record.name == name:
                self.video_listbox.selection_clear(0, tk.END)
                self.video_listbox.selection_set(idx)
                self.video_listbox.see(idx)
                self.on_video_select(None)
                return True
        return False

    def restore_last_selection(self) -> None:
        if self.last_video_name and self.select_video_by_name(self.last_video_name):
            return
        if self.filtered_records:
            self.video_listbox.selection_set(0)
            self.video_listbox.see(0)
            self.on_video_select(None)

    def update_action_state(self) -> None:
        enabled = self.current_record is not None
        state = tk.NORMAL if enabled else tk.DISABLED
        for btn in [
            self.save_button,
            self.save_next_button,
            self.clear_button,
            self.create_button,
            self.open_video_button,
            self.open_calib_button,
            self.open_calib_dir_button,
            self.prev_button,
            self.next_button,
        ]:
            btn.config(state=state)
        if enabled:
            self.calib_combo.config(state="readonly")
        else:
            self.calib_combo.config(state="disabled")

    def on_video_select(self, _event: Optional[tk.Event]) -> None:
        selection = self.video_listbox.curselection()
        if not selection:
            return
        record = self.filtered_records[selection[0]]
        self.current_record = record
        self.current_video_path = self.find_video_path(record.name)

        default_prof, reason = self.resolve_default_profile(record.name)
        self.current_default_profile = default_prof
        self.current_default_reason = reason

        override_prof = self.overrides.get(record.name)
        if override_prof:
            self._set_calib_var(override_prof)
        else:
            self._set_calib_var(default_prof or "")

        self.update_details()
        self.update_choice_state()
        self.update_image()
        self.update_action_state()
        self.last_video_name = record.name
        self.save_config()

    def _set_calib_var(self, value: str) -> None:
        self._ignore_calib_event = True
        self.calib_var.set(value)
        self._ignore_calib_event = False

    def on_calib_change(self, _event: Optional[tk.Event]) -> None:
        if self._ignore_calib_event:
            return
        self.update_choice_state()
        self.update_image()

    def update_choice_state(self) -> None:
        if not self.current_record:
            self.set_status("動画未選択", "info")
            return
        selected = self.calib_var.get().strip()
        override = self.overrides.get(self.current_record.name)
        self.is_dirty = False
        if override:
            if selected == override:
                self.set_status("上書き設定を適用中", "success")
            else:
                self.is_dirty = True
                self.set_status("上書き済み (未保存の変更あり)", "warning")
        else:
            if not selected:
                self.set_status("キャリブレーション未設定", "warning")
            elif selected == (self.current_default_profile or ""):
                self.set_status(self.current_default_reason or "デフォルト設定", "info")
            else:
                self.is_dirty = True
                self.set_status("未保存の選択があります", "warning")

    def update_details(self) -> None:
        if not self.current_record:
            return
        self.detail_video_var.set(self._ellipsize(self.current_record.display, 60))
        self.detail_run_var.set(str(self.current_record.run_id) if self.current_record.run_id else "-")
        path_text = str(self.current_video_path) if self.current_video_path else "-"
        self.detail_path_var.set(self._ellipsize(path_text, 90))
        self.detail_default_var.set(self.current_default_profile or "-")
        self.detail_override_var.set(self.overrides.get(self.current_record.name, "-"))
        self.detail_save_count_var.set(str(self.save_counts.get(self.current_record.name, 0)))

    def _ellipsize(self, text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return f"{text[: max_len - 12]}...{text[-9:]}"

    def get_db_profile(self, run_id: int) -> Optional[str]:
        if not os.path.exists(MAIN_DB_PATH):
            return None
        try:
            with sqlite3.connect(MAIN_DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT calibration_profile FROM ProcessLog WHERE run_id = ?", (run_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    return row[0]
        except Exception:
            pass
        return None

    def resolve_default_profile(self, video_name: str) -> Tuple[Optional[str], str]:
        run_id = self.video_run_map.get(video_name)
        if run_id:
            db_prof = self.get_db_profile(run_id)
            if db_prof and db_prof in self.calib_files_set:
                return db_prof, f"デフォルト (DB: Run {run_id})"

        v_date, v_fmt = self.extract_date(Path(video_name).name)
        if v_date:
            target_tags = {v_date}
            if v_fmt == "YYMMDD":
                target_tags.add("20" + v_date)
            elif v_fmt == "YYYYMMDD":
                target_tags.add(v_date[2:])
            for calib in self.calib_files:
                for tag in target_tags:
                    if tag in calib:
                        return calib, f"デフォルト (日付一致: {v_date})"

        return None, "デフォルト (設定なし)"

    def extract_date(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        match8 = re.search(r"(20[0-9]{2})(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])", text)
        if match8:
            return match8.group(0), "YYYYMMDD"
        match6 = re.search(r"(2[3-9]|[3-9][0-9])(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])", text)
        if match6:
            return match6.group(0), "YYMMDD"
        return None, None

    def find_video_path(self, filename: str) -> Optional[Path]:
        if not filename:
            return None
        direct = Path(filename)
        if direct.is_file():
            return direct

        name_only = direct.name
        for base in self.video_search_dirs:
            candidate = base / name_only
            if candidate.is_file():
                return candidate
            if base.name == "uploads":
                for root, _dirs, files in os.walk(base):
                    if name_only in files:
                        return Path(root) / name_only
        return None

    def get_frame(self, path: Path) -> Optional[Any]:
        key = str(path)
        if key in self.frame_cache:
            self.frame_cache_order.remove(key)
            self.frame_cache_order.append(key)
            return self.frame_cache[key].copy()

        cap = cv2.VideoCapture(key)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None

        self.frame_cache[key] = frame
        self.frame_cache_order.append(key)
        if len(self.frame_cache_order) > FRAME_CACHE_LIMIT:
            oldest = self.frame_cache_order.pop(0)
            self.frame_cache.pop(oldest, None)
        return frame.copy()

    def update_image(self) -> None:
        if not self.current_video_path or not self.current_video_path.exists():
            self.image_label.config(image="", text="動画ファイルが見つかりません")
            return

        frame = self.get_frame(self.current_video_path)
        if frame is None:
            self.image_label.config(image="", text="動画フレームの読み込みに失敗しました")
            return

        selected_calib = self.calib_var.get().strip()
        if selected_calib:
            calib_path = self.calib_dir / f"{selected_calib}.json"
            if calib_path.exists():
                try:
                    with open(calib_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self.draw_calibration(frame, data)
                except Exception:
                    pass

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = frame.shape[:2]

        self.root.update_idletasks()
        max_w = max(self.image_label.winfo_width(), 640)
        max_h = max(self.image_label.winfo_height(), 360)
        scale = min(max_w / w, max_h / h, 1.0)
        if scale < 1.0:
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

        img = Image.fromarray(frame)
        self.draw_overlay_text(img)

        self.tk_img = ImageTk.PhotoImage(img)
        self.image_label.config(image=self.tk_img, text="")

    def draw_overlay_text(self, pil_img: Image.Image) -> None:
        if not self.current_record:
            return
        lines = []
        selected = self.calib_var.get().strip()
        override = self.overrides.get(self.current_record.name)
        count = self.save_counts.get(self.current_record.name, 0)

        if override:
            lines.append(f"Override: {override}")
            if selected == override:
                lines.append("(適用中)")
            elif selected:
                lines.append(f"(選択中: {selected})")
        else:
            if selected:
                lines.append(f"Profile: {selected}")
                if selected == self.current_default_profile:
                    lines.append("(Default)")
            else:
                lines.append("未設定 (デフォルト)")
        
        # 保存回数表示
        if count > 0:
            lines.append(f"保存回数: {count}回")

        draw = ImageDraw.Draw(pil_img)
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except OSError:
            font = ImageFont.load_default()

        # シャドウ付きテキスト
        x, y = 10, 10
        for line in lines:
            # 黒縁
            for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                draw.text((x + dx, y + dy), line, font=font, fill="black")
            draw.text((x, y), line, font=font, fill="yellow")
            y += 24

        if override and selected == override:
             # 明示的なインジケータ
             draw.rectangle((10, y+10, 160, y+40), fill="green")
             draw.text((20, y+15), "保存設定読み込み済み", font=font, fill="white")


    def draw_calibration(self, frame: Any, data: dict) -> None:
        """Calibration data visualization on OpenCV frame"""
        # ポリゴンの描画
        lines = data.get("lines", {})
        if isinstance(lines, dict):
            for name, poly in lines.items():
                self._draw_poly(frame, poly, name)
        elif isinstance(lines, list):
             for poly in lines:
                 self._draw_poly(frame, poly, "line")
        
        # スケールの描画
        scale = data.get("scale")
        if isinstance(scale, dict) and "endpoints" in scale:
            pts = scale["endpoints"]
            if len(pts) == 2:
                cv2.line(frame, tuple(map(int, pts[0])), tuple(map(int, pts[1])), (0, 255, 255), 2)
                cv2.putText(frame, "Scale Ref", tuple(map(int, pts[0])), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

    def _draw_poly(self, frame: Any, poly: list, name: str) -> None:
        if not poly or len(poly) < 2:
             return
        
        pts = np.array(poly, np.int32)
        pts = pts.reshape((-1, 1, 2))
        
        color = (0, 255, 0)
        if "center" in name or "中央" in name:
            color = (0, 0, 255) # 赤
        elif "white" in name or "白" in name:
            color = (255, 255, 255) # 白
            
        cv2.polylines(frame, [pts], False, color, 2)

    def save_override(self) -> None:
        if not self.current_record:
            return
        selected = self.calib_var.get().strip()
        if not selected:
            messagebox.showwarning("警告", "キャリブレーションプロファイルが選択されていません。")
            return

        self.overrides[self.current_record.name] = selected
        
        # 保存回数インクリメント
        curr_count = self.save_counts.get(self.current_record.name, 0)
        self.save_counts[self.current_record.name] = curr_count + 1
        
        self.current_default_profile = selected
        self.current_default_reason = "上書き保存"
        
        self._save_overrides_to_file()
        self._save_counts_to_file()
        
        self.update_choice_state()
        self.update_details()
        self.update_image()
        self.set_status(f"設定を保存しました: {selected}", "success")

    def _save_overrides_to_file(self) -> None:
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.overrides_path, "w", encoding="utf-8") as f:
                json.dump(self.overrides, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("保存失敗", f"設定ファイルへの保存に失敗しました: {e}")

    def _save_counts_to_file(self) -> None:
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.save_counts_path, "w", encoding="utf-8") as f:
                json.dump(self.save_counts, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save counts: {e}")

    def clear_override(self) -> None:
        if not self.current_record:
            return
        if self.current_record.name in self.overrides:
            del self.overrides[self.current_record.name]
            self._save_overrides_to_file()
            self.set_status("設定を解除しました", "info")
            # リロード
            self.on_video_select(None)
            self.refresh_video_list(keep_selection=True)

    def save_and_next(self) -> None:
        self.save_override()
        self.go_next_video()

    def go_next_video(self) -> None:
        current_idx = self.video_listbox.curselection()
        if not current_idx:
            return
        next_idx = current_idx[0] + 1
        if next_idx < self.video_listbox.size():
            self.video_listbox.selection_clear(0, tk.END)
            self.video_listbox.selection_set(next_idx)
            self.video_listbox.see(next_idx)
            self.on_video_select(None)

    def go_prev_video(self) -> None:
        current_idx = self.video_listbox.curselection()
        if not current_idx:
            return
        prev_idx = current_idx[0] - 1
        if prev_idx >= 0:
            self.video_listbox.selection_clear(0, tk.END)
            self.video_listbox.selection_set(prev_idx)
            self.video_listbox.see(prev_idx)
            self.on_video_select(None)

    def select_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="前回のデータ処理CSVを選択",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialdir=str(self.csv_path.parent) if self.csv_path else str(APP_DIR)
        )
        if path:
            self.load_csv(Path(path))
            self.refresh_video_list()
            self.save_config()

    def select_data_dir(self) -> None:
        path = filedialog.askdirectory(
            title="保存先フォルダを選択",
            initialdir=str(self.data_dir) if hasattr(self, "data_dir") else str(APP_DIR)
        )
        if path:
            self.data_dir = Path(path)
            self.overrides_path = self.data_dir / DEFAULT_OVERRIDES_NAME
            self.save_counts_path = self.data_dir / DEFAULT_SAVE_COUNTS_NAME
            self.load_overrides()
            self.load_save_counts()
            self.save_config()
            self._update_data_dir_label()
            messagebox.showinfo("保存先変更", f"保存先を変更しました: {path}\n設定を再読み込みしました。")
            self.refresh_video_list()

    def reload_csv(self) -> None:
        if self.csv_path:
            self.load_csv(self.csv_path)
            self.refresh_video_list()
        else:
            self.select_csv()

    def run_reprocess(self) -> None:
        """reprocess_csv_cui.pyを実行する"""
        if self.is_dirty:
            if not messagebox.askyesno("未保存の変更", "未保存の変更があります。続行しますか？"):
                return

        mode = self.mode_var.get()[0] # "1" or "2" or "3"
        script_path = APP_DIR / "reprocess_csv_cui.py"
        
        if not script_path.exists():
            # Source_codeにあるかも？
            script_path = APP_DIR / "Source_code" / "reprocess_csv_cui.py"
        
        if not script_path.exists():
             messagebox.showerror("エラー", "reprocess_csv_cui.py が見つかりません。")
             return
             
        cmd = ["python", str(script_path), mode, "--no-pause"]
        
        try:
            # 別ウィンドウで実行
            subprocess.Popen(cmd, cwd=str(APP_DIR), creationflags=subprocess.CREATE_NEW_CONSOLE)
            messagebox.showinfo("実行開始", f"CSV再出力を開始しました。(Mode: {mode})")
        except Exception as e:
            messagebox.showerror("実行失敗", f"スクリプトの起動に失敗しました: {e}")

    def create_new_profile(self) -> None:
        """Create a new calibration profile by copying existing or empty"""
        if not self.calib_dir.exists():
            os.makedirs(self.calib_dir, exist_ok=True)
            
        base_name = self.calib_var.get().strip()
        new_name = simpledialog.askstring("新規作成", "新しいプロファイル名を入力してください:", parent=self.root)
        if not new_name:
            return
            
        src_path = self.calib_dir / f"{base_name}.json"
        dst_path = self.calib_dir / f"{new_name}.json"
        
        if dst_path.exists():
            messagebox.showerror("エラー", "同名のファイルが既に存在します。")
            return
            
        try:
            if src_path.exists():
                shutil.copy2(src_path, dst_path)
            else:
                # デフォルト作成
                with open(dst_path, "w", encoding="utf-8") as f:
                    json.dump({"scale": 0.005, "lines": {}}, f, indent=2)
            
            self.refresh_calibration_profiles()
            self._set_calib_var(new_name)
            self.on_calib_change(None)
            messagebox.showinfo("作成完了", f"新しいプロファイルを作成しました: {new_name}")
            
        except Exception as e:
            messagebox.showerror("エラー", f"作成に失敗しました: {e}")

    def open_video(self) -> None:
        if self.current_video_path and self.current_video_path.exists():
            os.startfile(self.current_video_path)
        else:
            messagebox.showwarning("ファイル不明", "動画ファイルが見つかりません。")

    def open_calibration(self) -> None:
        selected = self.calib_var.get().strip()
        if selected:
            path = self.calib_dir / f"{selected}.json"
            if path.exists():
                os.startfile(path)
            else:
                messagebox.showwarning("ファイル不明", f"プロファイルが見つかりません: {path}")

    def open_calibration_folder(self) -> None:
        if self.calib_dir.exists():
             os.startfile(self.calib_dir)
        else:
             os.makedirs(self.calib_dir, exist_ok=True)
             os.startfile(self.calib_dir)

    def clear_filter(self) -> None:
        self.filter_var.set("")
        self.refresh_video_list()

    def auto_assign_defaults(self) -> None:
        """全動画のデフォルト割り当て状況を確認し、レポートする"""
        report = []
        no_defaults = 0
        total = len(self.video_records)
        
        report.append(f"総動画数: {total}")
        report.append("-" * 30)
        
        for rec in self.video_records:
            prof, reason = self.resolve_default_profile(rec.name)
            if not prof:
                no_defaults += 1
                report.append(f"[×] {rec.display}: デフォルトなし")
            else:
                # report.append(f"[○] {rec.display}: {prof} ({reason})")
                pass
                
        report.append("-" * 30)
        if no_defaults == 0:
            report.append("すべての動画にデフォルトプロファイルが割り当て可能です。")
        else:
            report.append(f"{no_defaults} 件の動画にデフォルトプロファイルが見つかりませんでした。")
            
        # テキストファイルに出力して開く
        out_file = APP_DIR / "default_assignment_report.txt"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write("\n".join(report))
        os.startfile(out_file)

    def on_close(self) -> None:
        self.save_config()
        self.root.destroy()


def main():
    root = tk.Tk()
    # High DPI support for Windows
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
        
    app = CalibrationGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
