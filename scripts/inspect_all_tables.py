import sqlite3

db_path = r'C:\Users\kurok\Downloads\G_ADC\ADC_08\db\profiles\default\my_app_data.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get table names
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
tables = [t[0] for t in cursor.fetchall()]

for table in tables:
    print(f"\n=== {table} ===")
    cursor.execute(f"PRAGMA table_info({table});")
    cols = cursor.fetchall()
    col_names = [col[1] for col in cols]
    print(f"Columns: {', '.join(col_names)}")
    
    cursor.execute(f"SELECT COUNT(*) FROM {table};")
    count = cursor.fetchone()[0]
    print(f"Records: {count}")
    
    if count > 0 and count < 1000:
        cursor.execute(f"SELECT * FROM {table} LIMIT 2;")
        rows = cursor.fetchall()
        for i, row in enumerate(rows, 1):
            print(f"Sample {i}: {dict(zip(col_names, row))}")

conn.close()
