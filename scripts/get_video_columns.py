import sqlite3
import json

db_path = r'C:\Users\kurok\Downloads\G_ADC\ADC_08\db\profiles\default\my_app_data.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all column info
cursor.execute("PRAGMA table_info(Video);")
columns = cursor.fetchall()

print("Video table columns:")
for col in columns:
    cid, name, col_type, not_null, default_value, pk = col
    print(f"  {name}: {col_type} {'NOT NULL' if not_null else 'NULL'} {'PK' if pk else ''}")

# Get SQL create statement
cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='Video';")
schema = cursor.fetchone()

if schema:
    with open('video_table_create.sql', 'w', encoding='utf-8') as f:
        f.write(schema[0])
    print(f"\nFull CREATE statement saved to video_table_create.sql")

conn.close()
