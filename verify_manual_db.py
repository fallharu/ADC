from flask import Flask, current_app
from Source_code.modules import db_manager as dbm
import sqlite3
import os
import sys

# Redirect output
sys.stdout = open('verify_result.txt', 'w')
sys.stderr = sys.stdout

# Setup minimal Flask app
app = Flask(__name__)
# Define path
db_path = os.path.join(os.getcwd(), 'Source_code', 'modules', 'main_test.db')

# Override global DB path in module
dbm.MAIN_DB_PATH = db_path
print(f"Using DB Path: {dbm.MAIN_DB_PATH}")

def test_manual_db():
    if os.path.exists(db_path):
        os.remove(db_path)
        
    with app.app_context():
        print("Initialize DB...")
        # Ensure directory exists if new DB
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        try:
             dbm.init_db()
        except Exception as e:
             print(f"Init DB FAILED: {e}")
             import traceback
             traceback.print_exc()
             return

        # Check tables
        with dbm.get_db_connection() as conn:
            c = conn.cursor()
            tables = [row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            required = ["ManualOvertakeEvents", "ManualRunProgress", "ManualOvertakeTimeline", "ManualContextBacklog"]
            for t in required:
                if t in tables:
                    print(f"[OK] Table {t} exists")
                else:
                    print(f"[FAIL] Table {t} missing")
            
            # DEBUG: Print ManualOvertakeEvents schema
            c.execute("PRAGMA table_info(ManualOvertakeEvents)")
            cols = c.fetchall()
            print("DEBUG: ManualOvertakeEvents columns:")
            for col in cols:
                print(f"  {col['name']} ({col['type']})")

            # Create dummy ProcessLog for FK
            c.execute("INSERT INTO ProcessLog (run_id, status) VALUES (9999, 'test')")
            conn.commit()
            print("[OK] Created dummy ProcessLog for run_id=9999")

        # Test Insert
        print("Testing Insert...")
        event_data = {
            "run_id": 9999,
            "frame_num": 100,
            "video_time_s": 3.33,
            "overtaker_group_id": 1,
            "overtaken_group_id": 2,
            "notes": "Test Note",
            "context_frames": [{"frame_num": 99}, {"frame_num": 101}]
        }
        try:
            eid = dbm.insert_manual_overtake_event(event_data)
            print(f"[OK] Inserted event ID: {eid}")
        except Exception as e:
            print(f"[FAIL] Insert failed: {e}")
            import traceback
            traceback.print_exc()
            return

        # Test Fetch
        print("Testing Fetch...")
        fetched = dbm.fetch_manual_overtake_event(eid)
        if fetched and fetched['notes'] == "Test Note" and len(fetched['context_frames']) == 2:
             print(f"[OK] Fetched event correctly: {fetched['manual_event_id']}")
        else:
             print(f"[FAIL] Fetch mismatch: {fetched}")

        # Test Update
        print("Testing Update...")
        dbm.update_manual_overtake_event(eid, {"notes": "Updated Note"})
        fetched = dbm.fetch_manual_overtake_event(eid)
        if fetched['notes'] == "Updated Note":
             print("[OK] Update successful")
        else:
             print(f"[FAIL] Update failed: {fetched['notes']}")

        # Test List
        print("Testing List...")
        events = dbm.list_manual_overtake_events(run_id=9999)
        if len(events) >= 1:
             print(f"[OK] List returned {len(events)} events")
        else:
             print("[FAIL] List returned empty")

        # Test Helpers
        print("Testing Helpers...")
        dbm.touch_manual_run_progress(9999)
        val = dbm.count_manual_overtake_events(9999)
        print(f"[OK] Count manual events for run 9999: {val}")

        # Cleanup test data
        print("Cleaning up...")
        dbm.delete_manual_overtake_event(eid)
        print("[OK] Cleanup complete")
    
    print("Verification complete.")

if __name__ == "__main__":
    test_manual_db()
