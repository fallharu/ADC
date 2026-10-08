"""ADC System の現状と改善点を5枚のシンプルなPowerPointにまとめる。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches

from generate_adc_visualization_ppt import (
    BLUE,
    FONT_NUM,
    GREEN,
    INK,
    LIGHT,
    LINE,
    MID,
    MUTED,
    NAVY,
    ORANGE,
    PALE_BLUE,
    PALE_ORANGE,
    PALE_RED,
    PALE_TEAL,
    RED,
    SLIDE_H,
    SLIDE_W,
    TEAL,
    WHITE,
    add_circle,
    add_footer,
    add_pill,
    add_rect,
    add_text,
)


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "db" / "my_app_data.db"
OUT_DIR = ROOT / "output" / "presentation"
OUT_PATH = OUT_DIR / "ADC_System_現状と改善点_シンプル版.pptx"


@dataclass(frozen=True)
class Status:
    videos: int
    detections: int
    runs: int
    completed: int
    processing: int
    errors: int
    overtakes: int
    valid_clearance: int
    speed_nonnull: int
    speed_zero: int
    ttc_nonnull: int
    ttc_zero: int


def load_status() -> Status:
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        status = dict(conn.execute("SELECT status, COUNT(*) FROM ProcessLog GROUP BY status"))
        speed_nonnull, speed_zero, ttc_nonnull, ttc_zero = conn.execute(
            "SELECT SUM(speed_km_h IS NOT NULL), SUM(speed_km_h = 0), "
            "SUM(ttc_s IS NOT NULL), SUM(ttc_s = 0) FROM Detection"
        ).fetchone()
        return Status(
            videos=conn.execute("SELECT COUNT(*) FROM Video").fetchone()[0],
            detections=conn.execute("SELECT COUNT(*) FROM DetectionRaw").fetchone()[0],
            runs=conn.execute("SELECT COUNT(*) FROM ProcessLog").fetchone()[0],
            completed=status.get("completed", 0),
            processing=status.get("processing", 0),
            errors=status.get("error", 0),
            overtakes=conn.execute("SELECT COUNT(*) FROM OvertakeEvents").fetchone()[0],
            valid_clearance=conn.execute(
                "SELECT COUNT(*) FROM Detection "
                "WHERE clearance_distance_m BETWEEN 0.05 AND 10"
            ).fetchone()[0],
            speed_nonnull=speed_nonnull or 0,
            speed_zero=speed_zero or 0,
            ttc_nonnull=ttc_nonnull or 0,
            ttc_zero=ttc_zero or 0,
        )
    finally:
        conn.close()


def add_title(slide, title: str, lead: str | None = None, dark: bool = False) -> None:
    add_text(slide, title, 0.72, 0.52, 11.90, 0.58, 27, WHITE if dark else NAVY, True)
    if lead:
        add_text(
            slide,
            lead,
            0.74,
            1.12,
            11.70,
            0.42,
            13,
            PALE_BLUE if dark else MID,
        )


def add_kpi(slide, x: float, value: str, label: str, note: str, accent) -> None:
    add_rect(slide, x, 2.02, 2.78, 1.74, fill=WHITE, radius=True, line=LINE)
    add_rect(slide, x, 2.02, 0.08, 1.74, fill=accent, radius=False)
    add_text(slide, value, x + 0.25, 2.25, 2.26, 0.56, 27, NAVY, True, font=FONT_NUM)
    add_text(slide, label, x + 0.25, 2.88, 2.26, 0.28, 12, MID, True)
    add_text(slide, note, x + 0.25, 3.28, 2.26, 0.22, 9.2, MUTED)


def add_issue(slide, y: float, number: str, title: str, body: str, tag: str, accent, pale) -> None:
    add_rect(slide, 0.78, y, 11.78, 1.12, fill=pale, radius=True)
    add_circle(slide, 1.04, y + 0.27, 0.48, accent, number, WHITE, 12)
    add_text(slide, title, 1.72, y + 0.17, 3.18, 0.34, 14.5, NAVY, True)
    add_text(slide, body, 4.64, y + 0.16, 6.12, 0.58, 12.2, INK, False, valign=MSO_ANCHOR.TOP)
    add_pill(slide, tag, 10.93, y + 0.35, 1.20, accent, size=10)


def add_roadmap_card(
    slide,
    x: float,
    phase: str,
    title: str,
    items: list[str],
    outcome: str,
    accent,
    pale,
) -> None:
    add_rect(slide, x, 1.92, 3.74, 4.36, fill=WHITE, radius=True, line=LINE)
    add_rect(slide, x, 1.92, 3.74, 0.10, fill=accent, radius=False)
    add_pill(slide, phase, x + 0.28, 2.20, 0.94, accent, size=10)
    add_text(slide, title, x + 0.28, 2.72, 3.16, 0.44, 17, NAVY, True)
    for i, item in enumerate(items):
        y = 3.38 + i * 0.59
        add_circle(slide, x + 0.31, y + 0.03, 0.16, accent)
        add_text(slide, item, x + 0.60, y - 0.02, 2.82, 0.42, 11.5, INK)
    add_rect(slide, x + 0.25, 5.55, 3.24, 0.46, fill=pale, radius=True)
    add_text(slide, outcome, x + 0.37, 5.64, 3.00, 0.25, 10.2, accent, True, PP_ALIGN.CENTER)


def make_presentation(status: Status) -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    prs.core_properties.title = "ADC System｜現状と改善点"
    prs.core_properties.subject = "現行DBとソースコードに基づく簡易説明"
    prs.core_properties.author = "ADC System"
    blank = prs.slide_layouts[6]

    # 1. 表紙
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=NAVY, radius=False)
    add_pill(slide, "ADC SYSTEM", 0.78, 0.76, 1.48, BLUE, size=10.5)
    add_text(slide, "現状と改善点", 0.78, 1.66, 6.90, 0.74, 38, WHITE, True)
    add_text(
        slide,
        "交通映像解析の現在地を、\n「できること・課題・次の一手」で整理",
        0.82,
        2.65,
        6.50,
        1.10,
        19,
        PALE_BLUE,
        False,
        valign=MSO_ANCHOR.TOP,
    )
    add_rect(slide, 8.08, 1.52, 4.26, 3.78, fill=BLUE, radius=True)
    stages = [("1", "動画入力"), ("2", "AI解析"), ("3", "人の確認"), ("4", "結果出力")]
    for i, (num, label) in enumerate(stages):
        y = 1.92 + i * 0.78
        add_circle(slide, 8.48, y, 0.42, WHITE, num, BLUE, 10)
        add_text(slide, label, 9.08, y - 0.02, 2.52, 0.34, 15, WHITE, True)
        if i < len(stages) - 1:
            add_rect(slide, 8.68, y + 0.42, 0.03, 0.34, fill=PALE_BLUE, radius=False)
    add_text(slide, "2026.07.24｜現行DB・ソースコード確認", 0.82, 6.78, 5.50, 0.24, 10, MUTED, True)

    # 2. 現在できること
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=LIGHT, radius=False)
    add_title(slide, "現在できること", "動画の投入から安全指標の確認・出力まで、基本フローは一通り実装済みです。")
    cards = [
        ("01", "入力・設定", "動画／フォルダ登録\n現場別キャリブレーション", BLUE, PALE_BLUE),
        ("02", "検出・追跡", "YOLO＋ByteTrack\n車両・自転車・タイヤ", TEAL, PALE_TEAL),
        ("03", "安全指標", "速度・車間・白線距離\n離隔・追越し・TTC", ORANGE, PALE_ORANGE),
        ("04", "確認・出力", "手動補正UI\nExcel／CSV／解析動画", GREEN, PALE_TEAL),
    ]
    for i, (num, title, body, accent, pale) in enumerate(cards):
        x = 0.72 + i * 3.06
        add_rect(slide, x, 1.88, 2.78, 3.42, fill=WHITE, radius=True, line=LINE)
        add_rect(slide, x, 1.88, 2.78, 0.10, fill=accent, radius=False)
        add_pill(slide, num, x + 0.24, 2.18, 0.58, accent, size=9.5)
        add_text(slide, title, x + 0.24, 2.82, 2.28, 0.38, 16, NAVY, True)
        add_text(slide, body, x + 0.24, 3.46, 2.26, 0.90, 12, INK, False, valign=MSO_ANCHOR.TOP)
        add_rect(slide, x + 0.24, 4.70, 2.28, 0.34, fill=pale, radius=True)
        add_text(slide, "Web UIで一気通貫", x + 0.36, 4.75, 2.04, 0.22, 9.4, accent, True, PP_ALIGN.CENTER)
    add_rect(slide, 0.72, 5.78, 11.90, 0.60, fill=NAVY, radius=True)
    add_text(
        slide,
        "強み：AIだけで完結させず、人が検証・修正して再集計できる Human-in-the-loop",
        1.02,
        5.91,
        11.32,
        0.32,
        13,
        WHITE,
        True,
        PP_ALIGN.CENTER,
    )
    add_footer(slide, 2, "Source: ADC System 仕様書・現行ソースコード")

    # 3. 運用状況
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=LIGHT, radius=False)
    add_title(slide, "現在の運用状況", "現行データベースは大規模化しており、処理Runの大半は完了しています。")
    completion = status.completed / status.runs if status.runs else 0
    add_kpi(slide, 0.72, f"{status.videos:,}", "登録動画", "解析対象ファイル", BLUE)
    add_kpi(slide, 3.72, f"{status.detections / 1_000_000:.2f}M", "検出レコード", f"{status.detections:,}件", TEAL)
    add_kpi(slide, 6.72, f"{status.runs:,}", "処理Run", f"完了 {status.completed}件", ORANGE)
    add_kpi(slide, 9.72, f"{status.overtakes:,}", "追越しイベント", f"有効離隔 {status.valid_clearance}件", RED)
    add_rect(slide, 0.72, 4.18, 11.90, 1.66, fill=WHITE, radius=True, line=LINE)
    add_text(slide, "処理Runの完了率", 1.02, 4.48, 2.50, 0.34, 15, NAVY, True)
    add_text(slide, f"{completion * 100:.1f}%", 3.55, 4.38, 1.60, 0.56, 26, GREEN, True, font=FONT_NUM)
    add_rect(slide, 5.48, 4.57, 5.74, 0.22, fill=LINE, radius=True)
    add_rect(slide, 5.48, 4.57, 5.74 * completion, 0.22, fill=GREEN, radius=True)
    add_text(
        slide,
        f"完了 {status.completed}　／　処理中 {status.processing}　／　エラー {status.errors}",
        5.48,
        5.02,
        5.74,
        0.28,
        11,
        MID,
        True,
        PP_ALIGN.CENTER,
    )
    add_text(
        slide,
        "※ 検出レコード数はフレーム単位の観測数であり、ユニークな車両台数ではありません。",
        1.02,
        5.45,
        10.90,
        0.24,
        9.8,
        MUTED,
    )
    add_footer(slide, 3, "Source: db/my_app_data.db（2026-07-24確認）")

    # 4. 改善が必要な点
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=WHITE, radius=False)
    add_title(slide, "改善が必要な点", "優先度は「指標を正しく出す」→「品質を保証する」→「安定運用する」の順です。")
    add_issue(
        slide,
        1.80,
        "1",
        "速度・TTCの実績値",
        f"速度は{status.speed_nonnull:,}件、TTCは{status.ttc_nonnull:,}件が登録済みですが、現状はすべて0値。計算経路と校正値の再確認が必要です。",
        "最優先",
        RED,
        PALE_RED,
    )
    add_issue(
        slide,
        3.18,
        "2",
        "データ品質の見える化",
        f"追越し{status.overtakes}件に対して有効離隔は{status.valid_clearance}件。欠測・外れ値・手動修正の理由をレポート上で追跡できるようにします。",
        "高",
        ORANGE,
        PALE_ORANGE,
    )
    add_issue(
        slide,
        4.56,
        "3",
        "運用と保守の標準化",
        f"処理中{status.processing}件・エラー{status.errors}件の再実行導線、回帰テスト、ログ監視を整備し、変更後も同じ結果が出る状態を作ります。",
        "中",
        BLUE,
        PALE_BLUE,
    )
    add_footer(slide, 4, "Source: 現行DB監査・Git差分・テスト構成")

    # 5. 改善ロードマップ
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=LIGHT, radius=False)
    add_title(slide, "改善ロードマップ", "小さく直して数値で確認し、次の段階へ進む3ステップです。")
    add_roadmap_card(
        slide,
        0.72,
        "STEP 1",
        "計測を復旧",
        ["速度・TTCの0値原因を特定", "代表動画で期待値と比較", "再計算手順を固定"],
        "成果：主要指標が使える",
        RED,
        PALE_RED,
    )
    add_roadmap_card(
        slide,
        4.79,
        "STEP 2",
        "品質を保証",
        ["欠測・外れ値の自動チェック", "追越しイベントの二重確認", "指標ごとの合格基準を設定"],
        "成果：説明可能なデータ",
        ORANGE,
        PALE_ORANGE,
    )
    add_roadmap_card(
        slide,
        8.86,
        "STEP 3",
        "運用を安定化",
        ["失敗Runの再実行を簡単に", "回帰テストを自動化", "ログ・DBバックアップを監視"],
        "成果：継続運用できる",
        TEAL,
        PALE_TEAL,
    )
    add_rect(slide, 0.82, 6.56, 11.68, 0.48, fill=NAVY, radius=True)
    add_text(
        slide,
        "最初の判断ポイント：代表動画3本で速度・TTCが妥当値になることを確認",
        1.08,
        6.65,
        11.16,
        0.28,
        12,
        WHITE,
        True,
        PP_ALIGN.CENTER,
    )
    add_footer(slide, 5)
    return prs


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    status = load_status()
    prs = make_presentation(status)
    prs.save(OUT_PATH)
    print(f"saved: {OUT_PATH}")
    print(f"slides: {len(prs.slides)}")


if __name__ == "__main__":
    main()
