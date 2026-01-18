
import sqlite3
import pandas as pd
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'Source_code')))

from modules import db_manager as dbm

# Emulate logic without full Flask app if possible, or just use db_manager directly.
# We will use a temporary in-memory DB or creating a test DB file.
# Since db_manager uses a global MAIN_DB_PATH, we need to temporarily point it to a test DB.

TEST_DB_PATH = "test_enrichment.db"
os.environ["MAIN_DB_PATH"] = TEST_DB_PATH
dbm.MAIN_DB_PATH = TEST_DB_PATH

def setup_test_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    
    dbm.init_db()
    
    with dbm.get_db_connection() as conn:
        c = conn.cursor()

        # Recreate Detection table with FULL schema needed for export
        c.execute("DROP TABLE IF EXISTS Detection")
        c.execute("""
            CREATE TABLE Detection (
                auto_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                frame_num INTEGER,
                track_id INTEGER,
                class_id INTEGER,
                group_id INTEGER,
                overtake INTEGER,
                overtake_by INTEGER,
                clearance_distance_m REAL,
                clearance_distance_px REAL,
                line_distance_m REAL,
                line_distance REAL,
                l_line_distance_m REAL,
                l_line_distance REAL,
                r_line_distance_m REAL,
                r_line_distance REAL,
                approach_distance_m REAL,
                approach_distance_px REAL,
                x1 REAL, y1 REAL, x2 REAL, y2 REAL,
                measure_x REAL, measure_y REAL,
                approach_partner_group_id INTEGER,
                lane_position_flag TEXT,
                confidence REAL,
                speed_km_h REAL,
                ttc_s REAL,
                model_name TEXT,
                class_name TEXT,
                distance_m REAL
            )
        """)

        # 1. Insert Video
        c.execute("""
            INSERT INTO Video (filename, fps, duration) VALUES ('test_video.mp4', 30.0, 100.0)
        """)
        video_id = c.lastrowid
        
        # 2. Insert ProcessLog (Run)
        c.execute("""
            INSERT INTO ProcessLog (video_id, process_start, status) VALUES (?, '2025-01-01 12:00:00', 'completed')
        """, (video_id,))
        run_id = c.lastrowid
        
        # 3. Insert ClassMaster
        c.execute("INSERT OR IGNORE INTO ClassMaster (class_name) VALUES ('bicycle')")
        c.execute("SELECT class_id FROM ClassMaster WHERE class_name='bicycle'")
        class_id_bicycle = c.fetchone()[0]
        
        c.execute("INSERT OR IGNORE INTO ClassMaster (class_name) VALUES ('car')")
        c.execute("SELECT class_id FROM ClassMaster WHERE class_name='car'")
        class_id_car = c.fetchone()[0]
        
        # 4. Insert Detection (missing clearance_distance_m)
        # Bicycle track group_id=10
        c.execute("""
            INSERT INTO Detection (
                run_id, frame_num, track_id, class_id, group_id, 
                overtake, overtake_by, 
                clearance_distance_m
            ) VALUES (
                ?, 100, 1, ?, 10,
                0, 1,
                NULL -- Missing distance!
            )
        """, (run_id, class_id_bicycle))
        
        # Car track group_id=20 (overtaker)
        c.execute("""
            INSERT INTO Detection (
                run_id, frame_num, track_id, class_id, group_id,
                overtake, overtake_by,
                clearance_distance_m
            ) VALUES (
                ?, 100, 2, ?, 20,
                1, NULL,
                NULL -- Missing distance!
            )
        """, (run_id, class_id_car))
        
        # 5. Insert OvertakeEvents (HAS clearance_distance_m)
        c.execute("""
            INSERT INTO OvertakeEvents (
                run_id, event_frame_num, 
                overtaker_group_id, overtaken_group_id,
                clearance_distance_m
            ) VALUES (
                ?, 100, 20, 10, 1.55
            )
        """, (run_id,))
        
        conn.commit()
        return run_id

def verify():
    print("Setting up test DB...")
    run_id = setup_test_db()
    
    print(f"Fetching track data for run_id={run_id}...")
    data = dbm.get_track_data_for_export(run_id)
    
    df_bicycle = data['bicycle']
    df_overtake = data['overtake']
    
    print("Verifying Bicycle Data...")
    if df_bicycle.empty:
        print("FAIL: Bicycle DataFrame is empty")
        return

    # Save to Excel
    output_filename = "test_enrichment_output.xlsx"
    output_path = os.path.abspath(output_filename)
    
    print(f"\nSaving output to: {output_path}")
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        if not df_bicycle.empty:
            df_bicycle.to_excel(writer, sheet_name='自転車', index=False)
        if not df_overtake.empty:
            df_overtake.to_excel(writer, sheet_name='追い越し', index=False)
            
    print("Excel file created successfully.")

    # Check frame 100 row
    row = df_bicycle[df_bicycle['動画フレーム'] == 100].iloc[0]
    clearance = row['離隔距離(m)']
    
    print(f"Detected Clearance (Bicycle Sheet): {clearance}")
    
    if clearance == 1.55:
        print("SUCCESS: Bicycle sheet enriched correctly from OvertakeEvents!")
    else:
        print(f"FAIL: Expected 1.55, got {clearance}")

    print("\nVerifying Overtake Data...")
    if df_overtake.empty:
        print("FAIL: Overtake DataFrame is empty")
        return

    # Check frame 100 row
    row_ov = df_overtake[df_overtake['動画フレーム'] == 100].iloc[0]
    clearance_ov = row_ov['離隔距離(m)']
    
    print(f"Detected Clearance (Overtake Sheet): {clearance_ov}")
    
    if clearance_ov == 1.55:
        print("SUCCESS: Overtake sheet enriched correctly from OvertakeEvents!")
    else:
        print(f"FAIL: Expected 1.55, got {clearance_ov}")
        
    print("\n--- Rows with Frame 100 Preview ---")
    print(df_bicycle[df_bicycle['動画フレーム'] == 100][['動画フレーム', '役割', '離隔距離(m)', '白線距離(m)']].to_string(index=False))

if __name__ == "__main__":
    try:
        verify()
    finally:
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
            # Remove sidecars too explicitly just in case
            if os.path.exists(TEST_DB_PATH + "-wal"): os.remove(TEST_DB_PATH + "-wal")
            if os.path.exists(TEST_DB_PATH + "-shm"): os.remove(TEST_DB_PATH + "-shm")
