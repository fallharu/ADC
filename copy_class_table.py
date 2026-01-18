import sqlite3

# Copy Class table from backup to current DB
BACKUP_PATH = 'db/my_app_data.db.backup_20260117_102900'
TARGET_PATH = 'db/my_app_data.db'

# Get Class data from backup
backup_conn = sqlite3.connect(BACKUP_PATH)
backup_c = backup_conn.cursor()
backup_c.execute("SELECT class_id, class_name FROM Class")
class_data = backup_c.fetchall()
print(f"Backup Class table has {len(class_data)} rows")
for row in class_data[:10]:
    print(f"  {row}")
backup_conn.close()

# Insert into current DB
target_conn = sqlite3.connect(TARGET_PATH)
target_c = target_conn.cursor()
target_c.execute("DELETE FROM Class")  # Clear existing
target_c.executemany("INSERT INTO Class (class_id, class_name) VALUES (?, ?)", class_data)
target_conn.commit()
target_c.execute("SELECT COUNT(*) FROM Class")
print(f"\nTarget Class table now has {target_c.fetchone()[0]} rows")
target_conn.close()

print("Done!")
