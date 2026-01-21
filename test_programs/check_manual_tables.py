import sqlite3
import os

DB_PATH = r"c:\Users\kurok\Downloads\G_ADC\ADC_08\db\my_app_data.db"

def check_schema():
    if not os.path.exists(DB_PATH):
        print(f"DB not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("--- ManualOvertakeTimeline Schema ---")
    try:
        c.execute("PRAGMA table_info(ManualOvertakeTimeline)")
        rows = c.fetchall()
        for row in rows:
            print(row)
    except Exception as e:
        print(e)
        
    print("\n--- ManualOvertakeEvents Schema ---")
    try:
        c.execute("PRAGMA table_info(ManualOvertakeEvents)")
        rows = c.fetchall()
        for row in rows:
            print(row)
    except Exception as e:
        print(e)

    conn.close()

if __name__ == "__main__":
    check_schema()
