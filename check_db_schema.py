import sqlite3
import json

# Connect to database
conn = sqlite3.connect('db/my_app_data.db')
cursor = conn.cursor()

# Get Detection table schema
cursor.execute('PRAGMA table_info(Detection)')
columns = cursor.fetchall()

print("Detection table columns:")
print("=" * 60)
for col in columns:
    print(f"{col[1]:30s} {col[2]:15s}")

# Save to file for reference
with open('detection_schema.txt', 'w', encoding='utf-8') as f:
    f.write("Detection table columns:\n")
    f.write("=" * 60 + "\n")
    for col in columns:
        f.write(f"{col[1]:30s} {col[2]:15s}\n")

# Also get a sample row to see what data looks like
cursor.execute('SELECT * FROM Detection LIMIT 1')
sample = cursor.fetchone()

if sample:
    print("\n" + "=" * 60)
    print("Sample row (first 10 values):")
    print("=" * 60)
    col_names = [col[1] for col in columns]
    for i, (name, value) in enumerate(zip(col_names[:10], sample[:10])):
        print(f"{name:30s} = {value}")

conn.close()
print("\nSchema saved to detection_schema.txt")
