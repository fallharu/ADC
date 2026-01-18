import sqlite3
import os
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime

# パス設定
sys.path.append(os.getcwd())

from Source_code.modules.db_manager import MAIN_DB_PATH, configure_connection, init_db
from Source_code.modules.inference import run_postprocess_pipeline_sync
from Source_code.modules.overtake import summarize_run_overtakes

def setup_dummy_data():
    print("=== ダミーデータ作成 ===")
    init_db()  # テーブル作成
    
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Video
        cursor.execute("INSERT OR IGNORE INTO Video (filename, upload_datetime, fps, duration) VALUES (?, ?, ?, ?)",
                       ("dummy_video.mp4", datetime.now(), 30.0, 10.0))
        video_id = cursor.lastrowid
        if video_id == 0: # 既に存在した場合
            cursor.execute("SELECT video_id FROM Video WHERE filename=?", ("dummy_video.mp4",))
            video_id = cursor.fetchone()[0]
            
        # ProcessLog
        cursor.execute("INSERT INTO ProcessLog (video_id, process_start, status, output_folder) VALUES (?, ?, ?, ?)",
                       (video_id, datetime.now(), "processing", "output/dummy"))
        run_id = cursor.lastrowid
        
        # Detection (最低限のデータ)
        # 後処理が動くように、group_id を持ったデータを複数フレーム分入れる
        detections = []
        for frame in range(0, 30):
            # Car (Group 1)
            detections.append((run_id, video_id, 2, frame, "car", 0.9, 1, 100, 100, 200, 200, 50.0))
            # Bicycle (Group 2) - Overtaken logic check
            detections.append((run_id, video_id, 1, frame, "bicycle", 0.8, 2, 300, 100, 350, 200, 15.0))
            
        cursor.executemany("""
            INSERT INTO Detection (run_id, video_id, class_id, frame_num, class_name, confidence, group_id, x1, y1, x2, y2, speed_km_h)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, detections)
        
        conn.commit()
        print(f"作成した Run ID: {run_id}")
        return run_id

def check_db_schema():
    print("=== DBスキーマ確認 ===")
    if not os.path.exists(MAIN_DB_PATH):
        print(f"DBが見つかりません: {MAIN_DB_PATH}")
        return

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        cursor = conn.cursor()
        
        # テーブル一覧
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Tables: {tables}")

        # Detectionテーブルのカラム確認
        if 'Detection' in tables:
            cursor.execute("PRAGMA table_info(Detection)")
            cols = [row[1] for row in cursor.fetchall()]
            # print(f"Detection Columns: {cols}")
            if 'auto_id' in cols:
                print("  -> OK: auto_id (Mockup schema)")
            else:
                 print("  -> ERROR: auto_id not found")
                 
            if 'detection_id' in cols:
                print("  -> WARN: detection_id found (Production schema mix?)")
        
        if 'yolo' in tables:
            print("  -> WARN: 'yolo' table found (Production schema mix!)")

def trigger_post_process(run_id):
    print(f"\n=== Post-Process 手動実行テスト (Run ID: {run_id}) ===")
    try:
        completed, errors = run_postprocess_pipeline_sync(run_id)
        print(f"完了ステップ: {completed}")
        if errors:
            print("エラー発生:")
            for e in errors:
                print(f"  - {e}")
        else:
            print("エラーなし")
    except Exception:
        print("!!! CRASHED in pipeline !!!")
        traceback.print_exc()

    print(f"\n=== Summarize Overtakes テスト (Run ID: {run_id}) ===")
    try:
        summary = summarize_run_overtakes(run_id)
        print("Summary取得成功")
        # print(summary) 
    except Exception:
        print("!!! CRASHED in summarize_run_overtakes !!!")
        traceback.print_exc()

if __name__ == "__main__":
    try:
        run_id = setup_dummy_data()
        check_db_schema()
        trigger_post_process(run_id)
    except Exception:
        traceback.print_exc()

