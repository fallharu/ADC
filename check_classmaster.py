import sqlite3
import os
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

db_path = os.getenv('MAIN_DB_PATH', 'db/my_app_data.db')
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Check ClassMaster table
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ClassMaster'")
result = c.fetchone()
print(f"ClassMaster table exists: {result is not None}")

if result:
    c.execute('SELECT * FROM ClassMaster LIMIT 10')
    rows = c.fetchall()
    print(f"ClassMaster sample ({len(rows)} rows):")
    for row in rows:
        print(f"  {row}")
else:
    print("Creating ClassMaster table...")
    c.execute("""
        CREATE TABLE IF NOT EXISTS ClassMaster (
            class_id INTEGER PRIMARY KEY,
            class_name TEXT NOT NULL
        )
    """)
    # Insert common classes
    classes = [(0, 'person'), (1, 'bicycle'), (2, 'car'), (3, 'motorcycle'), (5, 'bus'), (7, 'truck')]
    c.executemany("INSERT OR IGNORE INTO ClassMaster (class_id, class_name) VALUES (?, ?)", classes)
    conn.commit()
    print("Table created with default classes!")

# Test fetch_detections_for_frame
print("\n=== Testing fetch_detections_for_frame ===")
from Source_code.modules.db_manager import fetch_detections_for_frame
detections = fetch_detections_for_frame(100177, 100)
print(f"Detections at frame 100: {len(detections)}")
if detections:
    print(f"First detection: {detections[0]}")

conn.close()
