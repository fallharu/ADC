import sys
import os
import sqlite3
import traceback

# Add project root to path
sys.path.append(os.getcwd())

from Source_code.modules.db_manager import MAIN_DB_PATH
from Source_code.modules.full_csv_export import generate_full_csv
from Source_code.modules.excel_exporter import create_detection_excel

def verify_exports():
    print(f"DB Path: {MAIN_DB_PATH}")
    
    # Check Tables
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        print("--- Tables Check ---")
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        # print(f"Tables: {tables}")
        print("Tables checked.")
        
    try:
        csv_bytes = generate_full_csv(MAIN_DB_PATH)
        if len(csv_bytes) > 0:
            print("SUCCESS: Full Data CSV bytes generated.")
            with open("test_full_data.csv", "wb") as f:
                f.write(csv_bytes)
            print("Saved test_full_data.csv")
            
            # Basic content check
            try:
                header_line = csv_bytes.decode('utf-8-sig').split('\n')[0]
                print(f"Header preview: {header_line[:150]}...")
            except:
                print("Header decode failed (cp932?)")
        else:
            print("WARNING: CSV bytes empty.")
    except Exception as e:
        print(f"ERROR: Full CSV Export failed: {e}")
        # traceback.print_exc()

    # 1.5 Verify Kanaoka CSV Export
    print("\n--- Testing Kanaoka CSV Export ---")
    try:
        from Source_code.modules.kanaoka_export import generate_kanaoka_csv
        csv_bytes = generate_kanaoka_csv(MAIN_DB_PATH)
        if len(csv_bytes) > 0:
            print("SUCCESS: Kanaoka CSV bytes generated.")
            with open("test_kanaoka_export.csv", "wb") as f:
                f.write(csv_bytes)
            print("Saved test_kanaoka_export.csv")
        else:
            print("WARNING: Kanaoka CSV bytes empty.")
    except Exception as e:
        print(f"ERROR: Kanaoka CSV Export failed: {e}")
        import traceback
        # Print stack trace manually to avoid truncation
        tb = traceback.extract_tb(sys.exc_info()[2])
        for filename, lineno, funcname, line in tb:
            print(f"File {filename}, line {lineno}, in {funcname}")
            print(f"    {line}")

    # 1.6 Verify Overtake Summary CSV Export
    print("\n--- Testing Overtake Summary CSV Export ---")
    try:
        from Source_code.modules.summary_csv_export import generate_summary_csv
        csv_bytes = generate_summary_csv(MAIN_DB_PATH)
        if len(csv_bytes) > 0:
            print("SUCCESS: Overtake Summary CSV bytes generated.")
            with open("test_summary.csv", "wb") as f:
                f.write(csv_bytes)
            print("Saved test_summary.csv")
        else:
            print("WARNING: Summary CSV bytes empty.")
    except Exception as e:
        print(f"ERROR: Overtake Summary CSV Export failed: {e}")
        traceback.print_exc()

    # 2. Get a valid Run ID
    run_id = None
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        cursor = conn.execute("SELECT run_id FROM ProcessLog ORDER BY run_id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            run_id = row[0]
            print(f"\nFound Run ID: {run_id}")

    # 3. Verify Standard Export (Per-Run)
    if run_id:
        print(f"--- Testing Standard Excel Export for Run {run_id} ---")
        try:
            path = create_detection_excel(run_id)
            print(f"SUCCESS: Standard Excel saved to: {path}")
            if os.path.exists(path):
                print("File exists on disk.")
        except Exception as e:
            print(f"ERROR: Standard Export failed: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    verify_exports()
