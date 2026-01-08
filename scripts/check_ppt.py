from pptx import Presentation
import os

def check_presentation(filename):
    if not os.path.exists(filename):
        print(f"File not found: {filename}")
        return

    prs = Presentation(filename)
    print(f"--- Content of {filename} ---")
    for i, slide in enumerate(prs.slides):
        print(f"\n[Slide {i+1}]")
        # タイトルの取得
        if slide.shapes.title:
            print(f"Title: {slide.shapes.title.text}")
        
        # テキストボックス等の内容取得
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            # タイトル以外のテキストを表示
            if shape == slide.shapes.title:
                continue
            
            for paragraph in shape.text_frame.paragraphs:
                prefix = "- " if paragraph.level > 0 else ""
                if paragraph.text.strip():
                    print(f"{prefix}{paragraph.text}")

        # 画像/図形のチェック
        image_count = 0
        chart_count = 0
        shape_count = 0
        for shape in slide.shapes:
            if shape.shape_type == 13: # PICTURE
                image_count += 1
            elif shape.shape_type == 3: # CHART
                chart_count += 1
            elif shape.shape_type == 1: # AUTO_SHAPE (Rectangles etc)
                # テキストフレームを持たない、またはプレースホルダー的なものをカウント
                if "キャプチャ挿入エリア" in shape.text or "サムネイル" in shape.text:
                    shape_count += 1
        
        if image_count > 0:
            print(f"(Contains {image_count} images)")
        if chart_count > 0:
            print(f"(Contains {chart_count} charts)")
        if shape_count > 0:
            print(f"(Contains {shape_count} placeholder shapes)")

if __name__ == "__main__":
    check_presentation("ADC_System_Overview_v2.pptx")
