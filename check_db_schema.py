import sqlite3
import os

db_path = "db/my_app_data.db"
print(f"Checking DB: {db_path}")

if not os.path.exists(db_path):
    print("DB file does not exist!")
else:
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(ManualOvertakeEvents)")
        columns = cursor.fetchall()
        if not columns:
            print("Table 'ManualOvertakeEvents' does not exist.")
        else:
            print("Columns in ManualOvertakeEvents:")
            for col in columns:
                print(f"  {col[1]}") # cid, name, type, notnull, dflt_value, pk
    except Exception as e:
        print(f"Error checking DB: {e}")
    finally:
        if conn:
            conn.close()
