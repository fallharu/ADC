
import json
import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pandas as pd


DEFAULT_BEST_CLASSES = {
    "0": "Tire",
    "1": "Number_plate",
    "2": "Bicycle_Tires",
}


def norm_class_id(x):
    """2 / 2.0 / '2' / '2.0' / ' 2 ' を全部 int(2) に寄せる。無理なら None。"""
    if pd.isna(x):
        return None
    try:
        # 文字列の余計な空白や全角空白を削る
        if isinstance(x, str):
            s = re.sub(r"\s+", "", x.strip())
            if s == "":
                return None
            x = s
        return int(float(x))
    except Exception:
        return None


def norm_model_name(x):
    if pd.isna(x):
        return ""
    return str(x).strip().lower()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CSV修正GUI（bestモデルのクラス名を復元）")
        self.geometry("920x620")

        self.csv_path = tk.StringVar()
        self.json_path = tk.StringVar()
        self.overwrite_nonempty = tk.BooleanVar(value=False)  # クラス名が埋まってる行も上書きするか
        self.save_mode = tk.StringVar(value="new")  # new / overwrite

        self.df = None
        self.best_map = DEFAULT_BEST_CLASSES.copy()

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True)

        # --- 入力CSV ---
        row1 = ttk.LabelFrame(frm, text="1) 入力CSV")
        row1.pack(fill="x", **pad)

        ttk.Entry(row1, textvariable=self.csv_path).pack(side="left", fill="x", expand=True, padx=8, pady=8)
        ttk.Button(row1, text="CSVを選択", command=self.pick_csv).pack(side="left", padx=8, pady=8)
        ttk.Button(row1, text="読み込み", command=self.load_csv).pack(side="left", padx=8, pady=8)

        # --- JSON ---
        row2 = ttk.LabelFrame(frm, text="2) best_model_classes.json（任意）")
        row2.pack(fill="x", **pad)

        ttk.Entry(row2, textvariable=self.json_path).pack(side="left", fill="x", expand=True, padx=8, pady=8)
        ttk.Button(row2, text="JSONを選択", command=self.pick_json).pack(side="left", padx=8, pady=8)
        ttk.Button(row2, text="JSON読み込み", command=self.load_json).pack(side="left", padx=8, pady=8)

        # --- オプション ---
        row3 = ttk.LabelFrame(frm, text="3) 修正オプション")
        row3.pack(fill="x", **pad)

        ttk.Checkbutton(
            row3,
            text="既にクラス名が埋まっているbest行も上書きする",
            variable=self.overwrite_nonempty,
        ).pack(anchor="w", padx=8, pady=6)

        save_box = ttk.Frame(row3)
        save_box.pack(fill="x", padx=8, pady=6)
        ttk.Label(save_box, text="保存方式: ").pack(side="left")
        ttk.Radiobutton(save_box, text="別名保存（推奨）", value="new", variable=self.save_mode).pack(side="left", padx=8)
        ttk.Radiobutton(save_box, text="上書き保存", value="overwrite", variable=self.save_mode).pack(side="left", padx=8)

        # --- 実行 ---
        row4 = ttk.Frame(frm)
        row4.pack(fill="x", **pad)

        ttk.Button(row4, text="4) 修正を実行（bestクラス名を埋める）", command=self.apply_fix).pack(side="left", padx=8, pady=8)
        ttk.Button(row4, text="5) 保存", command=self.save_csv).pack(side="left", padx=8, pady=8)

        # --- ログ ---
        row5 = ttk.LabelFrame(frm, text="ログ / 結果")
        row5.pack(fill="both", expand=True, **pad)

        self.log = tk.Text(row5, height=18, wrap="word")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

        self._log("起動しました。CSVを選択して「読み込み」してください。")
        self._log(f"内蔵bestクラス対応表: {self.best_map}")

    def _log(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def pick_csv(self):
        path = filedialog.askopenfilename(
            title="入力CSVを選択",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.csv_path.set(path)

    def pick_json(self):
        path = filedialog.askopenfilename(
            title="best_model_classes.json を選択（任意）",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.json_path.set(path)

    def load_json(self):
        path = self.json_path.get().strip()
        if not path:
            messagebox.showinfo("情報", "JSONが未指定なので内蔵マップを使います。")
            self.best_map = DEFAULT_BEST_CLASSES.copy()
            self._log(f"内蔵bestクラス対応表を使用: {self.best_map}")
            return

        if not os.path.exists(path):
            messagebox.showerror("エラー", f"JSONが見つかりません:\n{path}")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("JSONの中身がdictではありません。")

            # keys を str に寄せる
            self.best_map = {str(k): str(v) for k, v in data.items()}
            self._log(f"JSON読み込み成功: {path}")
            self._log(f"bestクラス対応表: {self.best_map}")
            messagebox.showinfo("OK", "JSONを読み込みました。")
        except Exception as e:
            messagebox.showerror("エラー", f"JSON読み込み失敗:\n{e}")

    def load_csv(self):
        path = self.csv_path.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror("エラー", "CSVファイルを選択してください。")
            return

        # よくあるパターン: utf-8-sig
        enc_try = ["utf-8-sig", "utf-8", "cp932"]
        last_err = None
        df = None
        for enc in enc_try:
            try:
                df = pd.read_csv(path, encoding=enc)
                self._log(f"CSV読み込み成功: {path} (encoding={enc})")
                break
            except Exception as e:
                last_err = e
        if df is None:
            messagebox.showerror("エラー", f"CSV読み込みに失敗:\n{last_err}")
            return

        # 必須列チェック
        required = ["モデル", "クラスID", "クラス名"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            messagebox.showerror(
                "エラー",
                f"必須列が見つかりません: {missing}\n"
                f"CSV列一覧: {list(df.columns)}",
            )
            return

        self.df = df
        self._log(f"行数: {len(df)} / 列数: {len(df.columns)}")
        self.summarize()

    def summarize(self):
        if self.df is None:
            return

        df = self.df
        model_norm = df["モデル"].map(norm_model_name)
        is_best = model_norm.eq("best")

        best_total = int(is_best.sum())
        best_empty = int((is_best & (df["クラス名"].isna() | (df["クラス名"].astype(str).str.strip() == ""))).sum())

        # class_id のユニーク（正規化前/後）
        raw_ids = sorted(set(df.loc[is_best, "クラスID"].dropna().astype(str).tolist()))
        norm_ids = sorted(set(norm_class_id(x) for x in df.loc[is_best, "クラスID"].tolist() if norm_class_id(x) is not None))

        self._log("---- 集計 ----")
        self._log(f"best行数: {best_total}")
        self._log(f"bestでクラス名が空/NULL: {best_empty}")
        self._log(f"bestのクラスID(生): {raw_ids[:30]}{' ...' if len(raw_ids) > 30 else ''}")
        self._log(f"bestのクラスID(正規化): {norm_ids}")
        self._log("--------------")

    def apply_fix(self):
        if self.df is None:
            messagebox.showerror("エラー", "先にCSVを読み込んでください。")
            return

        # JSONが指定されているなら読み込み推奨（押してなくても反映できるように自動ロード）
        if self.json_path.get().strip():
            self.load_json()

        df = self.df

        model_norm = df["モデル"].map(norm_model_name)
        is_best = model_norm.eq("best")

        # 対象条件: best
        target = is_best.copy()

        # クラス名が空の行だけ修正（上書き許可なら全部）
        if not self.overwrite_nonempty.get():
            empty_name = df["クラス名"].isna() | (df["クラス名"].astype(str).str.strip() == "")
            target = target & empty_name

        # class_id 正規化
        cid_norm_series = df.loc[target, "クラスID"].map(norm_class_id)

        # マッピング適用
        before_empty = int((is_best & (df["クラス名"].isna() | (df["クラス名"].astype(str).str.strip() == ""))).sum())

        mapped = cid_norm_series.map(lambda cid: self.best_map.get(str(cid)) if cid is not None else None)

        # 反映
        df.loc[target, "クラスID"] = cid_norm_series  # 見やすいように整数化して書き戻す
        df.loc[target, "クラス名"] = mapped

        after_empty = int((is_best & (df["クラス名"].isna() | (df["クラス名"].astype(str).str.strip() == ""))).sum())
        fixed = before_empty - after_empty

        self._log(f"[修正完了] bestクラス名を埋めた件数（空が減った分）: {fixed}")
        self.summarize()
        messagebox.showinfo("OK", f"修正しました。\n空欄が減った件数: {fixed}")

    def save_csv(self):
        if self.df is None:
            messagebox.showerror("エラー", "先にCSVを読み込んでください。")
            return

        in_path = self.csv_path.get().strip()
        if not in_path:
            messagebox.showerror("エラー", "入力CSVが未指定です。")
            return

        if self.save_mode.get() == "overwrite":
            out_path = in_path
        else:
            base, ext = os.path.splitext(in_path)
            out_path = base + "_fixed" + ext

        # 別名保存なら場所選択も可能にする
        if self.save_mode.get() != "overwrite":
            out_path = filedialog.asksaveasfilename(
                title="保存先を指定",
                initialfile=os.path.basename(out_path),
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            ) or ""
            if not out_path:
                return

        try:
            self.df.to_csv(out_path, index=False, encoding="utf-8-sig")
            self._log(f"保存しました: {out_path}")
            messagebox.showinfo("OK", f"保存しました:\n{out_path}")
        except Exception as e:
            messagebox.showerror("エラー", f"保存に失敗:\n{e}")


if __name__ == "__main__":
    # ttkテーマ（Windows標準でOK）
    app = App()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    app.mainloop()
