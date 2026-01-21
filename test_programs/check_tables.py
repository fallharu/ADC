import sqlite3

conn = sqlite3.connect("db/my_app_data.db")
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("All Tables:")
for t in tables:
    print(f"  - {t[0]}")

# Check for ManualOvertakeEvents specifically
manual_tables = [t[0] for t in tables if "Manual" in t[0] or "manual" in t[0]]
print("\nManual-related tables:", manual_tables)

# Check if ManualOvertakeEvents exists
for table in manual_tables:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    print(f"\n{table} columns:")
    for col in cols:
        print(f"  - {col[1]} ({col[2]})")
