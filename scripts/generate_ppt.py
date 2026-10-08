from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor

def create_presentation():
    prs = Presentation()

    # --- 共通設定 ---
    def set_font(run, size, bold=False):
        run.font.size = Pt(size)
        run.font.name = 'メイリオ' # Windows標準の日本語フォント
        run.font.bold = bold

    # --- 1. タイトルスライド ---
    slide_layout = prs.slide_layouts[0] # Title Slide
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    subtitle = slide.placeholders[1]

    title.text = "ADCシステム 概要資料"
    subtitle.text = "交通流調査・安全解析のためのAI自動化ソリューション"
    
    # フォント調整
    for paragraph in title.text_frame.paragraphs:
        for run in paragraph.runs:
            set_font(run, 44, True)
    for paragraph in subtitle.text_frame.paragraphs:
        for run in paragraph.runs:
            set_font(run, 24)


    # --- 2. システム概要 ---
    slide_layout = prs.slide_layouts[1] # Title and Content
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    content = slide.placeholders[1]

    title.text = "システム概要"
    tf = content.text_frame
    tf.text = "コンセプト: 交通流調査や安全解析を効率化するAIシステム"

    p = tf.add_paragraph()
    p.text = "スコープ: 車両・自転車の検出、追跡、速度計測、距離計測を一気通貫で実施"
    p.level = 0
    
    p = tf.add_paragraph()
    p.text = "主なターゲット:"
    p = tf.add_paragraph()
    p.text = "交通コンサルタント、道路管理者、研究機関"
    p.level = 1

    # --- 3. ワークフロー ---
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    content = slide.placeholders[1]

    title.text = "解析ワークフロー"
    tf = content.text_frame
    tf.text = "1. 入力 (Input)"
    p = tf.add_paragraph()
    p.text = "動画ファイルの読み込み（フォルダ一括処理 / 個別ファイル指定）"
    p.level = 1

    p = tf.add_paragraph()
    p.text = "2. 設定 (Setup)"
    p = tf.add_paragraph()
    p.text = "キャリブレーション（カメラアングル補正、車線幅設定）"
    p.level = 1

    p = tf.add_paragraph()
    p.text = "3. 解析 (Process)"
    p = tf.add_paragraph()
    p.text = "AIによる物体検出 & ロジック計算（速度推定・距離計測）"
    p.level = 1

    p = tf.add_paragraph()
    p.text = "4. 検証 (Verify)"
    p = tf.add_paragraph()
    p.text = "手動補正ツールによる目視確認（データの信頼性を担保）"
    p.level = 1
    
    p = tf.add_paragraph()
    p.text = "5. 出力 (Output)"
    p = tf.add_paragraph()
    p.text = "レポート出力（Excel/CSV/アノテーション動画）"
    p.level = 1


    # --- 4. 特徴1：柔軟なキャリブレーション ---
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    content = slide.placeholders[1]

    title.text = "特徴1：柔軟なキャリブレーション"
    tf = content.text_frame
    tf.text = "画面上のピクセルを現実空間のメートル単位へ高精度に変換"
    
    p = tf.add_paragraph()
    p.text = "簡単なWeb UI操作"
    p.level = 1
    p = tf.add_paragraph()
    p.text = "画面上で白線をなぞるだけでスケール計算が可能"
    p.level = 2

    p = tf.add_paragraph()
    p.text = "設定のプロファイル保存"
    p.level = 1
    p = tf.add_paragraph()
    p.text = "定点カメラなどで同じ設定を繰り返し利用可能"
    p.level = 2
    p = tf.add_paragraph()
    p.text = "設置角度や高さが異なる映像にも柔軟に対応"
    p.level = 2


    # --- 5. 特徴2：高度な解析指標 ---
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    content = slide.placeholders[1]

    title.text = "特徴2：高度な解析指標（追い越し・離隔）"
    tf = content.text_frame
    tf.text = "「自動車による自転車の追い越し」イベントを自動抽出"

    p = tf.add_paragraph()
    p.text = "離隔距離 (Clearance Distance)"
    p.level = 1
    p = tf.add_paragraph()
    p.text = "車両と自転車の間の最短距離をセンチメートル単位で算出"
    p.level = 2
    
    p = tf.add_paragraph()
    p.text = "白線からの距離 (Line Distance)"
    p.level = 1
    p = tf.add_paragraph()
    p.text = "車両が走行レーン内のどの位置を走っているかを定量化"
    p.level = 2

    p = tf.add_paragraph()
    p.text = "速度差・相対速度"
    p.level = 1
    p = tf.add_paragraph()
    p.text = "追い越し時の速度差や危険度を評価"
    p.level = 2


    # --- 6. 特徴3：手動検証・補正機能 ---
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    content = slide.placeholders[1]

    title.text = "特徴3：手動検証・補正 (Human-in-the-loop)"
    tf = content.text_frame
    tf.text = "AIの完全自動化ではない、人が最終判断を行う設計思想"

    p = tf.add_paragraph()
    p.text = "イベント編集機能"
    p.level = 1
    p = tf.add_paragraph()
    p.text = "AIによる誤検知を削除、または未検知を手動で追加"
    p.level = 2
    
    p = tf.add_paragraph()
    p.text = "データの信頼性確保"
    p.level = 1
    p = tf.add_paragraph()
    p.text = "学術研究や行政報告にも利用可能な、100%正確なデータセットを作成可能"
    p.level = 2
    p = tf.add_paragraph()
    p.text = "修正履歴の管理と再計算の自動化"
    p.level = 2


    # --- 7. 出力・レポート機能 ---
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    content = slide.placeholders[1]

    title.text = "豊富な出力機能"
    tf = content.text_frame
    tf.text = "Global Summary ダッシュボード"
    p = tf.add_paragraph()
    p.text = "全体の傾向（平均速度、追い越し回数、対向車比率など）を一目で確認"
    p.level = 1

    p = tf.add_paragraph()
    p.text = "Excel / CSV 出力"
    p.level = 0
    p = tf.add_paragraph()
    p.text = "全フレーム・全車両の詳細データを出力。二次分析やグラフ作成に最適"
    p.level = 1

    p = tf.add_paragraph()
    p.text = "アノテーション動画"
    p.level = 0
    p = tf.add_paragraph()
    p.text = "バウンディングボックス、ID、速度、距離情報を映像にオーバーレイ表示"
    p.level = 1


    # --- 7. 出力・レポート機能 (グラフ付き) ---
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    content = slide.placeholders[1]
    title.text = "分析結果の可視化例"
    content.text = "自動生成される統計データのイメージ"

    # グラフの追加 (サンプルデータ)
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE

    chart_data = CategoryChartData()
    chart_data.categories = ['Run 1', 'Run 2', 'Run 3']
    chart_data.add_series('平均速度 (km/h)', (45.2, 52.1, 48.8))
    chart_data.add_series('追い越し回数', (12, 8, 15))

    # グラフを配置 (左下)
    x, y, cx, cy = Inches(0.5), Inches(3.5), Inches(4.5), Inches(3.0)
    slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, x, y, cx, cy, chart_data
    )

    # 画像プレースホルダー (右下)
    # 実際の画像がある場合は slide.shapes.add_picture(path, ...) を使用します
    # ここではイメージとして矩形を配置
    x, y, cx, cy = Inches(5.5), Inches(3.5), Inches(4.0), Inches(3.0)
    shape = slide.shapes.add_shape(
        1, x, y, cx, cy # 1 = MSO_SHAPE.RECTANGLE
    )
    shape.text = "ここにアノテーション動画の\nサムネイル画像を挿入"
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(200, 200, 200)


    # --- 8. まとめ ---
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    content = slide.placeholders[1]

    title.text = "まとめ"
    tf = content.text_frame
    tf.text = "高効率 (High Efficiency)"
    p = tf.add_paragraph()
    p.text = "GPU対応による高速バッチ処理で、大量の動画データを短時間で解析"
    p.level = 1

    p = tf.add_paragraph()
    p.text = "高精度 (High Precision)"
    p.level = 0
    p = tf.add_paragraph()
    p.text = "独自のキャリブレーション技術とロジックに加え、手動補正で精度を担保"
    p.level = 1
    
    p = tf.add_paragraph()
    p.text = "統合ソリューション"
    p.level = 0
    p = tf.add_paragraph()
    p.text = "解析からレポート作成までをワンストップで提供するWebアプリケーション"
    p.level = 1


    # その他: 各スライドに画像配置スペースを追加する例
    # 特徴ページなどにイメージ図用の枠を追加
    for i, slide in enumerate(prs.slides):
        if i in [3, 4, 5]: # 特徴1, 2, 3のスライドインデックス
            x, y, cx, cy = Inches(5.5), Inches(2.0), Inches(4.0), Inches(3.0)
            shape = slide.shapes.add_shape(1, x, y, cx, cy)
            shape.text = "[画面キャプチャ挿入エリア]"
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(240, 240, 240)
            shape.line.color.rgb = RGBColor(150, 150, 150)


    # 保存
    output_filename = 'ADC_System_Overview_v2.pptx'
    prs.save(output_filename)
    print(f"Presentation saved to: {output_filename}")

if __name__ == "__main__":
    create_presentation()
