import sqlite3
import os

db_path = "db/test_adc.db"
if not os.path.exists(db_path):
    print("DB file not found")
    exit(1)

conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("PRAGMA table_info(Detection)")
rows = c.fetchall()
found = False
for r in rows:
    if r[1] in ['x1', 'video_id', 'class_id']:
        print(f"Found column: {r[1]}")
        found = True

if not found:
    print("Columns not found!")
else:
    print("Verification passed.")
conn.close()
