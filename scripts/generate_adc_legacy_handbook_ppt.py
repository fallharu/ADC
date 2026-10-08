"""ADC_08 旧版（Flask 版）の出力仕様と WEB UI 操作手順をスライド化する。

数値は db/my_app_data.db を read-only で開いて生成時に取得する。
描画ヘルパと配色は generate_adc_visualization_ppt から流用し、既存デッキと
見た目を揃える。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from generate_adc_visualization_ppt import (
    AMBER,
    BLUE,
    CYAN,
    FONT,
    FONT_NUM,
    GREEN,
    INK,
    LIGHT,
    LINE,
    MID,
    MUTED,
    NAVY,
    NAVY_2,
    ORANGE,
    OUT_DIR,
    PALE_BLUE,
    PALE_ORANGE,
    PALE_RED,
    PALE_TEAL,
    PURPLE,
    RED,
    SLIDE_H,
    SLIDE_W,
    TEAL,
    UNWIDENED,
    WHITE,
    WIDENED,
    add_circle,
    add_footer,
    add_line,
    add_multiline,
    add_pill,
    add_rect,
    add_text,
    add_title,
    color,
)


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "db" / "my_app_data.db"
OUT_PATH = OUT_DIR / "ADC_08_旧版ハンドブック_出力とWEBUI.pptx"

MONO = "Consolas"
SOURCE = "Source: Source_code/ の実装 と db/my_app_data.db（read-only 集計）"


# --------------------------------------------------------------------------
# データ取得
# --------------------------------------------------------------------------

def load_facts() -> dict:
    """デッキ内の実測値を DB から取得する。"""
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        def one(sql: str):
            return conn.execute(sql).fetchone()[0]

        tables = {
            name: one(f'SELECT COUNT(*) FROM "{name}"')
            for name in (
                "Detection",
                "DetectionRaw",
                "DetectionMetrics",
                "ProximityData",
                "ProcessLog",
                "Video",
                "TrafficCount",
                "Class",
                "ClassMaster",
                "OvertakeEvents",
                "ManualOvertakeEvents",
            )
        }
        status = dict(conn.execute("SELECT status, COUNT(*) FROM ProcessLog GROUP BY status"))
        classes = conn.execute(
            "SELECT class_name, COUNT(*) FROM Detection "
            "WHERE class_name IS NOT NULL GROUP BY class_name ORDER BY 2 DESC LIMIT 6"
        ).fetchall()
        detection_columns = len(conn.execute("PRAGMA table_info(Detection)").fetchall())
        manual_columns = len(conn.execute("PRAGMA table_info(ManualOvertakeEvents)").fetchall())
        sample = conn.execute(
            "SELECT run_id, frame_num, class_name, group_id, clearance_distance_cm, "
            "line_distance_m, lane_position_flag, travel_direction "
            "FROM Detection WHERE overtake = 1 AND clearance_distance_cm IS NOT NULL LIMIT 1"
        ).fetchone()
        oe_null = one(
            "SELECT COUNT(*) FROM OvertakeEvents WHERE clearance_distance_m IS NULL"
        )
        speed_zero = one(
            "SELECT COUNT(*) FROM Detection WHERE overtake = 1 AND speed_km_h = 0"
        )
    finally:
        conn.close()

    return {
        "tables": tables,
        "status": status,
        "classes": classes,
        "detection_columns": detection_columns,
        "manual_columns": manual_columns,
        "sample": sample,
        "overtake_events_null": oe_null,
        "overtake_speed_zero": speed_zero,
    }


# --------------------------------------------------------------------------
# 追加の描画ヘルパ
# --------------------------------------------------------------------------

def add_mono(slide, text, x, y, w, h, size=10.5, fill=INK, bold=False, align=PP_ALIGN.LEFT):
    return add_text(slide, text, x, y, w, h, size, fill, bold, align, font=MONO)


def add_mono_block(slide, lines, x, y, w, h, size=10, fill=INK, gap=2.5):
    """等幅フォントの複数行ブロック（ツリー・列名の提示用）。"""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = False
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    for i, line in enumerate(lines):
        text, tone = line if isinstance(line, tuple) else (line, fill)
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run()
        run.text = text
        run.font.name = MONO
        run.font.size = Pt(size)
        run.font.color.rgb = tone
        p.space_after = Pt(gap)
        p.space_before = Pt(0)
    return box


def add_table(
    slide,
    x,
    y,
    widths,
    header,
    rows,
    row_h=0.32,
    size=10,
    header_h=0.30,
    aligns=None,
    fonts=None,
    tones=None,
):
    """ヘッダ帯＋交互塗りの簡易テーブル。"""
    total_w = sum(widths)
    aligns = aligns or [PP_ALIGN.LEFT] * len(widths)
    fonts = fonts or [FONT] * len(widths)
    tones = tones or [INK] * len(widths)

    add_rect(slide, x, y, total_w, header_h, fill=NAVY, radius=False)
    cursor = x
    for w, label, align in zip(widths, header, aligns):
        add_text(slide, label, cursor + 0.12, y, w - 0.2, header_h, 9, WHITE, True, align)
        cursor += w

    cy = y + header_h
    for i, row in enumerate(rows):
        band = WHITE if i % 2 == 0 else LIGHT
        add_rect(slide, x, cy, total_w, row_h, fill=band, radius=False)
        cursor = x
        for w, value, align, font, tone in zip(widths, row, aligns, fonts, tones):
            add_text(
                slide, str(value), cursor + 0.12, cy, w - 0.2, row_h, size, tone, False, align, font=font
            )
            cursor += w
        cy += row_h
    add_line(slide, x, cy, x + total_w, cy + 0.012, LINE)
    return cy


def add_card(slide, x, y, w, h, title, lines, accent=BLUE, title_size=13, body_size=10.5):
    add_rect(slide, x, y, w, h, fill=WHITE, radius=True, line=LINE)
    add_rect(slide, x, y, 0.07, h, fill=accent, radius=False)
    add_text(slide, title, x + 0.24, y + 0.16, w - 0.42, 0.30, title_size, NAVY, True, valign=MSO_ANCHOR.TOP)
    add_multiline(slide, lines, x + 0.24, y + 0.58, w - 0.42, h - 0.72, body_size, MID, gap=5)


def add_step(slide, x, y, w, num, title, lines, accent=BLUE, h=None, body_size=10):
    add_circle(slide, x, y, 0.34, accent, num, WHITE, 12)
    add_text(slide, title, x + 0.46, y - 0.02, w - 0.46, 0.30, 12.5, NAVY, True, valign=MSO_ANCHOR.TOP)
    add_multiline(slide, lines, x + 0.46, y + 0.34, w - 0.46, (h or 1.0), body_size, MID, gap=3.5)


# --------------------------------------------------------------------------
# スライド
# --------------------------------------------------------------------------

def make_presentation(f: dict) -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    prs.core_properties.title = "ADC_08 旧版ハンドブック"
    prs.core_properties.subject = "旧版の出力データと WEB UI 操作手順"
    prs.core_properties.author = "ADC System"
    prs.core_properties.keywords = "ADC, 旧版, 出力仕様, WEB UI, 引き継ぎ"
    blank = prs.slide_layouts[6]

    t = f["tables"]
    st = f["status"]
    n = 0

    # ---------------------------------------------------------------- 01 表紙
    n += 1
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=NAVY, radius=False)
    add_rect(slide, 7.9, 0, SLIDE_W - 7.9, SLIDE_H, fill=NAVY_2, radius=False)
    for i, c in enumerate((AMBER, ORANGE, TEAL, BLUE)):
        add_rect(slide, 7.45 + i * 0.13, 0, 0.05, SLIDE_H, fill=c, radius=False)

    add_pill(slide, "ADC_08 / FLASK 版（旧版）", 0.72, 0.78, 3.05, AMBER, NAVY)
    add_text(slide, "旧版のアウトプットと", 0.72, 1.62, 6.6, 0.66, 30, color("D8E9F8"), True, valign=MSO_ANCHOR.TOP)
    add_text(slide, "WEB UI の使い方", 0.72, 2.22, 6.6, 0.86, 44, WHITE, True, valign=MSO_ANCHOR.TOP)
    add_text(
        slide,
        "どんなデータが出るのか / 画面をどう回すのか",
        0.74,
        3.28,
        6.5,
        0.42,
        16,
        CYAN,
        True,
    )
    add_line(slide, 0.74, 3.86, 3.1, 3.875, color("2C5170"))
    add_multiline(
        slide,
        [
            "実装（Source_code/routes・modules・templates）と",
            "稼働 DB の実測値から起こした引き継ぎ資料。",
            "新版 ADC Measurement 1.2 との差分検討の基準線として使う。",
        ],
        0.74,
        4.08,
        6.4,
        1.0,
        12,
        color("A9C4DC"),
        gap=4,
    )

    # 表紙の数値
    kpis = [
        (f"{t['Detection']:,}", "Detection 行"),
        (f"{f['detection_columns']}", "Detection 列"),
        (f"{t['ProcessLog']}", "Run"),
        (f"{t['Video']}", "動画"),
    ]
    kx = 0.74
    for value, label in kpis:
        add_rect(slide, kx, 5.42, 1.55, 0.94, fill=NAVY_2, radius=True, line=color("2C5170"))
        add_text(slide, value, kx, 5.54, 1.55, 0.44, 19, WHITE, True, PP_ALIGN.CENTER, font=FONT_NUM)
        add_text(slide, label, kx, 5.98, 1.55, 0.26, 9, color("9EB4C8"), False, PP_ALIGN.CENTER)
        kx += 1.66

    add_text(slide, "パイプラインの流れ", 8.34, 0.92, 4.4, 0.3, 11, CYAN, True)
    flow = [
        ("動画", AMBER),
        ("YOLO 推論", ORANGE),
        ("後処理 8 ステップ", TEAL),
        ("SQLite（Detection）", BLUE),
        ("CSV / Excel / 画像 / 動画", CYAN),
    ]
    fy = 1.44
    for i, (label, c) in enumerate(flow):
        add_rect(slide, 8.34, fy, 4.36, 0.62, fill=color("1B4468"), radius=True)
        add_rect(slide, 8.34, fy, 0.07, 0.62, fill=c, radius=False)
        add_text(slide, label, 8.62, fy, 3.9, 0.62, 13, WHITE, True)
        if i < len(flow) - 1:
            add_text(slide, "▼", 8.34, fy + 0.64, 4.36, 0.3, 9, color("6E90AC"), False, PP_ALIGN.CENTER)
        fy += 0.94
    add_text(slide, SOURCE, 0.72, 7.16, 9.0, 0.2, 8.2, color("7A93AB"), valign=MSO_ANCHOR.BOTTOM)

    # ---------------------------------------------------------------- 02 目次
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(slide, "このデッキの構成", "「何が出るか」を 3 章、「どう操作するか」を 2 章で扱う", "AGENDA")
    agenda = [
        ("01", "全体像", "動画 1 本が何に変わるか。推論＋後処理 8 ステップ", AMBER),
        ("02", "出力：データベース", "単一 SQLite に全指標を横持ち。実測行数と列の読み方", BLUE),
        ("03", "出力：ファイル", "Run ごとの CSV / Excel / 追い越し写真 / 注釈動画", TEAL),
        ("04", "WEB UI の画面構成", "サイドバー 3 グループと実ルートの対応", PURPLE),
        ("05", "標準の操作手順", "登録 → 推論 → 後処理 → 確認 → レビュー → 集計 → 出力", GREEN),
        ("06", "旧版の癖と注意", "データを読む前に確認すべき 7 点", RED),
    ]
    ay = 1.62
    for num, title, desc, accent in agenda:
        add_rect(slide, 0.58, ay, 12.2, 0.78, fill=WHITE, radius=True, line=LINE)
        add_rect(slide, 0.58, ay, 0.07, 0.78, fill=accent, radius=False)
        add_text(slide, num, 0.82, ay, 0.7, 0.78, 17, accent, True, font=FONT_NUM)
        add_text(slide, title, 1.56, ay, 3.2, 0.78, 14, NAVY, True)
        add_text(slide, desc, 4.76, ay, 7.9, 0.78, 11, MID)
        ay += 0.88
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 03 全体像
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(
        slide,
        "全体像 — 動画 1 本が何に変わるか",
        "計算結果はすべて Detection テーブルに書き戻される。画面も CSV も Excel も出どころは同じ 1 テーブル",
        "01 / OVERVIEW",
    )

    add_rect(slide, 0.58, 1.62, 12.2, 1.42, fill=PALE_ORANGE, radius=True, line=LINE)
    add_text(slide, "入力・推論", 0.78, 1.74, 2.0, 0.26, 10, ORANGE, True)
    io_steps = [
        ("動画", "uploads/ 配下の mp4"),
        ("車両検出モデル", "yolov8x / yolo26x 系"),
        ("タイヤ検出モデル", "best.pt 系"),
        ("Detection へ一括挿入", "1 検出 = 1 行"),
    ]
    ix = 0.78
    for i, (label, sub) in enumerate(io_steps):
        add_rect(slide, ix, 2.10, 2.72, 0.78, fill=WHITE, radius=True, line=LINE)
        add_text(slide, label, ix + 0.16, 2.18, 2.4, 0.30, 12, NAVY, True, valign=MSO_ANCHOR.TOP)
        add_text(slide, sub, ix + 0.16, 2.50, 2.4, 0.28, 9.5, MUTED, valign=MSO_ANCHOR.TOP)
        if i < len(io_steps) - 1:
            add_text(slide, "→", ix + 2.74, 2.10, 0.34, 0.78, 13, ORANGE, True, PP_ALIGN.CENTER)
        ix += 3.06

    add_rect(slide, 0.58, 3.22, 12.2, 2.28, fill=PALE_TEAL, radius=True, line=LINE)
    add_text(
        slide,
        "後処理パイプライン 8 ステップ　run_postprocess_pipeline_sync()",
        0.78,
        3.34,
        8.0,
        0.26,
        10,
        TEAL,
        True,
    )
    add_text(
        slide,
        "途中で失敗しても残りは続行し、成功ステップ名と失敗内容が Run ごとに記録される",
        0.78,
        3.60,
        11.8,
        0.24,
        9.5,
        MUTED,
    )
    post = [
        ("P1", "グループID", "track → group 集約"),
        ("P2", "運動学", "速度・加速度・進行方向"),
        ("P3", "白線距離", "左右白線までの水平距離"),
        ("P4", "追い越し", "判定 ＋ ±30 フレーム窓"),
        ("P5", "区間速度", "XY 区間速度"),
        ("P6", "接近／離隔", "approach / clearance"),
        ("P7", "車両間距離", "ProximityData を生成"),
        ("P8", "TTC", "衝突余裕時間"),
    ]
    px, py = 0.78, 3.94
    for i, (idx, label, sub) in enumerate(post):
        col = i % 4
        row = i // 4
        cx = px + col * 3.06
        cy = py + row * 0.76
        add_rect(slide, cx, cy, 2.86, 0.66, fill=WHITE, radius=True, line=LINE)
        add_rect(slide, cx, cy, 0.06, 0.66, fill=TEAL, radius=False)
        add_text(slide, idx, cx + 0.16, cy + 0.06, 0.42, 0.24, 9, TEAL, True, font=FONT_NUM)
        add_text(slide, label, cx + 0.62, cy + 0.04, 2.1, 0.26, 11.5, NAVY, True, valign=MSO_ANCHOR.TOP)
        add_text(slide, sub, cx + 0.62, cy + 0.32, 2.1, 0.26, 8.8, MUTED, valign=MSO_ANCHOR.TOP)

    add_rect(slide, 0.58, 5.68, 12.2, 1.16, fill=PALE_BLUE, radius=True, line=LINE)
    add_text(slide, "出力", 0.78, 5.80, 2.0, 0.26, 10, BLUE, True)
    outs = [
        ("データベース", "db/my_app_data.db", BLUE),
        ("CSV / Excel", "output/<run>/ と exports", TEAL),
        ("追い越し写真", "overtake_snapshots/*.png", AMBER),
        ("注釈動画", "annotated_run_<id>.mp4", RED),
    ]
    ox = 0.78
    for label, sub, c in outs:
        add_rect(slide, ox, 6.08, 2.86, 0.62, fill=WHITE, radius=True, line=LINE)
        add_rect(slide, ox, 6.08, 0.06, 0.62, fill=c, radius=False)
        add_text(slide, label, ox + 0.20, 6.10, 2.6, 0.28, 11.5, NAVY, True, valign=MSO_ANCHOR.TOP)
        add_mono(slide, sub, ox + 0.20, 6.38, 2.6, 0.24, 8.5, MUTED)
        ox += 3.06
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 04 DB 実測
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(
        slide,
        "出力その 1 — データベース",
        f"一次出力はすべて単一の SQLite に入る。以下は稼働 DB の実測行数",
        "02 / DATABASE",
    )

    kpi_defs = [
        (f"{t['Detection']:,}", "Detection 行", BLUE),
        (f"{f['detection_columns']} 列", "1 行が持つ指標数", TEAL),
        (f"{t['ProcessLog']}", f"Run（completed {st.get('completed', 0)}）", GREEN),
        (f"{t['OvertakeEvents']}", "自動判定の追い越し", AMBER),
    ]
    kx = 0.58
    for value, label, accent in kpi_defs:
        add_rect(slide, kx, 1.60, 2.96, 1.02, fill=WHITE, radius=True, line=LINE)
        add_rect(slide, kx, 1.60, 0.07, 1.02, fill=accent, radius=False)
        add_text(slide, value, kx + 0.24, 1.70, 2.6, 0.50, 24, NAVY, True, font=FONT_NUM)
        add_text(slide, label, kx + 0.24, 2.20, 2.6, 0.28, 10, MID, True)
        kx += 3.08

    rows = [
        ("Detection", f"{t['Detection']:,}", "1 検出 / 1 フレーム", "主テーブル。座標・速度・距離・フラグを横持ち"),
        ("DetectionRaw", f"{t['DetectionRaw']:,}", "同上", "正規化スキーマ移行後の生値（bbox・信頼度）"),
        ("DetectionMetrics", f"{t['DetectionMetrics']:,}", "同上", "同じく計算値側の分離テーブル"),
        ("ProximityData", f"{t['ProximityData']:,}", "1 ペア / 1 フレーム", "車両間の直線・横・縦距離"),
        ("ProcessLog", f"{t['ProcessLog']:,}", "1 Run", f"実行履歴。completed {st.get('completed', 0)} / error {st.get('error', 0)} / processing {st.get('processing', 0)}"),
        ("Video", f"{t['Video']:,}", "1 動画", "FPS・尺・撮影地点・道路種別・収集年"),
        ("TrafficCount", f"{t['TrafficCount']:,}", "1 ライン / 方向", "通過台数カウント"),
        ("Class / ClassMaster", f"{t['Class']} / {t['ClassMaster']}", "クラス", "YOLO クラス ID と名称の対応"),
        ("OvertakeEvents", f"{t['OvertakeEvents']:,}", "1 追い越し", "自動判定された追い越しイベント"),
        ("ManualOvertakeEvents", f"{t['ManualOvertakeEvents']:,}", "1 追い越し", f"手動判定画面で確定させたイベント（{f['manual_columns']} 列）"),
    ]
    add_table(
        slide,
        0.58,
        2.86,
        [2.5, 1.5, 2.2, 6.0],
        ["テーブル", "行数", "粒度", "役割"],
        rows,
        row_h=0.345,
        size=10,
        aligns=[PP_ALIGN.LEFT, PP_ALIGN.RIGHT, PP_ALIGN.LEFT, PP_ALIGN.LEFT],
        fonts=[MONO, FONT_NUM, FONT, FONT],
        tones=[TEAL, NAVY, MID, MID],
    )
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 05 1行のイメージ
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(
        slide,
        "Detection 1 行のイメージ",
        "1 行 =「あるフレームの、ある 1 オブジェクト」。そこに周辺の解析結果がすべて横持ちで貼り付く",
        "02 / DATABASE",
    )

    sample = f["sample"]
    if sample:
        run_id, frame_num, class_name, group_id, clearance_cm, line_m, lane_flag, direction = sample
    else:  # データが無い環境向けのフォールバック
        run_id, frame_num, class_name, group_id = 100350, 1157, "car", 18
        clearance_cm, line_m, lane_flag, direction = 195.2, 0.79, "+", "B"

    add_pill(slide, "追い越し成立フレーム（overtake = 1）の実データ", 0.58, 1.60, 4.4, AMBER, NAVY, 10)

    fields = [
        ("run_id", f"{run_id}", "実行 ID", MID),
        ("frame_num", f"{frame_num}", "フレーム番号", MID),
        ("class_name", f"{class_name}", "検出クラス", MID),
        ("group_id", f"{group_id}", "追い越した側", MID),
        ("clearance_distance_cm", f"{clearance_cm:.1f}", "離隔距離 cm", AMBER),
        ("line_distance_m", f"{line_m:.2f}", "最短白線距離 m", AMBER),
        ("lane_position_flag", f"{lane_flag}", "白線内側", MID),
        ("travel_direction", f"{direction}", "進行方向", MID),
    ]
    fx, fy = 0.58, 2.16
    for i, (col, value, label, tone) in enumerate(fields):
        cx = fx + (i % 4) * 3.08
        cy = fy + (i // 4) * 1.18
        add_rect(slide, cx, cy, 2.96, 1.04, fill=WHITE, radius=True, line=LINE)
        add_mono(slide, col, cx + 0.20, cy + 0.10, 2.6, 0.24, 8.5, MUTED)
        add_text(slide, value, cx + 0.20, cy + 0.34, 2.6, 0.44, 22, tone, True, font=FONT_NUM)
        add_text(slide, label, cx + 0.20, cy + 0.76, 2.6, 0.22, 9.5, MID)

    add_rect(slide, 0.58, 4.72, 12.2, 2.06, fill=LIGHT, radius=True, line=LINE)
    add_text(slide, "設計上のポイント", 0.82, 4.86, 4.0, 0.28, 12, NAVY, True)
    add_multiline(
        slide,
        [
            f"1 つの巨大な横持ちテーブル（{f['detection_columns']} 列）に全指標を書き込み、あとから好きな切り口で切り出す方式。",
            "距離は px / m / cm の 3 系統を別列で重複保持する。どれか 1 系統だけを使い、混在させないこと。",
            "1 本の動画に車両モデルとタイヤモデルの 2 モデルを走らせ、結果を同じテーブルに混在させる（model_name で区別）。",
            "列を足すだけで新指標を追加できる反面、どの列がどのキャリブレーションで計算されたかは行から追えない。",
        ],
        0.82,
        5.24,
        11.7,
        1.4,
        11,
        MID,
        bullet=True,
        gap=6,
    )
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 06 指標カラム
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(
        slide,
        "指標カラムの読み方",
        "distance / speed / flag / scale の 4 系統。距離はいずれも px・m・cm を併記する設計",
        "02 / DATABASE",
    )

    groups = [
        (
            "距離",
            AMBER,
            [
                "approach_distance_m ─ 自転車と車の最短接近距離",
                "clearance_distance_m/cm ─ 追い越し時の離隔（旧版の主指標）",
                "l_line_distance / r_line_distance ─ 左右白線までの水平距離",
                "line_distance ─ 左右のうち小さい方＝最近接白線距離",
                "l_line_cross_m / r_line_cross_m ─ 白線のはみ出し量",
                "front_distance_m / front_vehicle_id ─ 前方車両との距離",
            ],
        ),
        (
            "速度",
            TEAL,
            [
                "pixel_speed / pixel_speed_frame ─ 補正前の px/s・px/frame",
                "speed_km_h ─ スケール適用後の速度",
                "acceleration_m_s2 ─ 1 秒分の速度差から算出",
                "acceleration_state ─ 加速 / 減速 / 等速の区分",
                "ttc_s ─ 衝突余裕時間（秒）",
            ],
        ),
        (
            "判定フラグ",
            BLUE,
            [
                "overtake / overtake_after ─ 成立フレームとその後",
                "overtake_by / overtake_by_second ─ 追い越した車 / された自転車",
                "overtake_window_offset ─ 成立を 0 とした −30〜+30",
                "oncoming_flag ─ 上り下りが交差したフレーム",
                "lane_position_flag ─ 白線内側は +、外側は −",
                "center_line / white_line_overtake_status ─ 越えの文字列区分",
            ],
        ),
        (
            "換算の基準",
            PURPLE,
            [
                "scale_pixels_per_meter ─ 縦方向スケール",
                "x_pixels_per_meter ─ 横方向スケール",
                "measure_x / measure_y ─ 実測に使う計測点（タイヤ接地点側）",
                "group_id ─ トラッキング後の車両・自転車単位の ID",
                "model_name ─ 車両モデル / タイヤモデルの別",
            ],
        ),
    ]
    gx, gy = 0.58, 1.62
    for i, (title, accent, lines) in enumerate(groups):
        cx = gx + (i % 2) * 6.20
        cy = gy + (i // 2) * 2.62
        h = 2.44
        add_rect(slide, cx, cy, 6.0, h, fill=WHITE, radius=True, line=LINE)
        add_rect(slide, cx, cy, 0.07, h, fill=accent, radius=False)
        add_text(slide, title, cx + 0.24, cy + 0.14, 3.0, 0.28, 13, NAVY, True, valign=MSO_ANCHOR.TOP)
        add_multiline(slide, lines, cx + 0.24, cy + 0.54, 5.6, h - 0.66, 9.5, MID, gap=4.5)
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 07 クラス分布
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(
        slide,
        "検出クラスの実分布",
        "車両モデルとタイヤモデルの 2 系統が同じテーブルに同居する",
        "02 / DATABASE",
    )

    classes = f["classes"]
    top = max(c for _, c in classes) if classes else 1
    tone_map = {
        "Tire": PURPLE,
        "car": BLUE,
        "truck": BLUE,
        "bus": BLUE,
        "bicycle": TEAL,
        "Bicycle_Tires": AMBER,
    }
    note_map = {
        "Tire": "タイヤ検出モデル（best.pt 系）由来",
        "car": "車両検出モデル由来",
        "truck": "車両検出モデル由来",
        "bus": "車両検出モデル由来",
        "bicycle": "車両検出モデル由来",
        "Bicycle_Tires": "自転車タイヤ。離隔の計測点に使用",
    }
    by = 1.76
    bar_x = 3.10
    bar_max = 6.1
    for name, cnt in classes:
        tone = tone_map.get(name, MID)
        add_mono(slide, name, 0.58, by, 2.4, 0.4, 12, NAVY, True)
        width = max(bar_max * cnt / top, 0.06)
        add_rect(slide, bar_x, by + 0.06, bar_max, 0.28, fill=LIGHT, radius=False)
        add_rect(slide, bar_x, by + 0.06, width, 0.28, fill=tone, radius=False)
        add_text(slide, f"{cnt:,}", bar_x + bar_max + 0.16, by, 1.2, 0.4, 12, NAVY, True, PP_ALIGN.RIGHT, font=FONT_NUM)
        add_text(slide, note_map.get(name, ""), bar_x + bar_max + 1.44, by, 2.1, 0.4, 8.8, MUTED)
        by += 0.62

    add_rect(slide, 0.58, 5.62, 12.2, 1.18, fill=PALE_BLUE, radius=True, line=LINE)
    add_multiline(
        slide,
        [
            "離隔距離は車体 bbox の幅ではなく、タイヤ側の計測点（measure_x / measure_y）を基準に測る設計。",
            "そのためタイヤクラスの検出数が車両クラスを上回る。集計時に「検出数＝台数」と読み替えないこと。",
        ],
        0.82,
        5.86,
        11.7,
        0.7,
        11,
        MID,
        bullet=True,
        gap=6,
    )
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 08 ファイル
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(
        slide,
        "出力その 2 — ファイル",
        "Run ごとに output/<フォルダ別名>/<動画名>_<タイムスタンプ>/ が作られ、その中に成果物が並ぶ",
        "03 / FILES",
    )

    add_rect(slide, 0.58, 1.62, 5.9, 3.28, fill=LIGHT, radius=True, line=LINE)
    add_text(slide, "実際のディレクトリ構成", 0.80, 1.74, 4.0, 0.26, 11, NAVY, True)
    add_mono_block(
        slide,
        [
            ("output/", NAVY),
            ("├── 2_250816_V2/                    ← 一括処理の単位", MID),
            ("│   └── 000G6013_..._20251003_155831/   ← 1 Run", MID),
            ("│       ├── summary.txt", INK),
            ("│       ├── folder_settings.json", INK),
            ("│       ├── all_detections_run_100347_*.csv", INK),
            ("│       ├── annotated_run_100347.mp4", INK),
            ("│       ├── check_img_save1.jpg", INK),
            ("│       └── overtake_snapshots/", INK),
            ("│           ├── overtake_002295_car37_bike40_01.png", MID),
            ("│           └── overtake_events_run100511.json", MID),
            ("├── all_detections_20260121_143809.csv   ← 全 Run 横断", MID),
            ("├── statistics_runs_1_100177_334本_*.xlsx", MID),
            ("└── exports/  calibrations/  presentation/", MID),
        ],
        0.80,
        2.06,
        5.6,
        2.7,
        8.4,
        gap=2.2,
    )

    add_rect(slide, 6.66, 1.62, 6.12, 3.28, fill=WHITE, radius=True, line=LINE)
    add_text(slide, "summary.txt（実物）", 6.88, 1.74, 4.0, 0.26, 11, NAVY, True)
    add_mono_block(
        slide,
        [
            ("Run ID: 117", INK),
            ("Video: 01_2024_nu_0743_bike_clips.mp4", INK),
            ("Total Detections: 7036", INK),
            ("Used Models: yolov8x.pt, best.pt", INK),
            ("Detections by model:", INK),
            ("  - yolov8x: 2911", MID),
            ("  - best:    4125", MID),
        ],
        6.88,
        2.10,
        5.8,
        1.3,
        9.5,
        gap=3,
    )
    add_line(slide, 6.88, 3.60, 12.56, 3.612, LINE)
    add_text(slide, "命名規則", 6.88, 3.72, 4.0, 0.26, 11, NAVY, True)
    add_mono_block(
        slide,
        [
            ("all_detections_run_{run_id}_{ts}.csv", INK),
            ("{フォルダ}_combined_{ts}.csv", INK),
            ("{フォルダ}_csv_bundle_{ts}.zip", INK),
            ("detections_run{run_id}_{ts}.xlsx", INK),
            ("overtake_{frame:06d}_car{G}_bike{G}_{n:02d}.png", INK),
            ("annotated_run_{run_id}.mp4", INK),
        ],
        6.88,
        4.04,
        5.8,
        0.8,
        9,
        gap=2.4,
    )

    files = [
        ("CSV", "Run の Detection 全行 / フォルダ結合 / 配布用 ZIP", TEAL),
        ("XLSX", "日本語カラム。「追い越しまとめ」シート付き", GREEN),
        ("PNG", "追い越し瞬間の無加工フレーム＝写真ギャラリーの実体", AMBER),
        ("MP4", "bbox・速度・距離を焼き込んだ確認用動画（avi/mov/mkv 可）", RED),
    ]
    fx = 0.58
    for label, desc, c in files:
        add_rect(slide, fx, 5.08, 2.96, 1.32, fill=WHITE, radius=True, line=LINE)
        add_pill(slide, label, fx + 0.20, 5.22, 0.86, c)
        add_text(slide, desc, fx + 0.20, 5.66, 2.6, 0.64, 9.5, MID, valign=MSO_ANCHOR.TOP)
        fx += 3.08
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 09 エクスポート
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(
        slide,
        "エクスポート 6 メニューの使い分け",
        "同じ DB から切り口を変えて出しているだけ。用途に合う 1 つを選べば足りる（/export_page）",
        "03 / FILES",
    )
    rows = [
        ("DBそのまま", "CSV", "1 検出 / 1 フレーム", "全列を落として自前で再集計する"),
        ("追い越しペア", "CSV", "1 フレーム（追越側と被追越側を横結合）", "両者の速度・白線距離を突き合わせる"),
        ("追い越し詳細", "CSV", "1 フレーム（イベント前後の時系列）", "1 件の追い越しを波形として見る"),
        ("追い越し有まとめ", "CSV", "1 追い越しイベント", "件数・離隔分布の全体集計"),
        ("トラックデータ", "CSV", "関与車両の全フレーム", "軌跡の再現・可視化"),
        ("金岡出力", "CSV / XLSX", "1 追い越しイベント（日本語 34 列）", "受け渡し用の確定フォーマット"),
    ]
    add_table(
        slide,
        0.58,
        1.66,
        [2.6, 1.5, 4.4, 3.7],
        ["メニュー", "形式", "1 行の単位", "使いどころ"],
        rows,
        row_h=0.40,
        size=11,
        header_h=0.34,
        tones=[NAVY, TEAL, MID, MID],
    )

    add_rect(slide, 0.58, 4.44, 6.0, 2.36, fill=WHITE, radius=True, line=LINE)
    add_rect(slide, 0.58, 4.44, 0.07, 2.36, fill=AMBER, radius=False)
    add_text(slide, "金岡出力の列構成（34 列・日本語ヘッダ）", 0.82, 4.58, 5.4, 0.28, 12, NAVY, True)
    add_mono_block(
        slide,
        [
            ("ID / Run / 測定年度 / 道路種別 / 動画名 / フレーム / 動画時間(s)", MID),
            ("追い越し側 … Group / クラス / 時速(km/h) / ピクセル速度(px/s)", INK),
            ("       中央線距離(m) / 中央線越え(m) / 中央線測定点X(px)", INK),
            ("       白線距離(m) / 白線越え(m) / 白線測定点X(px) / 測定点Y(px)", INK),
            ("追い越され側 … 同一の 9 項目", INK),
            ("接近距離(m) / 離隔距離(cm) / 離隔距離(m) / 登録日時 / メモ", MID),
        ],
        0.82,
        4.96,
        5.6,
        1.6,
        8.6,
        gap=3.5,
    )

    add_rect(slide, 6.78, 4.44, 6.0, 2.36, fill=WHITE, radius=True, line=LINE)
    add_rect(slide, 6.78, 4.44, 0.07, 2.36, fill=GREEN, radius=False)
    add_text(slide, "Excel の日本語カラム（30 列）", 7.02, 4.58, 5.4, 0.28, 12, NAVY, True)
    add_multiline(
        slide,
        [
            "検出ID・Run ID・動画ファイル名・クラス名・フレーム番号・グループID・接近相手グループID",
            "接近距離(m)(px)・離隔距離(cm)(m)(px)・ピクセル速度・ピクセル移動量(px/f)・速度(km/h)",
            "加速度(m/s²)・加減速区分・進行方向・白線内外区分・左右白線距離(m)・最短白線距離(m)",
            "追い越しフラグ・追い越し後フラグ・追い越し±30f・追い越した車両Group・対向車フラグ・TTC(s)",
            "フラグ類は 1/0 ではなく「あり／-」に変換。2 枚目に「追い越しまとめ」シートが付く。",
        ],
        7.02,
        4.96,
        5.6,
        1.6,
        9,
        MID,
        gap=4,
    )
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 10 画面マップ
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(
        slide,
        "WEB UI — 画面構成",
        "run.bat（python -m Source_code.app）で起動し、http://127.0.0.1:5000/ を開く。左サイドバーは 3 グループ",
        "04 / WEB UI",
    )

    nav = [
        (
            "Workflow — 処理を進める",
            BLUE,
            [
                ("ダッシュボード", "/"),
                ("1. 動画登録", "/upload"),
                ("2. YOLO推論", "/detect"),
                ("3. 後処理", "/post_process"),
                ("4. 検出結果", "/detections"),
            ],
        ),
        (
            "Review — 目視で確かめる",
            AMBER,
            [
                ("手動判定", "/manual_overtake"),
                ("イベント観覧", "/manual_overtake/view"),
                ("追い越し写真", "/overtake_gallery"),
                ("検証", "/verify"),
            ],
        ),
        (
            "Reports — 出す",
            TEAL,
            [
                ("集計", "/statistics"),
                ("比較分析", "/comparative_report"),
                ("出力", "/export_page"),
                ("リザルト", "/result_view"),
                ("チェックシート", "/check_sheet"),
                ("Global Stats", "/global_summary"),
            ],
        ),
    ]
    nx = 0.58
    for title, accent, items in nav:
        add_rect(slide, nx, 1.66, 3.98, 4.24, fill=WHITE, radius=True, line=LINE)
        add_rect(slide, nx, 1.66, 3.98, 0.44, fill=accent, radius=False)
        add_text(slide, title, nx + 0.20, 1.66, 3.6, 0.44, 11.5, WHITE, True)
        iy = 2.24
        for label, route in items:
            add_text(slide, label, nx + 0.20, iy, 2.0, 0.34, 11, NAVY)
            add_mono(slide, route, nx + 2.20, iy, 1.66, 0.34, 8.8, MUTED, align=PP_ALIGN.RIGHT)
            add_line(slide, nx + 0.20, iy + 0.34, nx + 3.78, iy + 0.348, LINE)
            iy += 0.42
        nx += 4.12

    add_rect(slide, 0.58, 6.10, 12.2, 0.72, fill=PALE_BLUE, radius=True, line=LINE)
    add_text(
        slide,
        "起動時に DB スキーマの自動マイグレーションが走り、コンソールに登録ルート一覧が出力される。"
        "Flask 開発サーバ（debug=True）で動作する localhost 前提の構成。",
        0.82,
        6.10,
        11.8,
        0.72,
        11,
        MID,
    )
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 11 手順 前半
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(
        slide,
        "標準の操作手順 ①〜④ — 処理を通す",
        "サイドバーの Workflow グループを上から順に使えば 1 本ぶんが完結する",
        "05 / HOW TO",
    )

    add_step(
        slide,
        0.58,
        1.70,
        6.0,
        "1",
        "動画を登録する — 1. 動画登録",
        [
            "アップロード、または既存フォルダをリンク登録する。",
            "uploads/ に配置され、Video テーブルに FPS・尺・元パスが記録される。",
            "フォルダ一括処理をするなら、ここでフォルダを登録しておく。",
        ],
        BLUE,
        h=1.0,
    )
    add_step(
        slide,
        0.58,
        3.20,
        6.0,
        "2",
        "推論を回す — 2. YOLO推論",
        [
            "単一動画モードとフォルダ一括モードがある。指定するのは次の項目。",
            "年度 / 場所 / 道路種別（拡幅・未拡幅）… 比較分析の軸になる。要注意",
            "車両検出モデル / タイヤ検出モデル … Auto か明示指定。2 モデル併用",
            "キャリブレーションプロファイル … 未指定ならサブフォルダ設定を使用",
            "「後処理を自動実行」「CSV を出力」「既存結果を上書き」の 3 チェック",
            "バックグラウンド実行。画面を離れても処理は続く。",
        ],
        ORANGE,
        h=1.9,
    )
    add_step(
        slide,
        6.86,
        1.70,
        6.0,
        "3",
        "キャリブレーションを当てて再計算する — 3. 後処理",
        [
            "推論結果は座標のまま。スケールを与えて初めて m / km/h になる。",
            "対象は Run単位 / フォルダ単位 / 条件指定 / 全データ の 4 通り。",
            "実行系：選択分実行・全データ処理実行（後処理 8 ステップ）／動画生成",
            "出力系：DBそのまま CSV・Excel／追い越しペア CSV／自転車・対象車",
            "条件指定では「未拡幅 / 拡幅 / 未定義」で対象を絞れる。",
            "画面下部の解析実行ログで失敗 Run を特定する。",
        ],
        TEAL,
        h=1.9,
    )
    add_step(
        slide,
        6.86,
        4.10,
        6.0,
        "4",
        "結果を確認する — 4. 検出結果",
        [
            "フォルダ別サマリ（Run 数・車・自転車・追い越し件数）と Run 一覧。",
            "Run ID・動画ファイル・検出数・収集年・道路タイプ・処理日時を表示。",
            "年度や道路種別のメタデータをここで一括更新できる。",
            "行を選んで CSV / Excel を落とし、検出行のプレビュー画像も参照可能。",
        ],
        PURPLE,
        h=1.4,
    )
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 12 手順 後半
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(
        slide,
        "標準の操作手順 ⑤〜⑧ — 確かめて、出す",
        "Review グループで目視補正し、Reports グループで集計・比較・配布する",
        "05 / HOW TO",
    )

    add_step(
        slide,
        0.58,
        1.70,
        6.0,
        "5",
        "目視で確かめる — Review グループ",
        [
            "追い越し写真：overtake_snapshots/ の PNG を一覧表示。誤検出の削除、",
            "　中央線・白線越えステータスの手修正、写真の再生成ができる。",
            "手動判定：フレームを送り、追越側／被追越側を指定して登録。前後 30",
            "　フレームの速度（−30f / +30f）まで保存され、取りこぼしを補完できる。",
            "イベント観覧：登録済みイベントを表で確認し CSV に出す。",
            "検証：キャリブレーションの妥当性を距離テストで確認する。",
        ],
        AMBER,
        h=1.9,
    )
    add_step(
        slide,
        0.58,
        4.10,
        6.0,
        "6",
        "集計する — 集計",
        [
            "対象 Run を複数選び、4 つの集計モードから選択する。",
            "白線区分（A/B比較）／白線距離（自転車ID別）",
            "離隔距離×速度／トラックID別 速度・白線距離",
            "「下向き移動のみ抽出」で進行方向を絞り込める。",
            "Excel は 概要・Run別集計・詳細データ・グラフ の 4 シート。",
        ],
        GREEN,
        h=1.6,
    )
    add_step(
        slide,
        6.86,
        1.70,
        6.0,
        "7",
        "比較する — 比較分析",
        [
            "年度・道路種別などで群を分け、統計的に比較する。",
            "正規性検定を経て手法を選び、効果量（Cohen's d / η²）まで算出。",
            "「外れ値を除去する (IQR法)」で四分位範囲による除外を切り替え。",
            "Excel は 分析用データ・基本統計量・検定結果・DB_ProcessLog・",
            "　DB_OvertakeEvents・DB_Video の 6 シートで、元データまで同梱。",
            "「AI分析レポート (Gemini)」で解説文を生成（外部 API キーが必要）。",
        ],
        BLUE,
        h=1.9,
    )
    add_step(
        slide,
        6.86,
        4.10,
        6.0,
        "8",
        "配布用に出す — 出力",
        [
            "6 メニューから目的のファイルをダウンロードする。",
            "受け渡し先が決まっているなら「金岡出力」。",
            "自前で再分析するなら「DBそのまま」。",
            "追い越し 1 件を波形で見るなら「追い越し詳細」。",
        ],
        TEAL,
        h=1.4,
    )
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 13 注意点
    n += 1
    slide = prs.slides.add_slide(blank)
    add_title(
        slide,
        "旧版の癖 — データを読む前に確認すること",
        "引き継ぎ・再分析でつまずきやすい箇所。母数の定義に直接効く",
        "06 / CAVEATS",
    )

    caveats = [
        (
            "キャリブレーション未適用の Run では m / km/h が意味を持たない",
            "px 系の列だけが有効。プロファイル適用後に後処理を回し直す必要がある。",
            RED,
        ),
        (
            f"追い越し成立行のうち speed_km_h = 0 が {f['overtake_speed_zero']} 件ある",
            "スケール未設定や平滑化区間の端で発生する。速度を条件に使う集計では扱いを明示する。",
            RED,
        ),
        (
            f"OvertakeEvents {t['OvertakeEvents']} 件のうち {f['overtake_events_null']} 件は離隔距離が NULL",
            "イベントは検出済みでも距離の再計算が回っていない。件数集計と距離集計で母数が変わる。",
            RED,
        ),
        (
            "離隔距離は m / cm / px が別列で重複保持されている",
            "どれか 1 系統だけを使い、混在させない。単位取り違えがそのまま結論に出る。",
            ORANGE,
        ),
        (
            "路肩拡幅の有無は Detection の列としては持たない",
            "Video.road_type（拡幅／未拡幅）か Run のフォルダ別名で管理。推論時の入力ミスが比較分析の誤りになる。",
            ORANGE,
        ),
        (
            "「上書きする」オプションは過去データを削除する",
            "取り消せない。実行前に db/ のバックアップを取る。",
            ORANGE,
        ),
        (
            "Flask 開発サーバ（debug=True）で動作する",
            "localhost 前提の構成で、外部公開向けではない。",
            MUTED,
        ),
    ]
    cy = 1.66
    for title, body, accent in caveats:
        add_rect(slide, 0.58, cy, 12.2, 0.70, fill=WHITE, radius=True, line=LINE)
        add_rect(slide, 0.58, cy, 0.07, 0.70, fill=accent, radius=False)
        add_text(slide, title, 0.86, cy + 0.06, 6.0, 0.30, 11.5, NAVY, True, valign=MSO_ANCHOR.TOP)
        add_text(slide, body, 0.86, cy + 0.36, 11.7, 0.28, 9.8, MID, valign=MSO_ANCHOR.TOP)
        cy += 0.78
    add_footer(slide, n, SOURCE)

    # ---------------------------------------------------------------- 14 まとめ
    n += 1
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=NAVY, radius=False)
    add_rect(slide, 0, 0, SLIDE_W, 0.08, fill=AMBER, radius=False)
    add_text(slide, "SUMMARY", 0.58, 0.62, 3.0, 0.26, 9.5, AMBER, True)
    add_text(
        slide,
        "旧版の設計思想と、新版への引き継ぎ",
        0.58,
        0.94,
        11.8,
        0.62,
        28,
        WHITE,
        True,
        valign=MSO_ANCHOR.TOP,
    )

    add_rect(slide, 0.58, 1.94, 6.0, 2.30, fill=NAVY_2, radius=True, line=color("2C5170"))
    add_text(slide, "旧版（ADC_08 / Flask）の方式", 0.82, 2.08, 5.4, 0.30, 13, AMBER, True)
    add_multiline(
        slide,
        [
            f"1 つの横持ちテーブル（{f['detection_columns']} 列）に全指標を書き込む。",
            "列を足すだけで新指標を追加できる。",
            "反面、どの列がどのキャリブレーションで計算されたかを行から追えない。",
            "測定区間内の正式値と区間外の参考値が区別されない。",
        ],
        0.82,
        2.50,
        5.6,
        1.6,
        11,
        color("C6D9EA"),
        bullet=True,
        gap=6,
    )

    add_rect(slide, 6.78, 1.94, 6.0, 2.30, fill=NAVY_2, radius=True, line=color("2C5170"))
    add_text(slide, "新版 ADC Measurement 1.2 の対応", 7.02, 2.08, 5.4, 0.30, 13, CYAN, True)
    add_multiline(
        slide,
        [
            "速度・横離隔・縦距離・2D 距離・TTC を版付きで計算する。",
            "測定区間内の正式値と区間外の参考値を区別する。",
            "離隔は bbox 幅ではなくタイヤ接地点を俯瞰座標へ射影して測る。",
            "両者のタイヤを確認できないフレームは代用せず NULL にする。",
        ],
        7.02,
        2.50,
        5.6,
        1.6,
        11,
        color("C6D9EA"),
        bullet=True,
        gap=6,
    )

    add_rect(slide, 0.58, 4.46, 12.2, 1.06, fill=color("1B4468"), radius=True)
    add_text(
        slide,
        "旧版で保存された速度・TTC・自動離隔を、新版の正式値としてそのままコピーしない",
        0.86,
        4.46,
        11.6,
        1.06,
        15,
        WHITE,
        True,
    )

    add_text(slide, "この資料の使いどころ", 0.58, 5.74, 4.0, 0.28, 11, AMBER, True)
    add_multiline(
        slide,
        [
            "旧版データを再分析するときの列辞書として（03〜06 ページ）",
            "旧版を実際に動かして追加処理を回すときの操作手順として（10〜12 ページ）",
            "新旧の指標定義を突き合わせ、移行対象を決めるときの基準線として（14 ページ）",
        ],
        0.58,
        6.08,
        12.0,
        0.9,
        11,
        color("A9C4DC"),
        bullet=True,
        gap=5,
    )
    add_text(slide, SOURCE, 0.58, 7.16, 10.8, 0.18, 8.2, color("7A93AB"), valign=MSO_ANCHOR.BOTTOM)
    add_text(slide, f"{n:02d}", 12.25, 7.12, 0.48, 0.22, 9, color("7A93AB"), True, PP_ALIGN.RIGHT)

    return prs


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    facts = load_facts()
    prs = make_presentation(facts)
    prs.save(OUT_PATH)
    print(f"saved: {OUT_PATH}")
    print(f"slides: {len(prs.slides)}")


if __name__ == "__main__":
    main()
