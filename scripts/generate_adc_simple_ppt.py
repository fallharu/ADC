"""シンプル版のADC情報可視化デッキと発表カンペを生成する。"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt as DocPt
from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches

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
    ORANGE,
    OUT_DIR,
    PALE_BLUE,
    PALE_ORANGE,
    PALE_RED,
    PALE_TEAL,
    RED,
    SLIDE_H,
    SLIDE_W,
    TEAL,
    UNWIDENED,
    WHITE,
    WIDENED,
    add_circle,
    add_footer,
    add_picture,
    add_pill,
    add_rect,
    add_text,
    load_stats,
    mann_whitney_p,
    prepare_assets,
)


PPTX_PATH = OUT_DIR / "ADC_交通映像解析_シンプル版_カンペ付き.pptx"
CUE_DOCX_PATH = OUT_DIR / "ADC_交通映像解析_発表カンペ.docx"


@dataclass(frozen=True)
class Cue:
    title: str
    duration: str
    script: str
    emphasis: str
    transition: str

    @property
    def notes_text(self) -> str:
        return (
            f"【目安】{self.duration}\n\n"
            f"【話す内容】\n{self.script}\n\n"
            f"【強調する言葉】\n{self.emphasis}\n\n"
            f"【次へのつなぎ】\n{self.transition}"
        )


def add_notes(slide, cue: Cue) -> None:
    text_frame = slide.notes_slide.notes_text_frame
    if text_frame is None:
        return
    text_frame.clear()
    text_frame.text = cue.notes_text


def add_simple_title(slide, title: str, lead: str | None = None, dark: bool = False) -> None:
    title_color = WHITE if dark else NAVY
    lead_color = PALE_BLUE if dark else MID
    add_text(slide, title, 0.70, 0.50, 11.95, 0.64, 28, title_color, True, valign=MSO_ANCHOR.TOP)
    if lead:
        add_text(slide, lead, 0.72, 1.14, 11.80, 0.52, 13.5, lead_color, False, valign=MSO_ANCHOR.TOP)


def add_numbered_row(slide, y, number, heading, metric, body, accent):
    add_circle(slide, 0.82, y + 0.08, 0.52, accent, number, WHITE, 13)
    add_text(slide, heading, 1.54, y, 2.42, 0.34, 14, NAVY, True)
    add_text(slide, metric, 4.02, y - 0.04, 2.70, 0.43, 21, accent, True, font=FONT_NUM)
    add_text(slide, body, 6.92, y - 0.02, 5.55, 0.52, 12.5, INK, False, valign=MSO_ANCHOR.TOP)
    add_rect(slide, 1.54, y + 0.67, 10.86, 0.018, fill=LINE, radius=False)


def add_small_kpi(slide, x, value, label, accent, note):
    add_rect(slide, x, 1.82, 2.78, 1.72, fill=WHITE, radius=True, line=LINE)
    add_rect(slide, x, 1.82, 0.08, 1.72, fill=accent, radius=False)
    add_text(slide, value, x + 0.26, 2.02, 2.24, 0.60, 28, NAVY, True, font=FONT_NUM)
    add_text(slide, label, x + 0.26, 2.67, 2.24, 0.30, 12, MID, True)
    add_text(slide, note, x + 0.26, 3.08, 2.24, 0.22, 9.2, MUTED)


def add_band_bar(slide, y, label, values, total, label_color):
    colors = (RED, ORANGE, TEAL, BLUE)
    add_text(slide, label, 0.94, y - 0.03, 0.90, 0.30, 12.5, label_color, True)
    x = 1.92
    width = 5.08
    for value, fill in zip(values, colors):
        w = width * value / total
        add_rect(slide, x, y, w, 0.46, fill=fill, radius=False)
        if w > 0.62:
            add_text(slide, f"{value/total*100:.1f}%", x, y, w, 0.46, 9.5, WHITE, True, PP_ALIGN.CENTER)
        x += w


def build_cues(
    widened_rate: float,
    unwidened_rate: float,
    widened_median: float,
    unwidened_median: float,
    widened_low: float,
    unwidened_low: float,
    p_value: float,
) -> list[Cue]:
    return [
        Cue(
            "単眼カメラ映像から、追越し時の安全余裕を可視化",
            "40秒",
            "本日はADCシステムを使い、単眼カメラ映像から追越し時の安全余裕を可視化した結果をご紹介します。従来の交通調査は台数や車種の集計が中心ですが、この分析では車と自転車の間にどれだけ距離があったかまで残します。最初に結論をお伝えし、その後に仕組みと注意点を説明します。",
            "件数だけでなく、安全余裕を距離で見る",
            "まず、今回のデータから分かったことを3点に絞ります。",
        ),
        Cue(
            "まず、分かったこと",
            "70秒",
            f"結論は3点です。1つ目は、追越し頻度が拡幅で{widened_rate:.1f}件、未拡幅で{unwidened_rate:.1f}件と、動画1時間あたりではほぼ同程度だったことです。2つ目は、離隔距離の中央値が拡幅{widened_median:.2f}メートル、未拡幅{unwidened_median:.2f}メートルで、拡幅側が0.16メートル大きかったことです。3つ目は、1.5メートル未満の割合が拡幅{widened_low*100:.1f}パーセントに対して未拡幅{unwidened_low*100:.1f}パーセントだったことです。ただし有効データは43件なので、因果ではなく傾向として読みます。",
            "頻度は同等、差は安全余裕に現れる兆候",
            "この数字をどのように作ったのか、ADCの処理の流れを説明します。",
        ),
        Cue(
            "ADCは何をするシステムか",
            "60秒",
            "ADCは、動画の登録から結果出力までを一つの流れで扱う交通映像解析システムです。まずカメラ映像に距離情報を与える幾何校正を行い、YOLOとByteTrackで車両や自転車を検出・追跡します。その後、離隔距離、接近距離、白線との距離、追越しイベントなどを計算します。重要なのはAIだけで完結させず、人がイベントを確認・修正でき、修正後の指標を再計算できる点です。",
            "AIが候補を出し、人が確認・修正できる",
            "次に、今回この仕組みに入っているデータ規模を確認します。",
        ),
        Cue(
            "今回扱ったデータ",
            "50秒",
            "現行データベースには169本の動画、約121万件の検出レコード、251件の処理Run、47件の追越しイベントがあります。処理Runのうち245件が完了しており、完了率は97.6パーセントです。ここでいう検出レコードはユニークな車両台数ではなく、各フレームで対象を観測した記録です。したがって、121万件を交通量としてそのまま解釈しないことが大切です。",
            "121万件はフレーム単位の観測記録",
            "このデータから、追越し時の離隔距離をどのように計測したかを見ます。",
        ),
        Cue(
            "離隔距離は、追越し時の横方向の余裕",
            "60秒",
            "画面の白い枠が追越す車両、青い枠が自転車です。各対象の計測点を赤点と青点で示し、その横方向の最短距離を離隔距離として記録します。画面上のピクセルをメートルへ変換するため、事前に道路の白線や実距離を使ってキャリブレーションしています。この代表写真は各道路区分の中央値に近いイベントで、全体の結論は1枚の写真ではなく43件の分布から判断します。",
            "1枚の写真ではなく、イベント分布で比較する",
            "続いて、拡幅と未拡幅の分布を同じ条件で比べます。",
        ),
        Cue(
            "拡幅と未拡幅の比較",
            "75秒",
            f"追越し頻度はほぼ同じでしたが、離隔距離には差の兆候がありました。中央値は拡幅{widened_median:.2f}メートル、未拡幅{unwidened_median:.2f}メートルです。また1.5メートル未満は拡幅{widened_low*100:.1f}パーセント、未拡幅{unwidened_low*100:.1f}パーセントでした。平均値は拡幅側の大きな外れ値に影響されるため、中央値と距離帯の割合を重視します。検定のp値は{p_value:.3f}で、5パーセント水準には届いていません。したがって『拡幅で離隔が広い傾向』までが適切な表現です。",
            "未拡幅で狭い離隔が多いが、まだ傾向段階",
            "最後に、この結果から言えることと言えないことを整理します。",
        ),
        Cue(
            "結果の読み方と注意点",
            "60秒",
            "今回のデータからは、追越し頻度がほぼ同程度である一方、未拡幅では狭い離隔の割合が高い傾向を確認できます。ただし有効離隔43件は35動画から得られたもので、完全に独立とは限りません。47件中4件は欠測で、比較対象は一つの走行方向です。現行DBでは速度とTTCの正の値がなく、モデルのconfidenceも正解率ではありません。道路拡幅の因果効果を断定するには、条件を揃えた追加データが必要です。",
            "言えることと、まだ言えないことを分ける",
            "以上を踏まえて、今後の改善と活用方針をまとめます。",
        ),
        Cue(
            "まとめと次の一手",
            "45秒",
            "ADCによって、交通映像を台数の集計だけでなく、追越し時の安全余裕まで含むデータに変換できます。今回の分析では、未拡幅区間で狭い離隔が多い傾向が見えました。次は速度とTTCの計測を復旧し、47イベントを二重レビューし、地点・方向・時間帯を揃えた比較を増やします。これにより、映像を道路改善の優先順位を考える定量根拠へつなげます。",
            "件数から安全余裕へ、映像を道路改善の根拠に",
            "ご説明は以上です。ご質問をお願いします。",
        ),
    ]


def make_presentation() -> tuple[Presentation, list[Cue]]:
    stats = load_stats()
    assets = prepare_assets()
    widened = stats.clearance["拡幅"]
    unwidened = stats.clearance["未拡幅"]
    widened_median = statistics.median(widened)
    unwidened_median = statistics.median(unwidened)
    widened_mean = statistics.mean(widened)
    unwidened_mean = statistics.mean(unwidened)
    widened_low = sum(v < 1.5 for v in widened) / len(widened)
    unwidened_low = sum(v < 1.5 for v in unwidened) / len(unwidened)
    widened_rate = stats.road_events["拡幅"] / stats.road_hours["拡幅"]
    unwidened_rate = stats.road_events["未拡幅"] / stats.road_hours["未拡幅"]
    p_value = mann_whitney_p(widened, unwidened)
    cues = build_cues(
        widened_rate,
        unwidened_rate,
        widened_median,
        unwidened_median,
        widened_low,
        unwidened_low,
        p_value,
    )

    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    prs.core_properties.title = "ADC交通映像解析｜シンプル版（カンペ付き）"
    prs.core_properties.subject = "単眼カメラ映像から追越し安全性を可視化"
    prs.core_properties.author = "ADC System"
    prs.core_properties.comments = "各スライドの発表者ノートにカンペを収録。"
    blank = prs.slide_layouts[6]

    # 1. 表紙
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=NAVY, radius=False)
    add_picture(slide, assets["event_widened"], 7.82, 1.14, 4.82, 2.65, line=None)
    add_pill(slide, "ADC 交通映像解析", 0.74, 0.72, 1.82, BLUE, size=10.5)
    add_text(slide, "単眼カメラ映像から、\n追越し時の安全余裕を可視化", 0.74, 1.54, 6.50, 1.58, 35, WHITE, True, valign=MSO_ANCHOR.TOP)
    add_text(slide, "車と自転車の間に、どれだけ距離があったか。\n169本の動画と47件の追越しイベントから整理します。", 0.78, 3.48, 6.25, 0.86, 16, PALE_BLUE, False, valign=MSO_ANCHOR.TOP)
    add_rect(slide, 7.82, 4.20, 4.82, 1.12, fill=BLUE, radius=True)
    add_text(slide, "件数の把握から、\n安全余裕の把握へ", 8.08, 4.40, 4.30, 0.66, 18, WHITE, True, PP_ALIGN.CENTER, valign=MSO_ANCHOR.TOP)
    add_text(slide, "ADC System｜2026.07", 0.78, 6.72, 4.2, 0.25, 10, MUTED, True)
    add_notes(slide, cues[0])

    # 2. まず、分かったこと
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=WHITE, radius=False)
    add_simple_title(slide, "まず、分かったこと", "今回の比較では、追越しの回数よりも“車と自転車の間の余裕”に差が現れました。")
    add_rect(slide, 0.70, 1.68, 11.92, 0.62, fill=PALE_BLUE, radius=True)
    add_text(slide, "結論：追越し頻度はほぼ同じ。未拡幅では、狭い離隔が多い傾向。", 0.98, 1.80, 11.35, 0.34, 15, NAVY, True, PP_ALIGN.CENTER)
    add_numbered_row(slide, 2.66, "1", "追越し頻度", f"{widened_rate:.1f} vs {unwidened_rate:.1f} 件/時", "動画時間で補正すると、拡幅と未拡幅で大きな差はありません。", BLUE)
    add_numbered_row(slide, 3.68, "2", "離隔距離の中央値", f"{widened_median:.2f} vs {unwidened_median:.2f} m", "拡幅側が0.16m大きく、より広い余裕がある方向です。", TEAL)
    add_numbered_row(slide, 4.70, "3", "1.5m未満", f"{widened_low*100:.1f}% vs {unwidened_low*100:.1f}%", "未拡幅では、狭い離隔の割合が約5倍でした。", ORANGE)
    add_rect(slide, 0.82, 6.16, 11.54, 0.56, fill=LIGHT, radius=True)
    add_text(slide, "有効離隔43件の記述的比較です。結果は“傾向”として読み、因果は断定しません。", 1.02, 6.27, 11.14, 0.30, 11.5, MID, True, PP_ALIGN.CENTER)
    add_footer(slide, 2, "Source: 現行DB｜拡幅97動画・未拡幅69動画・有効離隔43件")
    add_notes(slide, cues[1])

    # 3. ADCは何をするシステムか
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=LIGHT, radius=False)
    add_simple_title(slide, "ADCは何をするシステムか", "動画の登録から距離計測、人の確認、データ出力までを一つの流れで扱います。")
    add_rect(slide, 0.72, 1.70, 11.90, 0.92, fill=WHITE, radius=True)
    add_text(slide, "単眼カメラの映像に距離情報を与え、車両と自転車を検出・追跡します。追越し候補はAIが抽出し、人が映像を確認・修正できる仕組みです。", 1.00, 1.88, 11.32, 0.54, 13.5, INK, False, PP_ALIGN.CENTER)
    steps = [
        ("1", "動画入力・校正"),
        ("2", "検出・追跡"),
        ("3", "距離・追越し算出"),
        ("4", "人の確認・出力"),
    ]
    accents = (BLUE, TEAL, ORANGE, GREEN)
    for i, ((num, label), accent) in enumerate(zip(steps, accents)):
        x = 0.74 + i * 3.00
        add_rect(slide, x, 3.03, 2.66, 1.44, fill=WHITE, radius=True, line=LINE)
        add_circle(slide, x + 0.18, 3.22, 0.40, accent, num, WHITE, 10)
        add_text(slide, label, x + 0.68, 3.47, 1.74, 0.48, 13, NAVY, True, PP_ALIGN.CENTER)
        if i < 3:
            add_text(slide, "→", x + 2.68, 3.49, 0.28, 0.28, 14, MUTED, True, PP_ALIGN.CENTER)
    add_rect(slide, 0.74, 5.02, 11.72, 1.08, fill=NAVY, radius=True)
    add_text(slide, "ポイント", 1.02, 5.28, 1.18, 0.32, 13, CYAN, True)
    add_text(slide, "AI任せにせず、人の確認結果を反映して指標を再計算します。これにより、追越しイベントの根拠と修正履歴を残せます。", 2.20, 5.19, 9.86, 0.58, 13, WHITE, True, valign=MSO_ANCHOR.TOP)
    add_footer(slide, 3, "Source: ADC System 実装構成を要約")
    add_notes(slide, cues[2])

    # 4. 今回扱ったデータ
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=LIGHT, radius=False)
    add_simple_title(slide, "今回扱ったデータ", "現行データベースの規模と処理状態を、4つの数字で確認します。")
    add_small_kpi(slide, 0.72, f"{stats.videos:,}", "動画", BLUE, "実映像ファイル")
    add_small_kpi(slide, 3.72, f"{stats.detections/1_000_000:.2f}M", "検出レコード", TEAL, f"{stats.detections:,}件")
    add_small_kpi(slide, 6.72, f"{stats.runs:,}", "処理Run", ORANGE, f"完了 {stats.completed}件")
    add_small_kpi(slide, 9.72, f"{stats.overtakes:,}", "追越しイベント", RED, "有効離隔 43件")
    add_rect(slide, 0.72, 3.92, 7.60, 2.10, fill=WHITE, radius=True)
    add_text(slide, "この数字を読むときの注意", 1.02, 4.18, 3.20, 0.34, 15, NAVY, True)
    add_text(slide, "121万件はユニークな車両台数ではありません。動画の各フレームで車や自転車を観測した記録の合計です。交通量として使う場合は、追跡IDや通過イベントにまとめてから集計します。", 1.02, 4.65, 6.92, 0.90, 12.5, INK, False, valign=MSO_ANCHOR.TOP)
    add_text(slide, "道路区分付き166動画：拡幅97本／未拡幅69本（区分なし3本）", 1.02, 5.54, 6.92, 0.27, 10.2, BLUE, True)
    add_rect(slide, 8.58, 3.92, 4.04, 2.10, fill=WHITE, radius=True)
    completion = stats.completed / stats.runs
    add_text(slide, "処理Runの完了率", 8.90, 4.18, 2.46, 0.34, 15, NAVY, True)
    add_text(slide, f"{completion*100:.1f}%", 8.90, 4.68, 2.02, 0.54, 28, GREEN, True, font=FONT_NUM)
    add_rect(slide, 8.90, 5.35, 3.26, 0.20, fill=LINE, radius=True)
    add_rect(slide, 8.90, 5.35, 3.26 * completion, 0.20, fill=GREEN, radius=True)
    add_text(slide, f"完了 {stats.completed}／処理中 {stats.processing}／エラー {stats.errors}", 8.90, 5.67, 3.26, 0.24, 9.5, MID, True, PP_ALIGN.CENTER)
    add_footer(slide, 4)
    add_notes(slide, cues[3])

    # 5. 離隔距離の見方
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=WHITE, radius=False)
    add_simple_title(slide, "離隔距離は、追越し時の横方向の余裕", "画像上の計測点を実距離へ変換し、車と自転車の最短距離をイベントごとに記録します。")
    add_picture(slide, assets["event_widened"], 0.72, 1.80, 7.08, 3.90)
    add_pill(slide, "代表イベント｜2.01m", 0.94, 1.98, 1.88, WIDENED, size=10.5)
    add_rect(slide, 8.12, 1.80, 4.50, 3.90, fill=LIGHT, radius=True)
    explanations = [
        ("1", "対象を追跡", "白い枠が車両、青い枠が自転車です。", BLUE),
        ("2", "計測点を決定", "車体と自転車の位置を赤点・青点で表します。", TEAL),
        ("3", "距離を記録", "横方向の最短距離をメートル単位で保存します。", ORANGE),
    ]
    for i, (num, heading, body, accent) in enumerate(explanations):
        y = 2.22 + i * 0.94
        add_circle(slide, 8.44, y, 0.42, accent, num, WHITE, 10)
        add_text(slide, heading, 9.00, y - 0.02, 2.66, 0.30, 12.8, NAVY, True)
        add_text(slide, body, 9.00, y + 0.30, 3.08, 0.42, 10.7, MID, False, valign=MSO_ANCHOR.TOP)
    add_rect(slide, 8.44, 5.06, 3.84, 0.40, fill=PALE_ORANGE, radius=True)
    add_text(slide, "1.5mは比較用の参考帯です", 8.62, 5.10, 3.48, 0.26, 10.5, ORANGE, True, PP_ALIGN.CENTER)
    add_rect(slide, 0.72, 6.02, 11.90, 0.50, fill=PALE_BLUE, radius=True)
    add_text(slide, "代表写真は説明用です。道路区分の比較は、全43件の離隔距離から判断します。", 0.98, 6.11, 11.36, 0.28, 11.5, NAVY, True, PP_ALIGN.CENTER)
    add_footer(slide, 5, "Source: 代表フレーム｜車両番号はぼかし済み")
    add_notes(slide, cues[4])

    # 6. 拡幅と未拡幅の比較
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=LIGHT, radius=False)
    add_simple_title(slide, "拡幅と未拡幅を比べると", "頻度はほぼ同じですが、未拡幅では狭い離隔の割合が高くなっています。")
    add_rect(slide, 0.72, 1.74, 7.08, 3.62, fill=WHITE, radius=True)
    add_text(slide, "離隔距離帯の構成比", 1.02, 2.02, 3.12, 0.34, 15, NAVY, True)
    bins_w = [sum(v < 1.5 for v in widened), sum(1.5 <= v < 2 for v in widened), sum(2 <= v < 2.5 for v in widened), sum(v >= 2.5 for v in widened)]
    bins_u = [sum(v < 1.5 for v in unwidened), sum(1.5 <= v < 2 for v in unwidened), sum(2 <= v < 2.5 for v in unwidened), sum(v >= 2.5 for v in unwidened)]
    add_band_bar(slide, 2.76, "拡幅", bins_w, len(widened), WIDENED)
    add_band_bar(slide, 3.70, "未拡幅", bins_u, len(unwidened), UNWIDENED)
    legend = [("<1.5m", RED), ("1.5–2.0m", ORANGE), ("2.0–2.5m", TEAL), ("2.5m以上", BLUE)]
    for i, (label, accent) in enumerate(legend):
        x = 1.02 + i * 1.58
        add_circle(slide, x, 4.70, 0.16, accent)
        add_text(slide, label, x + 0.23, 4.64, 1.20, 0.25, 9, MID)
    add_rect(slide, 8.10, 1.74, 4.52, 3.62, fill=WHITE, radius=True)
    add_text(slide, "主な数字", 8.44, 2.02, 2.00, 0.34, 15, NAVY, True)
    rows = [
        ("追越し頻度", f"{widened_rate:.1f}", f"{unwidened_rate:.1f}", "件/時"),
        ("中央値", f"{widened_median:.2f}", f"{unwidened_median:.2f}", "m"),
        ("1.5m未満", f"{widened_low*100:.1f}", f"{unwidened_low*100:.1f}", "%"),
    ]
    add_text(slide, "指標", 8.44, 2.48, 1.42, 0.24, 9.5, MUTED, True)
    add_text(slide, "拡幅", 10.02, 2.48, 0.82, 0.24, 9.5, WIDENED, True, PP_ALIGN.CENTER)
    add_text(slide, "未拡幅", 11.03, 2.48, 0.92, 0.24, 9.5, UNWIDENED, True, PP_ALIGN.CENTER)
    for i, (label, a, b, unit) in enumerate(rows):
        y = 2.86 + i * 0.50
        add_text(slide, label, 8.44, y, 1.46, 0.26, 10.5, INK, True)
        add_text(slide, f"{a}{unit}", 9.91, y, 1.06, 0.26, 11.5, WIDENED, True, PP_ALIGN.CENTER, font=FONT_NUM)
        add_text(slide, f"{b}{unit}", 11.00, y, 1.12, 0.26, 11.5, UNWIDENED, True, PP_ALIGN.CENTER, font=FONT_NUM)
    add_rect(slide, 0.72, 5.72, 11.90, 0.74, fill=NAVY, radius=True)
    add_text(slide, f"読み方：未拡幅で狭い離隔が多い“傾向”。検定 p={p_value:.3f} のため、因果や効果は断定しません。", 1.00, 5.87, 11.34, 0.38, 12.5, WHITE, True, PP_ALIGN.CENTER)
    add_footer(slide, 6, "Source: 有効離隔43件（拡幅24／未拡幅19）")
    add_notes(slide, cues[5])

    # 7. 結果の読み方と注意点
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=WHITE, radius=False)
    add_simple_title(slide, "結果の読み方と注意点", "調査結果として使うには、“ここまで言える”と“まだ言えない”を分けることが重要です。")
    add_rect(slide, 0.72, 1.80, 5.72, 4.38, fill=PALE_TEAL, radius=True)
    add_pill(slide, "ここまで言える", 1.02, 2.08, 1.60, TEAL, size=11)
    add_text(slide, "追越し頻度は、動画時間で補正するとほぼ同程度でした。", 1.02, 2.78, 4.96, 0.66, 15, NAVY, True, valign=MSO_ANCHOR.TOP)
    add_text(slide, "一方で、未拡幅では1.5m未満の離隔が多く、中央値も小さい結果です。したがって、未拡幅で安全余裕が小さい傾向がある、という読み方はできます。", 1.02, 3.66, 4.96, 1.30, 13, INK, False, valign=MSO_ANCHOR.TOP)
    add_text(slide, "有効離隔：43件（35動画由来）", 1.02, 5.44, 3.26, 0.34, 12, TEAL, True)

    add_rect(slide, 6.80, 1.80, 5.82, 4.38, fill=PALE_ORANGE, radius=True)
    add_pill(slide, "まだ言えない", 7.10, 2.08, 1.60, ORANGE, size=11)
    add_text(slide, "道路拡幅が原因で安全性が改善した、とまでは断定できません。", 7.10, 2.78, 5.00, 0.66, 15, NAVY, True, valign=MSO_ANCHOR.TOP)
    add_text(slide, "4件の離隔欠測があり、比較は1方向のみです。現行DBでは速度とTTCの正の値がないため、実績評価には使えません。処理完了率やconfidenceも解析精度ではありません。", 7.10, 3.66, 5.00, 1.30, 13, INK, False, valign=MSO_ANCHOR.TOP)
    add_text(slide, f"検定：p={p_value:.3f}", 7.10, 5.44, 2.10, 0.34, 12, ORANGE, True)
    add_footer(slide, 7, "Source: 現行DBの欠測・0値監査｜速度・TTCは今回の実績評価から除外")
    add_notes(slide, cues[6])

    # 8. まとめ
    slide = prs.slides.add_slide(blank)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=NAVY, radius=False)
    add_simple_title(slide, "まとめと次の一手", "ADCは、交通映像を“件数”だけでなく“安全余裕”まで含むデータへ変えます。", dark=True)
    summary_rows = [
        ("1", "今回分かったこと", "未拡幅では、狭い離隔が多い傾向が見えました。", BLUE),
        ("2", "今回の注意点", "有効データは43件。因果ではなく傾向として扱います。", ORANGE),
        ("3", "次に行うこと", "速度・TTCの復旧、二重レビュー、条件を揃えた比較を進めます。", TEAL),
    ]
    for i, (num, heading, body, accent) in enumerate(summary_rows):
        y = 1.92 + i * 1.17
        add_circle(slide, 0.86, y, 0.54, accent, num, WHITE, 13)
        add_text(slide, heading, 1.62, y - 0.02, 2.66, 0.36, 15, WHITE, True)
        add_text(slide, body, 4.22, y - 0.02, 7.86, 0.54, 14, PALE_BLUE, False, valign=MSO_ANCHOR.TOP)
        if i < 2:
            add_rect(slide, 1.62, y + 0.78, 10.48, 0.018, fill=MUTED, radius=False)
    add_rect(slide, 0.78, 5.75, 11.78, 0.76, fill=BLUE, radius=True)
    add_text(slide, "件数から安全余裕へ —— 映像を、道路改善の定量根拠に。", 1.04, 5.89, 11.26, 0.44, 20, WHITE, True, PP_ALIGN.CENTER)
    add_text(slide, "ADC System｜実データ可視化 2026-07", 0.80, 6.92, 5.6, 0.22, 9.5, MUTED, True)
    add_notes(slide, cues[7])

    return prs, cues


def make_cue_docx(cues: list[Cue]) -> None:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(1.6)
    section.bottom_margin = Cm(1.6)
    section.left_margin = Cm(1.8)
    section.right_margin = Cm(1.8)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = DocPt(12)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    for style_name in ("Title", "Heading 1", "Heading 2"):
        style = doc.styles[style_name]
        style.font.name = FONT
        style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

    title = doc.add_heading("ADC交通映像解析｜発表カンペ", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph("8枚・約7分を想定。PowerPointの発表者ノートにも同じ内容を収録しています。")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_page_break()

    for i, cue in enumerate(cues, 1):
        doc.add_heading(f"スライド{i}｜{cue.title}", level=1)
        p = doc.add_paragraph()
        run = p.add_run(f"目安：{cue.duration}")
        run.bold = True

        doc.add_heading("話す内容", level=2)
        doc.add_paragraph(cue.script)

        doc.add_heading("強調する言葉", level=2)
        p = doc.add_paragraph(cue.emphasis)
        p.runs[0].bold = True

        doc.add_heading("次へのつなぎ", level=2)
        doc.add_paragraph(cue.transition)

        if i != len(cues):
            doc.add_page_break()

    doc.save(CUE_DOCX_PATH)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prs, cues = make_presentation()
    prs.save(PPTX_PATH)
    make_cue_docx(cues)
    print(f"saved: {PPTX_PATH}")
    print(f"saved: {CUE_DOCX_PATH}")
    print(f"slides: {len(prs.slides)} / cues: {len(cues)}")


if __name__ == "__main__":
    main()
