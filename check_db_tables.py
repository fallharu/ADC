import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== 現在のDB状態 ===')
tables = ['Video', 'ProcessLog', 'Detection', 'Class', 'ClassMaster', 'OvertakeEvents']
for t in tables:
    c.execute(f"SELECT COUNT(*) FROM {t}")
    print(f'{t}: {c.fetchone()[0]} rows')

conn.close()
