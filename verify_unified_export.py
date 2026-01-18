import os
import sys
import pandas as pd
import sqlite3

# Add Source_code to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'Source_code'))

from modules import db_manager as dbm

def setup_test_db(db_path="test_unified_export.db"):
    if os.path.exists(db_path):
        os.remove(db_path)
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 1. Create Tables
    c.execute('''CREATE TABLE IF NOT EXISTS Video (
        video_id INTEGER PRIMARY KEY,
        filename TEXT,
        fps REAL,
        width INTEGER,
        height INTEGER,
        duration REAL,
        collection_year INTEGER,
        road_type TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS ProcessLog (
        run_id INTEGER PRIMARY KEY,
        video_id INTEGER,
        output_folder TEXT,
        process_start TEXT,
        process_end TEXT,
        status TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS ClassMaster (
        class_id INTEGER PRIMARY KEY,
        class_name TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS Detection (
        auto_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER,
        frame_num INTEGER,
        track_id INTEGER,
        class_id INTEGER,
        confidence REAL,
        x1 REAL, y1 REAL, x2 REAL, y2 REAL,
        measure_x REAL, measure_y REAL,
        group_id INTEGER,
        approach_partner_group_id INTEGER,
        line_distance_m REAL,
        line_distance REAL,
        l_line_distance_m REAL,
        l_line_distance REAL,
        r_line_distance_m REAL,
        r_line_distance REAL,
        approach_distance_m REAL,
        approach_distance_px REAL,
        clearance_distance_m REAL,
        clearance_distance_px REAL,
        lane_position_flag TEXT,
        overtake INTEGER,
        overtake_by INTEGER
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS OvertakeEvents (
        overtake_event_id INTEGER PRIMARY KEY,
        run_id INTEGER,
        event_frame_num INTEGER,
        overtaker_group_id INTEGER,
        overtaken_group_id INTEGER,
        overtaker_auto_id INTEGER,
        overtaken_auto_id INTEGER,
        line_distance_m REAL,
        line_distance REAL,
        clearance_distance_m REAL,
        clearance_distance_px REAL,
        l_line_distance_m REAL,
        l_line_distance REAL,
        r_line_distance_m REAL,
        r_line_distance REAL,
        approach_distance_m REAL,
        approach_distance_px REAL
    )''')
    
    # 2. Insert Test Data
    c.execute("INSERT INTO ClassMaster (class_id, class_name) VALUES (1, 'bicycle'), (2, 'car')")
    c.execute("INSERT INTO Video (video_id, filename, fps) VALUES (1, 'test_video.mp4', 30.0)")
    c.execute("INSERT INTO ProcessLog (run_id, video_id) VALUES (1, 1)")
    
    # Event Case: Frame 100
    # Overtaker (Car): Group 10
    # Overtaken (Bike): Group 20
    
    # Insert Overtake Event
    c.execute("""
        INSERT INTO OvertakeEvents (
            run_id, event_frame_num, overtaker_group_id, overtaken_group_id,
            line_distance_m, clearance_distance_m, clearance_distance_px
        ) VALUES (
            1, 100, 10, 20,
            1.5, 2.5, 250.0
        )
    """)
    
    # Insert Detections (Frame 90-110)
    # Both groups should exist in these frames
    # Frame 100 has some data missing in Detection to test Coalesce
    
    for f in range(90, 111):
        # Car (Group 10)
        c.execute("""
            INSERT INTO Detection (
                run_id, frame_num, track_id, class_id, group_id, approach_partner_group_id,
                x1, y1, x2, y2, overtake
            ) VALUES (
                1, ?, 101, 2, 10, 20,
                100, 100, 200, 200, ?
            )
        """, (f, 1 if f == 100 else 0))
        
        # Bike (Group 20)
        c.execute("""
            INSERT INTO Detection (
                run_id, frame_num, track_id, class_id, group_id, approach_partner_group_id,
                x1, y1, x2, y2, overtake_by
            ) VALUES (
                1, ?, 201, 1, 20, 10,
                300, 300, 350, 400, ?
            )
        """, (f, 101 if f == 100 else None))
        
    # Unrelated Group (Group 30) - Should NOT be exported
    c.execute("""
        INSERT INTO Detection (run_id, frame_num, track_id, class_id, group_id)
        VALUES (1, 100, 301, 2, 30)
    """)
    
    conn.commit()
    conn.close()
    return 1 # run_id

