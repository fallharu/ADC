import sqlite3
db_path = 'db/my_app_data.db'
target_filename_part = '000G2603'
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT p.run_id, v.filename, v.source_path FROM ProcessLog p JOIN Video v ON p.video_id = v.video_id WHERE v.filename LIKE ?", (f'%{target_filename_part}%',))
    rows = cursor.fetchall()
    print("MATCHING RUNS:")
    for r in rows:
        print(r)
    conn.close()
except Exception as e:
    print(e)
