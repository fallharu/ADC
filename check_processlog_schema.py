import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
cursor = conn.cursor()

# Get ProcessLog table schema
cursor.execute('PRAGMA table_info(ProcessLog)')
columns = cursor.fetchall()

print("ProcessLog table columns:")
print("=" * 60)
for col in columns:
    print(f"{col[1]:30s} {col[2]:15s}")

# Save to file
with open('processlog_schema.txt', 'w', encoding='utf-8') as f:
    f.write("ProcessLog table columns:\n")
    f.write("=" * 60 + "\n")
    for col in columns:
        f.write(f"{col[1]:30s} {col[2]:15s}\n")

conn.close()
print("\nSchema saved to processlog_schema.txt")
