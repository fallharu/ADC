import os
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

def create_thesis_docx(input_md_path, output_docx_path):
    # ドキュメントの新規作成
    doc = Document()
    
    # スタイルの設定 (標準フォントなど)
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Yu Mincho' # 明朝体を基本とする
    font.size = Pt(10.5)

    # Markdownファイルを読み込む
    if not os.path.exists(input_md_path):
        print(f"Error: Input file not found at {input_md_path}")
        return

    with open(input_md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # ヘッダー処理 (#, ##, ###)
        if line.startswith('# '):
            # タイトル (Heading 1)
            text = line[2:]
            p = doc.add_heading(text, level=1)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif line.startswith('## '):
            # セクション (Heading 2)
            text = line[3:]
            doc.add_heading(text, level=2)
        elif line.startswith('### '):
            # サブセクション (Heading 3)
            text = line[4:]
            doc.add_heading(text, level=3)
        
        # リスト処理
        elif line.startswith('* ') or line.startswith('- '):
            text = line[2:]
            p = doc.add_paragraph(text, style='List Bullet')
        elif line[0].isdigit() and line[1:3] == '. ':
            # 番号付きリスト (簡易的な処理)
            text = line[3:]
            p = doc.add_paragraph(text, style='List Number')
        
        # 本文処理
        else:
            # ボールド体の簡易パース (**text**)
            # python-docxで部分的なボールドは run を分ける必要があるが、
            # ここでは簡易的にパラグラフ全体を追加する (実用上は分割が必要だが今回はテキスト主眼)
            # 少しリッチにして、** ** の中身だけ太字にする処理を入れる
            p = doc.add_paragraph()
            parts = line.split('**')
            for i, part in enumerate(parts):
                run = p.add_run(part)
                if i % 2 == 1: # 奇数番目の要素は ** で囲まれていた部分
                    run.bold = True
                
                # フォント設定 (日本語対応のため)
                run.font.name = 'Yu Mincho'

    # 保存
    doc.save(output_docx_path)
    print(f"Document saved to: {output_docx_path}")

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    md_file = os.path.join(current_dir, 'ADC_System_Thesis_Content.md')
    docx_file = os.path.join(current_dir, 'ADC_System_Thesis.docx')
    
    create_thesis_docx(md_file, docx_file)
