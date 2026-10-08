import sqlite3
import os

db_path = os.path.join("db", "my_app_data.db")
if not os.path.exists(db_path):
    print(f"Database not found: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# Get all tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("=== Database Tables ===")
for t in tables:
    c.execute(f'SELECT COUNT(*) FROM "{t}"')
    count = c.fetchone()[0]
    print(f"  {t}: {count} rows")

# Key statistics
print("\n=== Key Statistics ===")

# Total runs
c.execute("SELECT COUNT(*) FROM ProcessLog")
print(f"Total Runs: {c.fetchone()[0]}")

# Total detections
c.execute("SELECT COUNT(*) FROM Detection")
print(f"Total Detections: {c.fetchone()[0]}")

# Total overtakes (auto)
c.execute("SELECT COUNT(*) FROM OvertakeEvents")
print(f"Automatic Overtakes: {c.fetchone()[0]}")

# Total manual overtakes
try:
    c.execute("SELECT COUNT(*) FROM ManualOvertakeEvents")
    print(f"Manual Overtakes: {c.fetchone()[0]}")
except:
    print("Manual Overtakes: 0 (table not exists)")

# Road types
c.execute("SELECT road_type, COUNT(*) FROM Video WHERE road_type IS NOT NULL GROUP BY road_type")
print("\n=== Road Types ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]} videos")

# Years
c.execute("SELECT collection_year, COUNT(*) FROM Video WHERE collection_year IS NOT NULL GROUP BY collection_year")
print("\n=== Collection Years ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]} videos")

conn.close()
