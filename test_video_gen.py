
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath('.'))

from Source_code.modules.video_generator import VideoGenerator

run_id = 100249

print(f"=== Run ID {run_id} 動画生成テスト開始 ===")
try:
    generator = VideoGenerator(run_id, options={
        'show_vehicle_box': True,
        'label_group_id': True,
        'label_class_name': True
    })
    output_path = generator.run()
    print(f"✓ 動画生成成功: {output_path}")
except Exception as e:
    print(f"✗ 動画生成失敗: {e}")
    import traceback
    traceback.print_exc()
