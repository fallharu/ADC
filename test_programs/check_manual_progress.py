import sqlite3
import os
from dotenv import load_dotenv
load_dotenv()

db_path = os.getenv('MAIN_DB_PATH', 'db/my_app_data.db')
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Check ManualRunProgress table
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ManualRunProgress'")
result = c.fetchone()
print(f"ManualRunProgress table exists: {result is not None}")

if result:
    c.execute('PRAGMA table_info(ManualRunProgress)')
    cols = c.fetchall()
    print('Columns:')
    for r in cols:
        print(f"  {r[1]}")
    
    # Check data
    c.execute("SELECT * FROM ManualRunProgress LIMIT 5")
    rows = c.fetchall()
    print(f"\nSample data ({len(rows)} rows):")
    for row in rows:
        print(f"  {row}")
else:
    print("Creating ManualRunProgress table...")
    c.execute("""
        CREATE TABLE IF NOT EXISTS ManualRunProgress (
            run_id INTEGER PRIMARY KEY,
            manual_status TEXT DEFAULT 'new',
            last_visited_at TEXT,
            last_annotated_at TEXT
        )
    """)
    conn.commit()
    print("Table created!")

conn.close()