def verify():
    # Patch DB path
    original_db_path = dbm.MAIN_DB_PATH
    dbm.MAIN_DB_PATH = "test_unified_export.db"
    
    try:
        print("Setting up test DB...")
        run_id = setup_test_db(dbm.MAIN_DB_PATH)
        
        print("Running export...")
        data = dbm.get_track_data_for_export(run_id)
        
        df_cycle = data['bicycle']
        df_overtake = data['overtake']
        
        print(f"Bicycle DF shape: {df_cycle.shape}")
        print(f"Overtake DF shape: {df_overtake.shape}")
        
        if not df_cycle.empty:
            print("FAIL: Bicycle DF should be empty.")
        else:
            print("PASS: Bicycle DF is empty.")
            
        if df_overtake.empty:
            print("FAIL: Overtake DF is empty.")
            return

        cols = df_overtake.columns.tolist()
        print(f"Columns found ({len(cols)}):", cols)
        
        expected_cols = [
            'イベントID', 'Run', '動画名', 'オフセットフレーム', '動画フレーム', '動画時間(s)', 
            '役割', 'Group ID', '相手Group', 'トラックID', 'クラス', 
            'BBOX x1', 'BBOX y1', 'BBOX x2', 'BBOX y2', '測定X(px)', '測定Y(px)',
            '白線距離(m)', '白線距離(cm)', '白線距離(px)', '白線距離比率(%)', '白線内外判定',
            '左白線距離(m)', '左白線距離(cm)', '左白線距離(px)',
            '右白線距離(m)', '右白線距離(cm)', '右白線距離(px)',
            '離隔距離(m)', '離隔距離(cm)', '離隔距離(px)'
        ]
        
        missing = [c for c in expected_cols if c not in cols]
        if missing:
            print(f"FAIL: Missing columns: {missing}")
        else:
            print("PASS: All expected columns present.")
            
        # Check Row Count (21 frames * 2 groups = 42 rows)
        if len(df_overtake) == 42:
            print("PASS: Row count is 42 (Correct filtering of event groups).")
        else:
            print(f"FAIL: Row count is {len(df_overtake)}, expected 42.")
            
        # Check Frame 100 Enrichment
        row_100_car = df_overtake[(df_overtake['動画フレーム'] == 100) & (df_overtake['Group ID'] == 10)].iloc[0]
        clr = row_100_car['離隔距離(m)']
        if clr == 2.5:
             print("PASS: Frame 100 enriched correctly (2.5m).")
        else:
             print(f"FAIL: Frame 100 clearance is {clr}, expected 2.5.")
             
        # Check Unrelated Group
        if 30 in df_overtake['Group ID'].values:
            print("FAIL: Unrelated Group 30 found in export.")
        else:
            print("PASS: Unrelated Group 30 correctly excluded.")

        # Save to file for inspection
        df_overtake.to_excel("verify_unified_output.xlsx", index=False)
        print("Saved verify_unified_output.xlsx")
            
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        dbm.MAIN_DB_PATH = original_db_path
        if os.path.exists("test_unified_export.db"):
            try:
                os.remove("test_unified_export.db")
            except:
                pass

if __name__ == '__main__':
    with open('verify_output.txt', 'w', encoding='utf-8') as f:
        original_stdout = sys.stdout
        sys.stdout = f
        verify()
        sys.stdout = original_stdout
        print("Verification complete. Check verify_output.txt")
