import sqlite3
import os

DB_PATH = r"c:\Users\kurok\Downloads\G_ADC\ADC_08\db\my_app_data.db"

def check_status(run_id):
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM ManualRunProgress WHERE run_id = ?", (run_id,))
        row = c.fetchone()
        if row:
            print(f"Run {run_id}: status={row['manual_status']}, last_visit_at={row['last_visit_at']}")
        else:
            print(f"Run {run_id}: No entry in ManualRunProgress")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_status(100177)
