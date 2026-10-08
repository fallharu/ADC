import sqlite3
import os

db_path = r'C:\Users\kurok\Downloads\G_ADC\ADC_08\db\profiles\default\my_app_data.db'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [t[0] for t in cursor.fetchall()]

print("TABLES:")
for table in tables:
    print(f"  - {table}")
    cursor.execute(f"SELECT COUNT(*) FROM {table};")
    count = cursor.fetchone()[0]
    print(f"    Records: {count}")

conn.close()
