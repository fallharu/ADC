
import sqlite3
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'Source_code')))

from modules import db_manager as dbm

# Use the ACTUAL database path from environment or default
if 'MAIN_DB_PATH' not in os.environ:
    # Fallback to likely location if not set, though db_manager usually handles this
    potential_db = os.path.join("db", "my_app_data.db")
    if os.path.exists(potential_db):
        dbm.MAIN_DB_PATH = potential_db
    else:
        # Try finding it
        for root, dirs, files in os.walk("."):
            for file in files:
                if file.endswith(".db") and "test" not in file:
                    dbm.MAIN_DB_PATH = os.path.join(root, file)
                    print(f"Found DB at: {dbm.MAIN_DB_PATH}")
                    break
        else:
            print("Could not locate main database file.")
            sys.exit(1)

print(f"Inspecting Database: {dbm.MAIN_DB_PATH}")

def inspect():
    with dbm.get_db_connection() as conn:
        c = conn.cursor()
        
        # 1. Check Table Columns
        print("\n--- Detection Table Columns ---")
        c.execute("PRAGMA table_info(Detection)")
        cols = c.fetchall()
        det_cols = [row['name'] for row in cols]
        print(det_cols)
        
        print("\n--- OvertakeEvents Table Columns ---")
        c.execute("PRAGMA table_info(OvertakeEvents)")
        cols = c.fetchall()
        oe_cols = [row['name'] for row in cols]
        print(oe_cols)

        # 2. Check for Non-Null Data in Detection
        print("\n--- Detection Data Stats (Non-Null counts) ---")
        for col in ['line_distance_m', 'clearance_distance_m', 'distance_m']:
            if col in det_cols:
                count = c.execute(f"SELECT COUNT(*) FROM Detection WHERE {col} IS NOT NULL").fetchone()[0]
                print(f"{col}: {count}")
            else:
                print(f"{col}: COLUMN MISSING")

        # 3. Check for Non-Null Data in OvertakeEvents
        print("\n--- OvertakeEvents Data Stats (Non-Null counts) ---")
        for col in ['line_distance_m', 'clearance_distance_m', 'l_line_distance_m', 'r_line_distance_m']:
             if col in oe_cols:
                count = c.execute(f"SELECT COUNT(*) FROM OvertakeEvents WHERE {col} IS NOT NULL").fetchone()[0]
                print(f"{col}: {count}")
             else:
                print(f"{col}: COLUMN MISSING")

        # 4. Check a sample Overtake Event and its matching Detections
        print("\n--- Sample Overtake Event Check ---")
        sample_event = c.execute("SELECT * FROM OvertakeEvents LIMIT 1").fetchone()
        if sample_event:
            sample_event = dict(sample_event)
            print("Sample Event:", sample_event)
            
            run_id = sample_event['run_id']
            frame = sample_event['event_frame_num']
            ot_group = sample_event['overtaker_group_id']
            od_group = sample_event['overtaken_group_id']
            
            print(f"Looking for matching Detections (Run: {run_id}, Frame: {frame}, Groups: {ot_group}, {od_group})...")
            
            dets = c.execute("""
                SELECT auto_id, run_id, frame_num, group_id, class_id, line_distance_m, clearance_distance_m 
                FROM Detection 
                WHERE run_id=? AND frame_num=? AND group_id IN (?, ?)
            """, (run_id, frame, ot_group, od_group)).fetchall()
            
            for d in dets:
                print(dict(d))
        else:
            print("No OvertakeEvents found.")

if __name__ == "__main__":
    with open('inspect_output.txt', 'w', encoding='utf-8') as f:
        sys.stdout = f
        inspect()
        sys.stdout = sys.__stdout__
    print("Inspection complete. Results saved to inspect_output.txt")
