
import sqlite3
import os

MAIN_DB_PATH = os.path.join('db', 'my_app_data.db')

def check_schema():
    if not os.path.exists(MAIN_DB_PATH):
        print(f"DB not found at {MAIN_DB_PATH}")
        return

    conn = sqlite3.connect(MAIN_DB_PATH)
    cursor = conn.execute("PRAGMA table_info(Detection)")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    
    print("Detection Table Columns:")
    print(columns)
    
    if 'model_name' in columns:
        print("Has model_name")
    else:
        print("MISSING model_name")
        
    # Check ClassMaster too
    conn = sqlite3.connect(MAIN_DB_PATH)
    cursor = conn.execute("PRAGMA table_info(ClassMaster)")
    cols_cm = [row[1] for row in cursor.fetchall()]
    conn.close()
    print("ClassMaster Table Columns:")
    print(cols_cm)

    # Check ProcessLog
    cursor = conn.execute("PRAGMA table_info(ProcessLog)")
    cols_pl = [row[1] for row in cursor.fetchall()]
    conn.close()
    print("ProcessLog Table Columns:")
    print(cols_pl)


if __name__ == "__main__":
    check_schema()
