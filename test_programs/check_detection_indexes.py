import sqlite3
import os
from dotenv import load_dotenv
load_dotenv()

db_path = os.getenv('MAIN_DB_PATH', 'db/my_app_data.db')
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Check existing indexes
c.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='Detection'")
indexes = c.fetchall()
print("=== Detection table indexes ===")
for r in indexes:
    print(f"  {r[0]}: {r[1]}")

# Count rows
c.execute('SELECT COUNT(*) FROM Detection')
count = c.fetchone()[0]
print(f"\nTotal Detection rows: {count:,}")

# Test query performance
import time
run_id = 100177
frame = 100
start = time.time()
c.execute("SELECT COUNT(*) FROM Detection WHERE run_id = ? AND frame_num = ?", (run_id, frame))
result = c.fetchone()[0]
elapsed = time.time() - start
print(f"\nQuery test (run_id={run_id}, frame={frame}): {result} rows in {elapsed*1000:.2f}ms")

# Explain query plan
c.execute(f"EXPLAIN QUERY PLAN SELECT * FROM Detection WHERE run_id = ? AND frame_num = ?", (run_id, frame))
plan = c.fetchall()
print("\n=== EXPLAIN QUERY PLAN ===")
for row in plan:
    print(f"  {row}")

conn.close()
