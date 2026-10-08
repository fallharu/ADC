import sqlite3
db_path = 'db/my_app_data.db'
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(ProcessLog)")
    columns = cursor.fetchall()
    print("ProcessLog Table Columns:")
    for col in columns:
        print(col)
    conn.close()
except Exception as e:
    print(e)
