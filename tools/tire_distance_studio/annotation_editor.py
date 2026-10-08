# -*- coding: utf-8 -*-
"""Tire Distance Studio 統合手動アノテーションエディタ。

画像または動画からフレームを抽出し、タイヤを囲む矩形を元画像座標で保持して
YOLO形式（class_id, center_x, center_y, width, height）へ保存します。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from studio_utils import bounded_float, clean_path_text, positive_int, required_path


class IntegratedAnnotationEditor(tk.Toplevel):
    """画像・動画からYOLO形式のタイヤbboxを作成・修正する編集画面。

    ``samples`` のbboxは常に元画像座標で保持します。キャンバス表示時だけ
    ``display_scale`` と ``image_offset`` を適用するため、高DPI表示や
    ウィンドウサイズ変更後も保存座標は変化しません。
    """
    IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
    VIDEO_TYPES = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v"}

    def __init__(self, master: tk.Misc, engine, *, dataset_dir: Path, initial_source: str = "") -> None:
        """エディタを初期化し、入力済みパスがあれば遅延自動読込する。"""
        super().__init__(master)
        self.engine = engine
        self.title("手動タイヤアノテーション — Tire Distance Studio")
        self.geometry(self._window_geometry(master))
        self.minsize(980, 680)
        self.configure(bg="#f3f6fa")

        self.dataset_var = tk.StringVar(value=str(dataset_dir))
        self.source_var = tk.StringVar(value=initial_source)
        self.split_var = tk.StringVar(value="auto")
        self.val_ratio_var = tk.StringVar(value="0.20")
        self.frame_step_var = tk.StringVar(value="30")
        self.max_frames_var = tk.StringVar(value="30")
        self.sample_var = tk.StringVar(value="画像または動画を読み込んでください")
        self.status_var = tk.StringVar(value="左ドラッグでタイヤを囲みます。")

        self.samples: list[dict[str, object]] = []
        self.sample_index = 0
        self.display_scale = 1.0
        self.image_offset = (0.0, 0.0)
        self.tk_image: Optional[ImageTk.PhotoImage] = None
        self.drag_start: Optional[tuple[float, float]] = None
        self.drag_rect_id: Optional[int] = None
        self.loading = False
        self.render_job: Optional[str] = None
        self.autoload_job: Optional[str] = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Left>", lambda _event: self._previous())
        self.bind("<Right>", lambda _event: self._next())
        self.bind("<Control-s>", lambda _event: self._save_current())
        self.bind("<Control-Shift-S>", lambda _event: self._save_all())
        self.bind("<BackSpace>", lambda _event: self._undo())
        self.bind("<Delete>", lambda _event: self._undo())
        self.after(100, self._render)
        if clean_path_text(initial_source):
            self.autoload_job = self.after(350, self._autoload_source)

    def _autoload_source(self) -> None:
        """起動時の自動読込。手動読込との二重実行を防ぐためIDを先に破棄する。"""
        self.autoload_job = None
        self._load_source()

    def _schedule_render(self, _event=None) -> None:
        """連続するConfigureイベントをまとめ、最後の1回だけ再描画する。"""
        if self.render_job is not None:
            try:
                self.after_cancel(self.render_job)
            except tk.TclError:
                pass
        self.render_job = self.after(80, self._render)

    @staticmethod
    def _window_geometry(master: tk.Misc) -> str:
        """画面解像度とDPI倍率から、モニター内へ収まる初期サイズを返す。"""
        sw, sh = master.winfo_screenwidth(), master.winfo_screenheight()
        try:
            tk_scaling = float(master.tk.call("tk", "scaling"))
        except Exception:
            tk_scaling = 96.0 / 72.0
        monitor_scale = max(1.0, tk_scaling / (96.0 / 72.0))
        width = min(int(sw * 0.94), max(1100, int(1600 * monitor_scale)))
        height = min(int(sh * 0.90), max(720, int(960 * monitor_scale)))
        return f"{width}x{height}+{max(0, (sw-width)//2)}+{max(0, (sh-height)//2)}"

    def _set_initial_pane_position(self) -> None:
        """画像領域を広く確保するため、初回だけ左右ペインを7:3へ配置する。"""
        try:
            total_width = max(900, self.body.winfo_width())
            self.body.sashpos(0, int(total_width * 0.70))
        except (tk.TclError, AttributeError):
            pass

    def _build_ui(self) -> None:
        """入力、キャンバス、編集操作、ログからなる画面を構築する。"""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(14, 12))
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(4, weight=1)

        ttk.Label(top, text="入力", font=("Yu Gothic UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.source_var).grid(row=0, column=1, sticky="ew", padx=7)
        buttons = ttk.Frame(top)
        buttons.grid(row=0, column=2, sticky="w")
        ttk.Button(buttons, text="ファイル", command=self._browse_file).pack(side="left")
        ttk.Button(buttons, text="フォルダ", command=self._browse_folder).pack(side="left", padx=(4, 0))

        ttk.Label(top, text="抽出間隔").grid(row=0, column=3, sticky="e", padx=(14, 5))
        ttk.Entry(top, textvariable=self.frame_step_var, width=7).grid(row=0, column=4, sticky="w")
        ttk.Label(top, text="最大枚数").grid(row=0, column=4, sticky="w", padx=(75, 5))
        ttk.Entry(top, textvariable=self.max_frames_var, width=7).grid(row=0, column=4, sticky="w", padx=(145, 0))
        self.load_button = ttk.Button(top, text="読み込む", command=self._load_source)
        self.load_button.grid(row=0, column=5, padx=(10, 0))

        ttk.Label(top, text="保存データセット", font=("Yu Gothic UI", 10, "bold")).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(top, textvariable=self.dataset_var).grid(row=1, column=1, sticky="ew", padx=7, pady=(8, 0))
        ttk.Button(top, text="参照", command=self._browse_dataset).grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Label(top, text="保存先").grid(row=1, column=3, sticky="e", padx=(14, 5), pady=(8, 0))
        ttk.Combobox(top, textvariable=self.split_var, values=("auto", "train", "val"), state="readonly", width=8).grid(row=1, column=4, sticky="w", pady=(8, 0))
        ttk.Label(top, text="val比率").grid(row=1, column=4, sticky="w", padx=(92, 5), pady=(8, 0))
        ttk.Entry(top, textvariable=self.val_ratio_var, width=7).grid(row=1, column=4, sticky="w", padx=(148, 0), pady=(8, 0))

        self.body = ttk.PanedWindow(self, orient="horizontal")
        body = self.body
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 10))

        image_panel = ttk.Frame(body)
        image_panel.grid_columnconfigure(0, weight=1)
        image_panel.grid_rowconfigure(1, weight=1)
        body.add(image_panel, weight=5)
        ttk.Label(image_panel, textvariable=self.sample_var, font=("Yu Gothic UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.canvas = tk.Canvas(image_panel, bg="#111827", highlightthickness=1, highlightbackground="#334155", cursor="crosshair")
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Configure>", self._schedule_render)

        side = ttk.Frame(body, padding=(12, 0))
        side.grid_columnconfigure((0, 1), weight=1)
        side.grid_rowconfigure(10, weight=1)
        body.add(side, weight=1)

        ttk.Label(side, text="矩形編集", font=("Yu Gothic UI", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(side, text="タイヤ1個につき1つのbboxを、できるだけ隙間なく囲みます。", wraplength=330, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 14))
        ttk.Button(side, text="← 前へ", command=self._previous).grid(row=2, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(side, text="次へ →", command=self._next).grid(row=2, column=1, sticky="ew", padx=(4, 0))
        ttk.Button(side, text="直前の矩形を削除", command=self._undo).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(side, text="矩形をすべて削除", command=self._clear).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        ttk.Separator(side).grid(row=5, column=0, columnspan=2, sticky="ew", pady=14)
        ttk.Button(side, text="現在の画像を保存  Ctrl+S", command=self._save_current).grid(row=6, column=0, columnspan=2, sticky="ew")
        ttk.Button(side, text="全画像を保存", command=self._save_all).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(side, text="保存先を開く", command=self._open_dataset).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        help_box = ttk.LabelFrame(side, text="操作", padding=(9, 7))
        help_box.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(16, 8))
        ttk.Label(help_box, text="左ドラッグ: bbox追加\n← / →: 前後移動\nBackspace: 直前を削除\nCtrl+S: 現在を保存", justify="left").pack(anchor="w")

        self.log = tk.Text(side, height=10, wrap="word", bg="#0e1726", fg="#d8e3f2", relief="flat", font=("Consolas", 9), padx=8, pady=8)
        self.log.grid(row=10, column=0, columnspan=2, sticky="nsew")

        status = ttk.Frame(self, padding=(14, 7))
        status.grid(row=2, column=0, sticky="ew")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        ttk.Label(status, text="緑=bbox / 黄=作成中", foreground="#157347").pack(side="right")
        self.after(250, self._set_initial_pane_position)

    def _browse_file(self) -> None:
        """画像または動画ファイルを選択する。"""
        path = filedialog.askopenfilename(title="画像または動画", filetypes=(("画像・動画", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff *.mp4 *.avi *.mov *.mkv *.wmv *.m4v"), ("すべて", "*.*")))
        if path:
            self.source_var.set(path)

    def _browse_folder(self) -> None:
        """画像・動画を含む入力フォルダを選択する。"""
        path = filedialog.askdirectory(title="画像・動画フォルダ")
        if path:
            self.source_var.set(path)

    def _browse_dataset(self) -> None:
        """YOLOデータセットの保存先を選択する。"""
        path = filedialog.askdirectory(title="YOLOデータセット")
        if path:
            self.dataset_var.set(path)

    def _write_log(self, message: str) -> None:
        """エディタ内ログとステータスバーへ同じメッセージを表示する。"""
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.status_var.set(message)

    def _load_source(self) -> None:
        """入力画像／動画をメモリへ抽出し、既存YOLOラベルも同時に読む。"""
        if self.loading:
            return
        if self.autoload_job is not None:
            try:
                self.after_cancel(self.autoload_job)
            except tk.TclError:
                pass
            self.autoload_job = None
        if self._has_dirty() and not messagebox.askyesno(
            "未保存",
            "未保存の矩形があります。破棄して別の入力を読み込みますか？",
            parent=self,
        ):
            return

        self.loading = True
        self.load_button.configure(state="disabled")
        self.status_var.set("画像／動画を読み込んでいます…")
        self.update_idletasks()
        try:
            # 保存先は抽出前に検証する。空欄をPath(".")として扱わない。
            dataset = required_path(self.dataset_var.get(), "保存データセット")
            self.dataset_var.set(str(dataset))
            self.engine.ensure_yolo_dataset(dataset)

            import cv2

            source = Path(clean_path_text(self.source_var.get()))
            self.source_var.set(str(source))
            if not source.exists():
                raise FileNotFoundError(f"入力が見つかりません: {source}")
            step = positive_int(self.frame_step_var.get(), "抽出間隔")
            maximum = positive_int(self.max_frames_var.get(), "最大枚数")
            files = self.engine.iter_training_source_files(source)
            samples: list[dict[str, object]] = []

            # 最大枚数は各動画ではなく、選択した入力全体へ適用する。
            # 大量画像を一度に保持してメモリ不足になることを防ぐ。
            for current in files:
                if len(samples) >= maximum:
                    break
                suffix = current.suffix.lower()
                if suffix in self.IMAGE_TYPES:
                    image = cv2.imread(str(current))
                    if image is not None:
                        samples.append(self._sample(current.stem, image, current))
                    else:
                        self._write_log(f"画像を開けないためスキップ: {current.name}")
                elif suffix in self.VIDEO_TYPES:
                    cap = cv2.VideoCapture(str(current))
                    if not cap.isOpened():
                        self._write_log(f"動画を開けないためスキップ: {current.name}")
                        continue
                    frame_index = -1
                    try:
                        while len(samples) < maximum:
                            ok, frame = cap.read()
                            if not ok:
                                break
                            frame_index += 1
                            if frame_index % step:
                                continue
                            stem = f"{current.stem}_f{frame_index:06d}"
                            samples.append(self._sample(stem, frame.copy(), current, frame_index))
                    finally:
                        cap.release()

            if not samples:
                raise RuntimeError("アノテーション用画像を抽出できませんでした。")
            self.samples = samples
            self.sample_index = 0
            self._write_log(f"読み込み完了: {len(samples)}枚")
            self._render()
        except Exception as exc:
            self.status_var.set("読み込みに失敗しました。入力を確認してください。")
            messagebox.showerror("読み込みエラー", str(exc), parent=self)
        finally:
            self.loading = False
            self.load_button.configure(state="normal")

    def _sample(self, stem: str, image, source: Path, frame_index: Optional[int] = None) -> dict[str, object]:
        """画像、bbox、保存状態を1件の編集サンプルへまとめる。"""
        safe_stem = self.engine.sanitize_file_stem(stem)
        boxes, loaded_split = self._load_existing_labels(safe_stem, image.shape[1], image.shape[0], source)
        return {"stem": safe_stem, "image": image, "boxes": boxes, "dirty": False, "saved": bool(loaded_split), "loaded_split": loaded_split, "source": source, "frame_index": frame_index}

    def _load_existing_labels(self, stem: str, width: int, height: int, source: Path):
        """対応するYOLOラベルを探し、検証済みの元画像座標へ復元する。"""
        candidates: list[tuple[Path, str]] = []
        dataset = required_path(self.dataset_var.get(), "保存データセット")
        for split in ("train", "val"):
            candidates.append((dataset / "labels" / split / f"{stem}.txt", split))

        # 既存YOLOデータセット内の画像を直接開いた場合は、その隣のlabelsを優先する。
        if source.parent.name in {"train", "val"} and source.parent.parent.name == "images":
            root = source.parent.parent.parent
            candidates.insert(0, (root / "labels" / source.parent.name / f"{source.stem}.txt", source.parent.name))

        for label_path, split in candidates:
            if not label_path.exists():
                continue
            boxes = []
            skipped = 0
            for raw in label_path.read_text(encoding="utf-8-sig").splitlines():
                parts = raw.split()
                if len(parts) < 5:
                    skipped += 1
                    continue
                try:
                    _class_id, cx, cy, bw, bh = map(float, parts[:5])
                except ValueError:
                    skipped += 1
                    continue

                # NaN/Inf、負のサイズ、完全に画像外の矩形は編集対象にしない。
                values = (cx, cy, bw, bh)
                if not all(math.isfinite(value) for value in values) or bw <= 0 or bh <= 0:
                    skipped += 1
                    continue
                left = max(0.0, (cx - bw / 2) * width)
                top = max(0.0, (cy - bh / 2) * height)
                right = min(float(width), (cx + bw / 2) * width)
                bottom = min(float(height), (cy + bh / 2) * height)
                if right - left < 1 or bottom - top < 1:
                    skipped += 1
                    continue
                boxes.append(self.engine.TireRegion(left=left, top=top, right=right, bottom=bottom))
            if skipped:
                self._write_log(f"不正なラベルを{skipped}行スキップ: {label_path.name}")
            return boxes, split
        return [], None

    def _current(self):
        """現在位置を範囲内へ補正し、編集中サンプルを返す。"""
        if not self.samples:
            return None
        self.sample_index = max(0, min(self.sample_index, len(self.samples)-1))
        return self.samples[self.sample_index]

    def _render(self) -> None:
        """元画像の縦横比を保ってキャンバスへ描画し、bboxを重ねる。"""
        self.render_job = None
        sample = self._current()
        self.canvas.delete("all")
        if sample is None:
            return
        image = sample["image"]
        ih, iw = image.shape[:2]
        cw, ch = max(320, self.canvas.winfo_width()), max(240, self.canvas.winfo_height())
        self.display_scale = min(cw/iw, ch/ih)
        dw, dh = max(1, int(iw*self.display_scale)), max(1, int(ih*self.display_scale))
        ox, oy = (cw-dw)/2, (ch-dh)/2
        self.image_offset = (ox, oy)
        import cv2
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        if (dw, dh) != (iw, ih):
            pil = pil.resize((dw, dh), getattr(getattr(Image, "Resampling", Image), "LANCZOS"))
        self.tk_image = ImageTk.PhotoImage(pil)
        self.canvas.create_image(ox, oy, anchor="nw", image=self.tk_image)
        for index, region in enumerate(sample["boxes"], start=1):
            self._draw_region(region, index)
        dirty = " ●未保存" if sample["dirty"] else ""
        loaded = f" / {sample['loaded_split']}読込" if sample.get("loaded_split") else ""
        self.sample_var.set(f"{self.sample_index+1}/{len(self.samples)}  {sample['stem']}  bbox:{len(sample['boxes'])}{loaded}{dirty}")

    def _draw_region(self, region, index: int) -> None:
        """元画像座標のbboxを表示座標へ変換して描く。"""
        s = self.display_scale
        ox, oy = self.image_offset
        x1, y1, x2, y2 = region.left*s+ox, region.top*s+oy, region.right*s+ox, region.bottom*s+oy
        self.canvas.create_rectangle(x1, y1, x2, y2, outline="#00ff66", width=3)
        self.canvas.create_rectangle(x1, max(oy, y1-22), x1+64, y1, fill="#067a3c", outline="")
        self.canvas.create_text(x1+5, max(oy+10, y1-11), text=f"Tire {index}", fill="white", anchor="w", font=("Segoe UI", 9, "bold"))

    def _canvas_point(self, x: float, y: float):
        """キャンバス座標を元画像座標へ逆変換し、画像外ならNoneを返す。"""
        sample = self._current()
        if sample is None:
            return None
        image = sample["image"]
        ih, iw = image.shape[:2]
        ox, oy = self.image_offset
        px, py = (x-ox)/self.display_scale, (y-oy)/self.display_scale
        if px < 0 or py < 0 or px > iw or py > ih:
            return None
        return px, py

    def _press(self, event) -> None:
        """ドラッグ開始点を元画像座標で記録する。"""
        self.drag_start = self._canvas_point(event.x, event.y)

    def _drag(self, event) -> None:
        """作成途中のbboxを黄色い矩形でプレビューする。"""
        point = self._canvas_point(event.x, event.y)
        if self.drag_start is None or point is None:
            return
        if self.drag_rect_id is not None:
            self.canvas.delete(self.drag_rect_id)
        ox, oy = self.image_offset
        s = self.display_scale
        x1, y1 = self.drag_start
        x2, y2 = point
        self.drag_rect_id = self.canvas.create_rectangle(x1*s+ox, y1*s+oy, x2*s+ox, y2*s+oy, outline="#ffe600", width=3)

    def _release(self, event) -> None:
        """有効なドラッグをTireRegionへ変換し、未保存bboxとして追加する。"""
        sample = self._current()
        point = self._canvas_point(event.x, event.y)
        start = self.drag_start
        self.drag_start = None
        if self.drag_rect_id is not None:
            self.canvas.delete(self.drag_rect_id)
            self.drag_rect_id = None
        if sample is None or start is None or point is None:
            return
        x1, y1 = start
        x2, y2 = point
        region = self.engine.TireRegion(left=min(x1,x2), top=min(y1,y2), right=max(x1,x2), bottom=max(y1,y2))
        if region.right-region.left < 3 or region.bottom-region.top < 3:
            return
        sample["boxes"].append(region)
        sample["dirty"] = True
        self._render()

    def _previous(self) -> None:
        """1つ前のサンプルへ移動する。"""
        if self.samples:
            self.sample_index = max(0, self.sample_index-1)
            self._render()

    def _next(self) -> None:
        """1つ次のサンプルへ移動する。"""
        if self.samples:
            self.sample_index = min(len(self.samples)-1, self.sample_index+1)
            self._render()

    def _undo(self) -> None:
        """現在画像で最後に追加したbboxを1件削除する。"""
        sample = self._current()
        if sample and sample["boxes"]:
            sample["boxes"].pop()
            sample["dirty"] = True
            self._render()

    def _clear(self) -> None:
        """確認後、現在画像のbboxをすべて削除する。"""
        sample = self._current()
        if sample and sample["boxes"] and messagebox.askyesno("全削除", "現在の画像のbboxをすべて削除しますか？", parent=self):
            sample["boxes"].clear()
            sample["dirty"] = True
            self._render()

    def _split_for(self, index: int) -> str:
        """指定モードまたはval比率からtrain/valの保存先を決める。"""
        split = self.split_var.get()
        if split != "auto":
            return split
        ratio = bounded_float(self.val_ratio_var.get(), "val比率", minimum=0.0, maximum=0.99)
        return self.engine.split_for_auto_sample(saved_index=index, local_index=index, source_index=0, source_count=1, val_ratio=ratio)

    def _save_one(self, sample: dict[str, object], index: int):
        """1サンプルの画像とYOLOラベルを保存し、状態を保存済みにする。"""
        result = self.engine.save_yolo_annotation_sample(image_bgr=sample["image"], regions=sample["boxes"], dataset_dir=required_path(self.dataset_var.get(), "保存データセット"), split=self._split_for(index), sample_stem=str(sample["stem"]))
        sample["dirty"] = False
        sample["saved"] = True
        return result

    def _save_current(self) -> None:
        """現在のサンプルだけを保存する。"""
        sample = self._current()
        if sample is None:
            messagebox.showerror("保存", "画像を先に読み込んでください。", parent=self)
            return
        try:
            image_path, label_path, count = self._save_one(sample, self.sample_index)
            self._write_log(f"保存: {image_path.name} / bbox={count}")
            self._render()
        except Exception as exc:
            messagebox.showerror("保存エラー", str(exc), parent=self)

    def _save_all(self) -> None:
        """読み込んだ全サンプルをtrain/valへ保存する。"""
        if not self.samples:
            messagebox.showerror("保存", "画像を先に読み込んでください。", parent=self)
            return
        try:
            total = 0
            for index, sample in enumerate(self.samples):
                _image, _label, count = self._save_one(sample, index)
                total += count
            self._write_log(f"全保存完了: images={len(self.samples)}, bbox={total}")
            self._render()
            messagebox.showinfo("保存完了", f"画像: {len(self.samples)}\nbbox: {total}\n{self.dataset_var.get()}", parent=self)
        except Exception as exc:
            messagebox.showerror("保存エラー", str(exc), parent=self)

    def _open_dataset(self) -> None:
        """データセットフォルダを作成し、エクスプローラーで開く。"""
        path = required_path(self.dataset_var.get(), "保存データセット")
        try:
            path.mkdir(parents=True, exist_ok=True)
            import os
            os.startfile(str(path.resolve()))
        except Exception as exc:
            messagebox.showerror("開けません", str(exc), parent=self)

    def _has_dirty(self) -> bool:
        """未保存bboxを持つサンプルがあるかを返す。"""
        return any(bool(sample.get("dirty")) for sample in self.samples)

    def _on_close(self) -> None:
        """未保存内容がある場合だけ確認してから画面を閉じる。"""
        if self._has_dirty() and not messagebox.askyesno("未保存", "保存していないbboxがあります。閉じますか？", parent=self):
            return
        self.destroy()