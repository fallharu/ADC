
import sqlite3
import os

DB_PATH = 'db/my_app_data.db'

if not os.path.exists(DB_PATH):
    print(f"DB not found at {DB_PATH}")
    exit(1)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print("--- CREATE TABLE SQL ---")
try:
    sql = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='Detection'").fetchone()
    if sql:
        print(sql[0])
    else:
        print("Table Detection not found")
except Exception as e:
    print(f"Error fetching detailed sql: {e}")

print("\n--- PRAGMA table_info ---")
try:
    cols = cursor.execute("PRAGMA table_info(Detection)").fetchall()
    col_names = [c[1] for c in cols]
    print(col_names)
    
    missing = []
    expected = ['acceleration_m_s2', 'group_id', 'approach_distance_m', 'l_line_distance_m']
    for e in expected:
        if e not in col_names:
            missing.append(e)
            
    if missing:
        print(f"\nMISSING COLUMNS: {missing}")
    else:
        print("\nAll expected columns present.")
        
except Exception as e:
    print(f"Error fetching pragma: {e}")

conn.close()
