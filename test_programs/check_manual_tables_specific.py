import sqlite3
import os

DB_PATH = r"c:\Users\kurok\Downloads\G_ADC\ADC_08\db\my_app_data.db"

def check_schema():
    if not os.path.exists(DB_PATH):
        print(f"DB not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("--- ManualOvertakeTimeline Schema (manual_event_id check) ---")
    try:
        c.execute("PRAGMA table_info(ManualOvertakeTimeline)")
        rows = c.fetchall()
        found = False
        for row in rows:
            # row format: (cid, name, type, notnull, dflt_value, pk)
            if row[1] == 'manual_event_id':
                print(f"FOUND: {row}")
                found = True
        if not found:
            print("NOT FOUND: manual_event_id in ManualOvertakeTimeline")
            
    except Exception as e:
        print(e)

    conn.close()

if __name__ == "__main__":
    check_schema()
