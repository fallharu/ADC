import sqlite3

db_path = r'C:\Users\kurok\Downloads\G_ADC\ADC_08\db\profiles\default\my_app_data.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all table names
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name;")
tables = cursor.fetchall()

for name, sql in tables:
    print(f"\n{'='*80}")
    print(f"TABLE: {name}")
    print(f"{'='*80}")
    if sql:
        print(sql[:800])  # First 800 chars of CREATE statement
    
    # Count records
    cursor.execute(f"SELECT COUNT(*) FROM `{name}`;")
    count = cursor.fetchone()[0]
    print(f"\nRecords: {count}")

conn.close()
