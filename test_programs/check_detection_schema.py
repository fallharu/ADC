import sqlite3
import os

DB_PATH = r"c:\Users\kurok\Downloads\G_ADC\ADC_08\db\my_app_data.db"

def check_detection_schema():
    if not os.path.exists(DB_PATH):
        print(f"DB not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("--- Detection Schema ---")
    try:
        c.execute("PRAGMA table_info(Detection)")
        rows = c.fetchall()
        for row in rows:
            print(row)
    except Exception as e:
        print(e)
    
    # Check sample data
    print("\n--- Sample Data ---")
    try:
         c.execute("SELECT * FROM Detection LIMIT 1")
         print(c.fetchone())
    except:
         pass

    conn.close()

if __name__ == "__main__":
    check_detection_schema()
