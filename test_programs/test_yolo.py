import sys
import os
import traceback

sys.path.insert(0, os.getcwd())
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from Source_code.modules.inference import process_video
from Source_code.modules.db_manager import init_db

# Test video path (update as needed)
TEST_VIDEO = "uploads/20250705/1_20250705_000G2175 Masaaki Sakai_bike_clips.mp4"

def progress_callback(current, total, status="processing", message=None):
    print(f"Progress: {current}/{total} - {status} - {message}")

if __name__ == "__main__":
    print("=== YOLO処理テスト ===")
    
    # Check if video exists
    if not os.path.exists(TEST_VIDEO):
        # Try to find any video
        import glob
        videos = glob.glob("uploads/**/*.mp4", recursive=True)
        if videos:
            TEST_VIDEO = videos[0]
            print(f"テスト動画を発見: {TEST_VIDEO}")
        else:
            print("テスト動画が見つかりません")
            sys.exit(1)
    
    try:
        result = process_video(
            video_path=TEST_VIDEO,
            progress_callback=progress_callback
        )
        print(f"成功! Run ID: {result.run_id}, 検出数: {result.total_detections}")
    except Exception as e:
        print(f"エラー発生: {type(e).__name__}: {e}")
        traceback.print_exc()
