"""Generate a 20-slide, blue-led executive evaluation deck for ADC System.

The deck deliberately uses only native PowerPoint shapes and text, so it remains
editable without external fonts or image assets.  Metrics are read from the
current SQLite database in read-only mode.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "db" / "my_app_data.db"
OUT_DIR = ROOT / "output" / "presentation"
OUT_PATH = OUT_DIR / "ADC_System_全体評価と改善計画_20枚.pptx"

SLIDE_W = 13.333
SLIDE_H = 7.5
FONT = "Yu Gothic"
FONT_NUM = "Aptos Display"

NAVY = "102A43"
BLUE = "1463D9"
BLUE_2 = "2F80ED"
SKY = "DCEEFF"
PALE_BLUE = "F3F8FF"
INK = "19324A"
MID = "5E7184"
MUTED = "8191A3"
LINE = "D9E5F2"
WHITE = "FFFFFF"
GREEN = "16815A"
PALE_GREEN = "E7F6EE"
ORANGE = "D98118"
PALE_ORANGE = "FFF3DF"
RED = "C83434"
PALE_RED = "FDEBEC"
GRAY = "E8EEF5"


def color(value: str) -> RGBColor:
    return RGBColor.from_string(value)


@dataclass(frozen=True)
class Metrics:
    videos: int
    detections: int
    runs: int
    completed: int
    processing: int
    errors: int
    overtakes: int
    manual_events: int
    tracked: int
    grouped: int
    confidence_ge_50: int
    speed_nonnull: int
    speed_zero: int
    ttc_nonnull: int
    ttc_zero: int
    valid_clearance: int
    scaled: int
    db_size_bytes: int

    @property
    def completed_rate(self) -> float:
        return self.completed / self.runs if self.runs else 0.0

    def pct(self, value: int) -> float:
        return value / self.detections if self.detections else 0.0


def load_metrics() -> Metrics:
    """Read a compact metrics snapshot without mutating the production DB."""
    if not DB_PATH.exists():
        return Metrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        status_rows = dict(conn.execute("SELECT status, COUNT(*) FROM ProcessLog GROUP BY status"))
        aggregate = conn.execute(
            """
            SELECT
                COUNT(*),
                COALESCE(SUM(track_id IS NOT NULL), 0),
                COALESCE(SUM(group_id IS NOT NULL), 0),
                COALESCE(SUM(confidence >= 0.5), 0),
                COALESCE(SUM(speed_km_h IS NOT NULL), 0),
                COALESCE(SUM(speed_km_h = 0), 0),
                COALESCE(SUM(ttc_s IS NOT NULL), 0),
                COALESCE(SUM(ttc_s = 0), 0),
                COALESCE(SUM(clearance_distance_m BETWEEN 0.05 AND 10), 0),
                COALESCE(SUM(scale_pixels_per_meter IS NOT NULL), 0)
            FROM Detection
            """
        ).fetchone()
        (
            detections,
            tracked,
            grouped,
            confidence_ge_50,
            speed_nonnull,
            speed_zero,
            ttc_nonnull,
            ttc_zero,
            valid_clearance,
            scaled,
        ) = aggregate
        return Metrics(
            videos=conn.execute("SELECT COUNT(*) FROM Video").fetchone()[0],
            detections=detections,
            runs=conn.execute("SELECT COUNT(*) FROM ProcessLog").fetchone()[0],
            completed=status_rows.get("completed", 0),
            processing=status_rows.get("processing", 0),
            errors=status_rows.get("error", 0),
            overtakes=conn.execute("SELECT COUNT(*) FROM OvertakeEvents").fetchone()[0],
            manual_events=conn.execute("SELECT COUNT(*) FROM ManualOvertakeEvents").fetchone()[0],
            tracked=tracked,
            grouped=grouped,
            confidence_ge_50=confidence_ge_50,
            speed_nonnull=speed_nonnull,
            speed_zero=speed_zero,
            ttc_nonnull=ttc_nonnull,
            ttc_zero=ttc_zero,
            valid_clearance=valid_clearance,
            scaled=scaled,
            db_size_bytes=DB_PATH.stat().st_size,
        )
    finally:
        conn.close()


def set_fill(shape, fill: str) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = color(fill)


def set_line(shape, line: str | None, width: float = 1.0) -> None:
    if line is None:
        shape.line.fill.background()
        return
    shape.line.color.rgb = color(line)
    shape.line.width = Pt(width)


def add_rect(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    fill: str,
    line: str | None = None,
    rounded: bool = False,
):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    set_fill(shape, fill)
    set_line(shape, line)
    return shape


def add_circle(slide, x: float, y: float, d: float, fill: str, line: str | None = None):
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    set_fill(shape, fill)
    set_line(shape, line)
    return shape


def add_text(
    slide,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    size: float,
    fill: str = INK,
    bold: bool = False,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    valign: MSO_ANCHOR = MSO_ANCHOR.TOP,
    font_name: str = FONT,
    margin: float = 0.02,
):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(margin)
    tf.margin_right = Inches(margin)
    tf.margin_top = Inches(margin)
    tf.margin_bottom = Inches(margin)
    tf.vertical_anchor = valign
    paragraph = tf.paragraphs[0]
    paragraph.alignment = align
    paragraph.space_after = Pt(0)
    paragraph.space_before = Pt(0)
    run = paragraph.add_run()
    run.text = text
    run.font.name = font_name
    run._r.get_or_add_rPr().set(qn("a:ea"), font_name)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color(fill)
    return shape


def add_bullets(
    slide,
    items: list[str],
    x: float,
    y: float,
    w: float,
    h: float,
    size: float = 17,
    fill: str = INK,
    accent: str = BLUE,
    gap: float = 6.0,
):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(0.03)
    tf.margin_right = Inches(0.03)
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
    for index, item in enumerate(items):
        paragraph = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        paragraph.alignment = PP_ALIGN.LEFT
        paragraph.space_after = Pt(gap)
        paragraph.level = 0
        bullet = paragraph.add_run()
        bullet.text = "● "
        bullet.font.name = FONT
        bullet._r.get_or_add_rPr().set(qn("a:ea"), FONT)
        bullet.font.size = Pt(size - 3)
        bullet.font.color.rgb = color(accent)
        body = paragraph.add_run()
        body.text = item
        body.font.name = FONT
        body._r.get_or_add_rPr().set(qn("a:ea"), FONT)
        body.font.size = Pt(size)
        body.font.color.rgb = color(fill)
    return shape


def add_footer(slide, number: int, source: str = "") -> None:
    add_rect(slide, 0.55, 7.09, 12.23, 0.015, LINE)
    add_text(slide, f"ADC System｜全体評価と改善計画｜{number:02d} / 20", 0.60, 7.17, 5.8, 0.16, 8.5, MUTED, False)
    if source:
        add_text(slide, source, 6.30, 7.17, 6.42, 0.16, 8.2, MUTED, False, PP_ALIGN.RIGHT)


def add_title(slide, title: str, subtitle: str, number: int, source: str = "") -> None:
    add_rect(slide, 0.55, 0.47, 0.10, 0.78, BLUE)
    add_text(slide, title, 0.82, 0.47, 11.75, 0.46, 27, NAVY, True)
    add_text(slide, subtitle, 0.84, 1.00, 11.55, 0.28, 13.8, MID, False)
    add_footer(slide, number, source)


def add_pill(slide, text: str, x: float, y: float, w: float, fill: str, text_fill: str = WHITE, size: float = 10.5):
    add_rect(slide, x, y, w, 0.32, fill, rounded=True)
    add_text(slide, text, x + 0.04, y + 0.065, w - 0.08, 0.16, size, text_fill, True, PP_ALIGN.CENTER)


def add_metric_card(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    value: str,
    label: str,
    note: str,
    accent: str = BLUE,
    value_size: float = 29,
):
    add_rect(slide, x, y, w, h, WHITE, LINE, rounded=True)
    add_rect(slide, x, y, w, 0.09, accent)
    add_text(slide, value, x + 0.22, y + 0.33, w - 0.44, 0.50, value_size, NAVY, True, font_name=FONT_NUM)
    add_text(slide, label, x + 0.22, y + 0.97, w - 0.44, 0.22, 13, MID, True)
    add_text(slide, note, x + 0.22, y + 1.30, w - 0.44, 0.30, 10.5, MUTED)


def add_status_card(
    slide,
    x: float,
    y: float,
    title: str,
    body: str,
    marker: str,
    accent: str,
    pale: str,
):
    add_rect(slide, x, y, 3.82, 2.12, WHITE, LINE, rounded=True)
    add_circle(slide, x + 0.30, y + 0.32, 0.52, accent)
    add_text(slide, marker, x + 0.30, y + 0.43, 0.52, 0.18, 11, WHITE, True, PP_ALIGN.CENTER)
    add_text(slide, title, x + 1.00, y + 0.33, 2.45, 0.32, 16, NAVY, True)
    add_text(slide, body, x + 0.30, y + 0.93, 3.14, 0.66, 14.5, INK, False)
    add_rect(slide, x + 0.30, y + 1.73, 3.14, 0.22, pale, rounded=True)
    add_text(slide, "評価のポイント", x + 0.45, y + 1.77, 2.84, 0.12, 8.8, accent, True, PP_ALIGN.CENTER)


def add_issue_card(
    slide,
    y: float,
    rank: str,
    title: str,
    impact: str,
    action: str,
    accent: str,
    pale: str,
):
    add_rect(slide, 0.76, y, 11.83, 1.22, WHITE, LINE, rounded=True)
    add_rect(slide, 0.76, y, 0.12, 1.22, accent)
    add_circle(slide, 1.13, y + 0.31, 0.52, accent)
    add_text(slide, rank, 1.13, y + 0.42, 0.52, 0.17, 10.8, WHITE, True, PP_ALIGN.CENTER)
    add_text(slide, title, 1.89, y + 0.20, 2.87, 0.27, 15.8, NAVY, True)
    add_text(slide, impact, 4.55, y + 0.19, 4.59, 0.56, 13.2, INK, False)
    add_rect(slide, 9.47, y + 0.27, 2.65, 0.67, pale, rounded=True)
    add_text(slide, action, 9.65, y + 0.39, 2.30, 0.34, 11.3, accent, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)


def add_score_row(slide, y: float, label: str, score: int, note: str, accent: str):
    add_text(slide, label, 1.10, y + 0.04, 2.42, 0.24, 14.5, NAVY, True)
    for i in range(5):
        add_circle(slide, 3.78 + i * 0.32, y + 0.02, 0.20, accent if i < score else GRAY)
    add_text(slide, f"{score}/5", 5.50, y + 0.04, 0.52, 0.20, 13.5, accent, True, PP_ALIGN.RIGHT)
    add_text(slide, note, 6.32, y + 0.04, 5.10, 0.22, 13.2, INK)


def make_deck(metrics: Metrics) -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    prs.core_properties.title = "ADC System｜全体評価と改善計画"
    prs.core_properties.subject = "現行DB・ソースコード・自動テストに基づく20枚の評価資料"
    prs.core_properties.author = "ADC System"
    blank = prs.slide_layouts[6]

    def light_slide():
        slide = prs.slides.add_slide(blank)
        add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, PALE_BLUE)
        return slide

    # 01 Cover
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, NAVY)
    add_rect(slide, 0.76, 0.78, 0.11, 4.60, BLUE)
    add_pill(slide, "ADC SYSTEM", 1.18, 0.82, 1.56, BLUE_2, size=10)
    add_text(slide, "全体評価と\n改善計画", 1.18, 1.55, 6.25, 1.58, 38, WHITE, True)
    add_text(slide, "交通映像解析システムの実装状況・\nデータ品質・運用リスクを整理", 1.21, 3.43, 5.92, 0.72, 18.5, SKY)
    add_rect(slide, 8.05, 1.12, 4.22, 4.66, BLUE, rounded=True)
    stages = [("01", "動画入力"), ("02", "AI解析"), ("03", "人が検証"), ("04", "レポート出力")]
    for i, (num, label) in enumerate(stages):
        y = 1.60 + i * 0.88
        add_circle(slide, 8.45, y, 0.42, WHITE)
        add_text(slide, num, 8.45, y + 0.12, 0.42, 0.16, 9.5, BLUE, True, PP_ALIGN.CENTER)
        add_text(slide, label, 9.18, y + 0.03, 2.50, 0.30, 16, WHITE, True)
        if i < len(stages) - 1:
            add_rect(slide, 8.64, y + 0.42, 0.04, 0.47, SKY)
    add_text(slide, "2026年8月28日｜現行DB・ソースコード・自動テスト確認", 1.20, 6.62, 7.10, 0.20, 10.3, SKY)

    # 02 Executive conclusion
    slide = light_slide()
    add_title(slide, "結論：限定運用は可能。外部公開は条件付き", "実装資産は強い一方、数値の妥当性・品質保証・セキュリティを先に是正する必要があります。", 2, "Source: 現行DB・ソースコード監査")
    add_status_card(slide, 0.78, 1.75, "強み", "動画から安全分析・\n出力までの一気通貫", "A", GREEN, PALE_GREEN)
    add_status_card(slide, 4.76, 1.75, "条件", "速度・TTCなどの\n計測値を再検証", "B", ORANGE, PALE_ORANGE)
    add_status_card(slide, 8.74, 1.75, "停止線", "認証・秘密情報の\n是正前に公開しない", "C", RED, PALE_RED)
    add_rect(slide, 0.78, 4.47, 11.78, 1.17, NAVY, rounded=True)
    add_text(slide, "判断", 1.10, 4.79, 0.86, 0.22, 13.5, SKY, True)
    add_text(slide, "P0：セキュリティ　→　P1：計測精度　→　P2：品質ゲート　の順に進める", 2.13, 4.72, 9.73, 0.40, 19, WHITE, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)

    # 03 Scope
    slide = light_slide()
    add_title(slide, "評価の対象と根拠", "主観的な印象ではなく、現行データ・コード・実行結果を突き合わせて評価しました。", 3, "Source: db/my_app_data.db・docs/・Source_code/")
    sources = [
        ("現行DB", "169動画・251 Run・121万検出行の実値", BLUE, PALE_BLUE),
        ("仕様・処理資料", "ワークフロー、7段後処理、指標の定義", GREEN, PALE_GREEN),
        ("ソースコード", "Web設定、DB、キュー、認可、依存関係", ORANGE, PALE_ORANGE),
        ("自動テスト", "37件の実行結果と失敗の内容", RED, PALE_RED),
    ]
    for i, (title, desc, accent, pale) in enumerate(sources):
        x = 0.78 + (i % 2) * 6.02
        y = 1.76 + (i // 2) * 1.62
        add_rect(slide, x, y, 5.68, 1.27, WHITE, LINE, rounded=True)
        add_rect(slide, x, y, 0.12, 1.27, accent)
        add_pill(slide, title, x + 0.29, y + 0.22, 1.44, accent, size=9.8)
        add_text(slide, desc, x + 1.97, y + 0.31, 3.25, 0.43, 15.0, INK, True)
        add_rect(slide, x + 0.29, y + 0.89, 5.02, 0.17, pale, rounded=True)
    add_rect(slide, 0.78, 5.50, 11.78, 0.66, WHITE, LINE, rounded=True)
    add_text(slide, "狙い：作り直しではなく、使える資産を残して「安全に継続運用できる状態」へ進めること", 1.06, 5.69, 11.20, 0.24, 15, NAVY, True, PP_ALIGN.CENTER)

    # 04 Value flow
    slide = light_slide()
    add_title(slide, "ADCが提供する価値", "交通映像を、安全分析に使えるデータとレポートへ変換する仕組みです。", 4, "Source: docs/ADC_System_Overview.md")
    flow = [
        ("動画", "入力", BLUE),
        ("校正", "実空間へ変換", BLUE_2),
        ("検出・追跡", "YOLO / Track", BLUE),
        ("7段後処理", "速度・距離・TTC", BLUE_2),
        ("人が検証", "補正・確認", GREEN),
        ("出力", "Excel / CSV / 動画", NAVY),
    ]
    for i, (title, label, accent) in enumerate(flow):
        x = 0.60 + i * 2.12
        add_rect(slide, x, 2.27, 1.70, 1.77, WHITE, LINE, rounded=True)
        add_circle(slide, x + 0.57, 2.56, 0.56, accent)
        add_text(slide, str(i + 1), x + 0.57, 2.69, 0.56, 0.15, 9.5, WHITE, True, PP_ALIGN.CENTER)
        add_text(slide, title, x + 0.13, 3.26, 1.44, 0.23, 14.0, NAVY, True, PP_ALIGN.CENTER)
        add_text(slide, label, x + 0.12, 3.59, 1.46, 0.18, 9.6, MID, False, PP_ALIGN.CENTER)
        if i < len(flow) - 1:
            add_text(slide, "→", x + 1.76, 2.91, 0.30, 0.30, 20, BLUE, True, PP_ALIGN.CENTER)
    add_rect(slide, 1.42, 5.02, 10.49, 0.56, PALE_GREEN, rounded=True)
    add_text(slide, "差別化ポイント：AIだけで完結させず、人が最終確認・再計算できる Human-in-the-loop", 1.68, 5.18, 9.97, 0.20, 13.2, GREEN, True, PP_ALIGN.CENTER)

    # 05 Implemented strengths
    slide = light_slide()
    add_title(slide, "実装済みの強み", "中核機能はすでに揃っており、改善は“新規開発”より“品質の引き上げ”が中心です。", 5, "Source: docs/ADC_System_Specification.md")
    strength_cards = [
        ("AI検出・追跡", "車両・自転車・タイヤ\nYOLO＋追跡ID", "01"),
        ("安全指標", "速度・白線距離・\n離隔・追い越し・TTC", "02"),
        ("手動検証", "誤検知修正・\nイベント追加・再計算", "03"),
        ("出力・可視化", "Excel・CSV・\n解析済み動画", "04"),
    ]
    for i, (title, body, num) in enumerate(strength_cards):
        x = 0.77 + i * 3.02
        add_rect(slide, x, 1.88, 2.71, 3.13, WHITE, LINE, rounded=True)
        add_pill(slide, num, x + 0.24, 2.16, 0.61, BLUE, size=9.6)
        add_text(slide, title, x + 0.24, 2.86, 2.22, 0.39, 16.2, NAVY, True)
        add_text(slide, body, x + 0.24, 3.57, 2.14, 0.69, 14.1, INK)
        add_rect(slide, x + 0.24, 4.58, 2.16, 0.14, SKY, rounded=True)
    add_rect(slide, 0.77, 5.48, 11.79, 0.56, NAVY, rounded=True)
    add_text(slide, "評価：機能の網羅性は高い。次の焦点は、主要指標を“信頼して使える”状態にすること。", 1.10, 5.65, 11.10, 0.20, 13.7, WHITE, True, PP_ALIGN.CENTER)

    # 06 Current scale
    slide = light_slide()
    add_title(slide, "現行の運用規模", "データ量はすでに小規模な試作段階を超え、運用設計が必要な規模です。", 6, "Source: db/my_app_data.db（2026-08-28 read-only 集計）")
    add_metric_card(slide, 0.78, 1.85, 2.75, 1.72, f"{metrics.videos:,}", "登録動画", "解析対象ファイル", BLUE)
    add_metric_card(slide, 3.72, 1.85, 2.75, 1.72, f"{metrics.detections / 1_000_000:.2f}M", "検出レコード", f"{metrics.detections:,} 行", GREEN)
    add_metric_card(slide, 6.66, 1.85, 2.75, 1.72, f"{metrics.runs:,}", "処理 Run", f"完了 {metrics.completed:,} 件", ORANGE)
    add_metric_card(slide, 9.60, 1.85, 2.75, 1.72, f"{metrics.overtakes:,}", "追い越しイベント", f"手動イベント {metrics.manual_events:,} 件", RED)
    add_rect(slide, 0.78, 4.25, 11.78, 1.22, WHITE, LINE, rounded=True)
    add_text(slide, "読み方", 1.08, 4.58, 0.78, 0.22, 14, BLUE, True)
    add_text(slide, "検出レコードはフレーム単位の観測値です。ユニークな車両台数ではありません。", 2.12, 4.58, 9.67, 0.22, 15.0, INK, True)
    add_text(slide, "だからこそ、データの“量”だけでなく、速度・距離などの“使える値の割合”で品質を管理します。", 2.12, 4.93, 9.65, 0.20, 13.1, MID)

    # 07 Run stability
    slide = light_slide()
    add_title(slide, "処理Runの完了率は97.6%", "処理の大半は完了している一方、エラーの原因はGPU環境に起因しており、対策が必要です。", 7, "Source: db/my_app_data.db・ProcessLog error_message")
    add_rect(slide, 0.84, 1.89, 5.14, 3.58, WHITE, LINE, rounded=True)
    add_text(slide, f"{metrics.completed_rate * 100:.1f}%", 1.27, 2.39, 4.20, 0.72, 37, GREEN, True, PP_ALIGN.CENTER, font_name=FONT_NUM)
    add_text(slide, "Run 完了率", 1.27, 3.27, 4.20, 0.24, 15, NAVY, True, PP_ALIGN.CENTER)
    add_rect(slide, 1.20, 3.95, 4.39, 0.25, GRAY, rounded=True)
    add_rect(slide, 1.20, 3.95, 4.39 * metrics.completed_rate, 0.25, GREEN, rounded=True)
    add_text(slide, f"完了 {metrics.completed}　処理中 {metrics.processing}　エラー {metrics.errors}", 1.10, 4.49, 4.60, 0.22, 12.6, MID, True, PP_ALIGN.CENTER)
    add_rect(slide, 6.34, 1.89, 6.14, 3.58, PALE_ORANGE, None, rounded=True)
    add_pill(slide, "確認された障害", 6.70, 2.25, 1.76, ORANGE, size=9.5)
    add_text(slide, "CUDA 互換性エラー", 6.70, 2.91, 4.98, 0.34, 20, NAVY, True)
    add_text(slide, "GPUとPyTorch / CUDAの組合せが合わず、\n3 Runがエラーで停止しています。", 6.70, 3.48, 5.10, 0.53, 15, INK)
    add_text(slide, "改善：環境固定・CPUフォールバック・再実行導線", 6.70, 4.56, 5.14, 0.22, 13.2, ORANGE, True)

    # 08 Quality foundations
    slide = light_slide()
    add_title(slide, "データ品質：追跡までは広く付与されている", "検出・追跡の土台は機能しています。課題は、そこから安全指標へ変換する部分です。", 8, "Source: db/my_app_data.db・Detection 集計")
    quality = [
        (f"{metrics.pct(metrics.tracked) * 100:.1f}%", "track_id 付与", f"{metrics.tracked:,} / {metrics.detections:,}", BLUE),
        (f"{metrics.pct(metrics.grouped) * 100:.1f}%", "group_id 付与", f"{metrics.grouped:,} / {metrics.detections:,}", GREEN),
        (f"{metrics.pct(metrics.confidence_ge_50) * 100:.1f}%", "信頼度 0.5以上", f"{metrics.confidence_ge_50:,} / {metrics.detections:,}", ORANGE),
        (f"{metrics.valid_clearance:,}", "有効な離隔値", "安全指標としては不足", RED),
    ]
    for i, (value, label, note, accent) in enumerate(quality):
        x = 0.78 + i * 3.02
        add_rect(slide, x, 1.89, 2.72, 2.05, WHITE, LINE, rounded=True)
        add_circle(slide, x + 0.27, 2.20, 0.12, accent)
        add_text(slide, value, x + 0.25, 2.56, 2.22, 0.41, 24, NAVY, True, PP_ALIGN.CENTER, font_name=FONT_NUM)
        add_text(slide, label, x + 0.22, 3.13, 2.28, 0.20, 12.7, MID, True, PP_ALIGN.CENTER)
        add_text(slide, note, x + 0.19, 3.48, 2.34, 0.20, 9.6, MUTED, False, PP_ALIGN.CENTER)
    add_rect(slide, 0.78, 4.73, 11.78, 0.73, NAVY, rounded=True)
    add_text(slide, "評価：検出・追跡を“分析結果”へつなぐ、校正と後処理の品質管理がボトルネックです。", 1.10, 4.98, 11.12, 0.24, 14.3, WHITE, True, PP_ALIGN.CENTER)

    # 09 Measurement zero issue
    slide = light_slide()
    add_title(slide, "最優先①　実空間への換算が成立していない", "速度・加速度の前提となるキャリブレーションスケールが、現行DBに記録されていません。", 9, "Source: db/my_app_data.db・Detection 集計")
    add_rect(slide, 0.78, 1.82, 5.54, 3.65, WHITE, LINE, rounded=True)
    add_pill(slide, "観測事実", 1.08, 2.16, 1.18, RED, size=9.8)
    add_text(slide, f"{metrics.scaled:,}", 1.05, 2.86, 2.22, 0.62, 34, RED, True, PP_ALIGN.CENTER, font_name=FONT_NUM)
    add_text(slide, "scale_pixels_per_meter の有効値", 1.05, 3.60, 3.82, 0.24, 14.2, NAVY, True, PP_ALIGN.CENTER)
    add_text(slide, f"対象：{metrics.detections:,} 検出行", 1.05, 4.09, 3.82, 0.20, 12.4, MID, False, PP_ALIGN.CENTER)
    add_rect(slide, 6.67, 1.82, 5.89, 3.65, PALE_RED, None, rounded=True)
    add_text(slide, "影響", 7.03, 2.15, 1.0, 0.26, 15.5, RED, True)
    add_text(slide, "km/h・加速度・距離の\n研究上の解釈ができない", 7.03, 2.78, 4.78, 0.73, 22, NAVY, True)
    add_text(slide, "改善：代表動画3本で「校正保存 → 後処理 →\n期待値比較」を通し、スケールの保存経路を固定する。", 7.03, 4.08, 4.78, 0.55, 14.3, INK)

    # 10 Safety metric zero issue
    slide = light_slide()
    add_title(slide, "最優先②　安全指標を“0”のまま利用しない", "TTCや速度の0は安全を意味しません。未計算・変換失敗・前提不足を区別する必要があります。", 10, "Source: db/my_app_data.db・Detection / OvertakeEvents 集計")
    add_metric_card(slide, 0.78, 1.84, 3.47, 1.96, f"{metrics.speed_nonnull:,}", "速度の非NULL値", "すべて 0 km/h", RED, value_size=27)
    add_metric_card(slide, 4.94, 1.84, 3.47, 1.96, f"{metrics.ttc_nonnull:,}", "TTCの非NULL値", "すべて 0 秒", RED, value_size=27)
    add_metric_card(slide, 9.10, 1.84, 3.47, 1.96, f"{metrics.valid_clearance:,}", "有効離隔値", f"追い越しイベント {metrics.overtakes} 件", ORANGE, value_size=29)
    add_rect(slide, 0.78, 4.50, 11.78, 1.12, WHITE, LINE, rounded=True)
    add_text(slide, "必要な品質ルール", 1.09, 4.82, 2.24, 0.23, 15, NAVY, True)
    add_text(slide, "①未計算とゼロを分離　②欠測率を出力　③イベント単位で手動確認　④閾値外を自動除外", 3.48, 4.82, 8.42, 0.23, 14.2, INK, True)

    # 11 Validation plan
    slide = light_slide()
    add_title(slide, "機能の存在と、性能の証明を分ける", "研究・行政報告に使うには、代表条件で再現可能な精度評価を持つことが必須です。", 11, "Source: docs/ADC_System_Thesis_Content.md・仕様資料")
    validation = [
        ("① 正解データ", "代表映像3本を人手でラベル付け\n速度・距離・追い越しの正解を用意", BLUE),
        ("② 比較評価", "AI結果との差を計測\n平均誤差・再現率・欠測率を出す", ORANGE),
        ("③ 合格基準", "用途別の閾値を決める\n満たせない映像は自動で除外", GREEN),
    ]
    for i, (title, body, accent) in enumerate(validation):
        x = 0.86 + i * 4.08
        add_rect(slide, x, 1.95, 3.62, 3.20, WHITE, LINE, rounded=True)
        add_circle(slide, x + 0.31, 2.27, 0.52, accent)
        add_text(slide, str(i + 1), x + 0.31, 2.39, 0.52, 0.16, 10.0, WHITE, True, PP_ALIGN.CENTER)
        add_text(slide, title, x + 0.97, 2.31, 2.24, 0.25, 15.6, NAVY, True)
        add_text(slide, body, x + 0.31, 3.11, 2.98, 0.78, 14.5, INK)
        add_rect(slide, x + 0.31, 4.50, 2.90, 0.13, accent, rounded=True)
    add_text(slide, "アウトプット：各指標について「どの条件なら使えるか」を説明できる評価レポート", 1.13, 5.73, 11.08, 0.26, 15.0, NAVY, True, PP_ALIGN.CENTER)

    # 12 Tests
    slide = light_slide()
    add_title(slide, "最優先③　自動テストが品質ゲートになっていない", "テストは存在しますが、現行コードとの境界不整合により、リリース判断に使える状態ではありません。", 12, "Source: python -m unittest discover -s tests（2026-08-28）")
    add_rect(slide, 0.83, 1.84, 4.01, 3.46, NAVY, None, rounded=True)
    add_text(slide, "37", 1.13, 2.24, 3.42, 0.68, 40, WHITE, True, PP_ALIGN.CENTER, font_name=FONT_NUM)
    add_text(slide, "実行テスト数", 1.13, 3.12, 3.42, 0.24, 14.5, SKY, True, PP_ALIGN.CENTER)
    add_text(slide, "現行コードを対象に実行済み", 1.13, 4.14, 3.42, 0.20, 11.2, SKY, False, PP_ALIGN.CENTER)
    add_metric_card(slide, 5.22, 1.84, 3.35, 1.68, "6", "Failures", "期待値との差異", RED, value_size=31)
    add_metric_card(slide, 9.04, 1.84, 3.35, 1.68, "29", "Errors", "実行境界・依存関係", ORANGE, value_size=31)
    add_rect(slide, 5.22, 3.89, 7.17, 1.41, WHITE, LINE, rounded=True)
    add_text(slide, "観測された不整合", 5.51, 4.18, 2.12, 0.20, 13.5, NAVY, True)
    add_text(slide, "ルート分割後の参照ずれ / 未定義DBパス / 旧APIを前提としたテスト", 5.51, 4.57, 6.40, 0.24, 13.0, INK)
    add_text(slide, "改善：テストを現行モジュールへ揃え、全件グリーンをCIの必須条件にする。", 1.06, 5.79, 11.23, 0.25, 14.5, RED, True, PP_ALIGN.CENTER)

    # 13 Security
    slide = light_slide()
    add_title(slide, "最優先④　セキュリティは公開停止レベル", "外部公開・複数ユーザー利用の前に、秘密情報と破壊操作の保護を完了させる必要があります。", 13, "Source: .env / .gitignore / Source_code/app.py / routes 監査")
    security = [
        ("秘密情報", ".env がGit管理され、\nAPIキーが設定済み", "失効・再発行・履歴除去", RED),
        ("Web設定", "固定Secret / debug=True", "環境別設定・debug無効化", RED),
        ("操作保護", "認証・CSRFの実装が\n確認できない", "RBAC・CSRF・監査ログ", RED),
    ]
    for i, (title, body, action, accent) in enumerate(security):
        x = 0.82 + i * 4.07
        add_rect(slide, x, 1.89, 3.56, 3.35, WHITE, LINE, rounded=True)
        add_pill(slide, "P0", x + 0.30, 2.18, 0.51, accent, size=9.4)
        add_text(slide, title, x + 0.30, 2.81, 2.70, 0.25, 16.2, NAVY, True)
        add_text(slide, body, x + 0.30, 3.34, 2.80, 0.56, 14.0, INK)
        add_rect(slide, x + 0.30, 4.46, 2.90, 0.36, PALE_RED, rounded=True)
        add_text(slide, action, x + 0.40, 4.55, 2.70, 0.16, 9.9, RED, True, PP_ALIGN.CENTER)
    add_text(slide, "重要：この資料には秘密値を記載していません。是正完了まで外部公開は保留します。", 1.04, 5.69, 11.28, 0.24, 13.8, RED, True, PP_ALIGN.CENTER)

    # 14 Jobs
    slide = light_slide()
    add_title(slide, "運用継続性：長時間ジョブは再起動に弱い", "後処理のキュー・進捗がプロセス内メモリ中心のため、停止時の再開・追跡・再試行が難しくなります。", 14, "Source: Source_code/routes/post_process.py 監査")
    add_rect(slide, 0.82, 1.89, 5.20, 3.38, PALE_ORANGE, None, rounded=True)
    add_text(slide, "現在のリスク", 1.15, 2.22, 2.1, 0.25, 16.2, ORANGE, True)
    add_bullets(slide, [
        "アプリ再起動でジョブ状態が残らない",
        "処理失敗の再実行条件が追えない",
        "並列処理時の排他・進捗履歴が弱い",
    ], 1.15, 2.92, 4.45, 1.43, 15.0, INK, ORANGE, 7)
    add_rect(slide, 6.35, 1.89, 6.13, 3.38, WHITE, LINE, rounded=True)
    add_text(slide, "改善の到達像", 6.69, 2.22, 2.5, 0.25, 16.2, GREEN, True)
    add_bullets(slide, [
        "DBに永続ジョブテーブルを置く",
        "ワーカーで retry / cancel / resume を管理",
        "job IDで進捗・監査ログを一元化する",
    ], 6.69, 2.92, 5.25, 1.43, 15.0, INK, GREEN, 7)
    add_text(slide, "目的：長時間動画処理を“人が張り付かなくても復旧できる運用”へ変える。", 1.10, 5.74, 11.10, 0.24, 14.8, NAVY, True, PP_ALIGN.CENTER)

    # 15 DB operations
    slide = light_slide()
    add_title(slide, "データ基盤：SQLiteは使えるが、運用の上限を決める", "650 MB・121万行まで成長しており、同時利用・並列処理には接続制御と保全が必要です。", 15, "Source: db/my_app_data.db・db_manager.py 監査")
    add_metric_card(slide, 0.82, 1.86, 3.16, 1.74, f"{metrics.db_size_bytes / 1_000_000:.0f} MB", "DBファイル", "単一ファイルDB", BLUE, value_size=28)
    add_metric_card(slide, 4.42, 1.86, 3.16, 1.74, f"{metrics.detections / 1_000_000:.2f}M", "Detection行", "フレーム単位の観測", GREEN, value_size=28)
    add_metric_card(slide, 8.02, 1.86, 3.16, 1.74, "SQLite", "現行ストア", "統制された単一運用には適合", ORANGE, value_size=26)
    add_rect(slide, 0.82, 4.26, 11.68, 1.25, WHITE, LINE, rounded=True)
    add_bullets(slide, [
        "接続を一元化し、busy timeout・retry・バックアップを標準化する",
        "容量・書込み待ち・エラー数を監視し、移行条件を先に決める",
    ], 1.08, 4.55, 10.95, 0.67, 14.2, INK, BLUE, 5)

    # 16 Maintainability
    slide = light_slide()
    add_title(slide, "保守性と再現性：複雑さを“管理可能な単位”へ戻す", "大きなモジュール・古い経路・未固定依存により、変更の影響範囲が見えにくくなっています。", 16, "Source: Source_code/・docs/requirements.txt・git status")
    maintenance = [
        ("3,756行", "db_manager.py", "DB操作をrepository層へ分割"),
        ("2,407行", "routes/manual.py", "手動検証をservice/APIへ分離"),
        ("8,712行", "legacy/routes_legacy.py", "legacyを凍結し段階的に削除"),
    ]
    for i, (value, label, action) in enumerate(maintenance):
        x = 0.86 + i * 4.08
        add_rect(slide, x, 1.90, 3.62, 3.24, WHITE, LINE, rounded=True)
        add_text(slide, value, x + 0.30, 2.31, 2.99, 0.45, 27, NAVY, True, PP_ALIGN.CENTER, font_name=FONT_NUM)
        add_text(slide, label, x + 0.30, 2.91, 2.99, 0.22, 13.3, MID, True, PP_ALIGN.CENTER)
        add_rect(slide, x + 0.32, 3.60, 2.95, 0.54, PALE_BLUE, rounded=True)
        add_text(slide, action, x + 0.48, 3.74, 2.64, 0.24, 11.4, BLUE, True, PP_ALIGN.CENTER)
    add_text(slide, "同時に：依存バージョン固定・CI・リリースタグ・変更レビューを標準化する。", 1.11, 5.75, 11.12, 0.23, 14.5, NAVY, True, PP_ALIGN.CENTER)

    # 17 Overall score
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, NAVY)
    add_text(slide, "全体評価｜5軸の現在地", 0.82, 0.62, 8.80, 0.40, 27, WHITE, True)
    add_text(slide, "機能は進んでいる。データの信頼性・品質保証・公開安全性が改善の中心です。", 0.84, 1.12, 10.90, 0.24, 13.7, SKY)
    add_rect(slide, 0.78, 1.72, 11.78, 4.74, WHITE, None, rounded=True)
    add_score_row(slide, 2.12, "機能の網羅性", 4, "一気通貫の処理と出力を実装", GREEN)
    add_score_row(slide, 2.90, "データの妥当性", 1, "校正・速度・TTCの再検証が必要", RED)
    add_score_row(slide, 3.68, "運用の安定性", 2, "GPU障害・ジョブ復旧・DB運用が課題", ORANGE)
    add_score_row(slide, 4.46, "セキュリティ", 1, "公開前にP0是正が必須", RED)
    add_score_row(slide, 5.24, "品質エンジニアリング", 1, "テスト整備・CI必須化が必要", RED)
    add_text(slide, "判定", 9.03, 6.70, 0.67, 0.18, 10.2, SKY, True)
    add_text(slide, "内部・研究パイロット：条件付きGo　｜　外部公開：P0/P1完了までNo-Go", 9.78, 6.66, 2.63, 0.30, 10.3, WHITE, True, PP_ALIGN.RIGHT)

    # 18 Priority
    slide = light_slide()
    add_title(slide, "改善の優先順位", "“重要なものから全部”ではなく、公開停止ラインと数値の信頼性を先に解消します。", 18, "Source: 現行DB・ソースコード・テスト結果の統合評価")
    add_issue_card(slide, 1.66, "P0", "公開停止ライン", "秘密情報・debug・認証/CSRFを是正。外部公開の前提を整える。", "即時：公開しない", RED, PALE_RED)
    add_issue_card(slide, 3.07, "P1", "計測値の信頼性", "校正保存、速度・TTCの計算、代表動画の正解比較を完了する。", "2週間：数値を検証", ORANGE, PALE_ORANGE)
    add_issue_card(slide, 4.48, "P2", "品質と復旧性", "全テストの整合、CI、永続ジョブ・再実行・バックアップを整える。", "30日：運用を固める", BLUE, PALE_BLUE)
    add_text(slide, "P3（60〜90日）：DB移行条件・モジュール分割・監視基盤を計画的に実装する。", 1.08, 6.22, 11.08, 0.22, 13.5, MID, True, PP_ALIGN.CENTER)

    # 19 30-day plan
    slide = light_slide()
    add_title(slide, "最初の30日：小さく直し、数値で合格を確認する", "改善作業そのものではなく、各段階で“完了をどう証明するか”を明確にします。", 19, "Source: 推奨アクションプラン")
    roadmap = [
        ("Day 0–3", "公開停止ラインを解消", ["キー失効・再発行", "debug無効化", "認証/CSRFの設計開始"], RED, PALE_RED),
        ("Week 1–2", "計測の正解を作る", ["代表動画3本を選定", "校正→後処理を通す", "速度・TTCを正解比較"], ORANGE, PALE_ORANGE),
        ("Week 3–4", "品質ゲートを通す", ["テストの参照を現行化", "37件を全件グリーンへ", "CI・再実行導線を追加"], BLUE, PALE_BLUE),
    ]
    for i, (phase, title, tasks, accent, pale) in enumerate(roadmap):
        x = 0.76 + i * 4.15
        add_rect(slide, x, 1.82, 3.76, 4.10, WHITE, LINE, rounded=True)
        add_pill(slide, phase, x + 0.29, 2.16, 1.03, accent, size=9.7)
        add_text(slide, title, x + 0.29, 2.80, 3.04, 0.40, 17, NAVY, True)
        add_bullets(slide, tasks, x + 0.29, 3.52, 3.00, 1.34, 14.0, INK, accent, 7)
        add_rect(slide, x + 0.29, 5.30, 3.08, 0.28, pale, rounded=True)
    # 20 Success and ask
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, NAVY)
    add_pill(slide, "NEXT DECISION", 0.82, 0.80, 1.69, BLUE, size=10.2)
    add_text(slide, "成功条件を満たしてから、\n次の公開判断へ", 0.82, 1.47, 7.31, 1.25, 31, WHITE, True)
    exit_criteria = [
        ("安全", "秘密情報なし・認証/CSRF・debug off"),
        ("正確", "速度/TTCを正解データと比較して合格"),
        ("品質", "自動テスト全件グリーン＋CI"),
        ("運用", "失敗Runの再試行・バックアップを確認"),
    ]
    for i, (title, body) in enumerate(exit_criteria):
        x = 0.82 + (i % 2) * 5.94
        y = 3.38 + (i // 2) * 1.13
        add_circle(slide, x, y + 0.08, 0.34, BLUE)
        add_text(slide, "✓", x, y + 0.17, 0.34, 0.12, 9.3, WHITE, True, PP_ALIGN.CENTER)
        add_text(slide, title, x + 0.58, y, 1.00, 0.22, 14.5, SKY, True)
        add_text(slide, body, x + 1.75, y, 3.83, 0.40, 13.4, WHITE)
    add_rect(slide, 0.82, 6.17, 11.70, 0.57, BLUE, None, rounded=True)
    add_text(slide, "お願い：P0〜P2の改善スプリントを承認し、成功条件を満たすまで外部公開を保留する。", 1.12, 6.35, 11.10, 0.20, 13.5, WHITE, True, PP_ALIGN.CENTER)

    return prs


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    metrics = load_metrics()
    deck = make_deck(metrics)
    deck.save(OUT_PATH)
    print(f"saved: {OUT_PATH}")
    print(f"slides: {len(deck.slides)}")
    print(f"metrics: videos={metrics.videos}, detections={metrics.detections}, runs={metrics.runs}")


if __name__ == "__main__":
    main()
