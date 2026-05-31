import sqlite3
import os
import sys
import traceback
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent
sys.path.append(str(project_root))

from Source_code.modules.db_manager import MAIN_DB_PATH
from Source_code.modules.xy_section_speed import assign_xy_section_speed

LOG_FILE = "reproduce_log.txt"

def log(msg):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def verify_fix():
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
        
    log(f"Checking database at: {MAIN_DB_PATH}")
    
    # 1. Check columns
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(Detection)")
            columns = [row[1] for row in cursor.fetchall()]
            
            required = ["xy_px_speedpx", "xy_px_karikm", "xy_px_changeable", "xy_px_changeable_name"]
            missing = [col for col in required if col not in columns]
            
            if missing:
                log(f"FAIL: Still missing columns: {missing}")
            else:
                log("PASS: All required columns exist in Detection table.")
    except Exception as e:
        log(f"FAIL: Database check error: {e}")

    # 2. Run function
    run_id = 100659
    log(f"Attempting to run assign_xy_section_speed for run_id={run_id}...")
    
    try:
        assign_xy_section_speed(run_id)
        log("PASS: assign_xy_section_speed completed without schema error.")
    except Exception as e:
        log(f"FAIL: assign_xy_section_speed raised exception: {e}")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            traceback.print_exc(file=f)

if __name__ == "__main__":
    verify_fix()
