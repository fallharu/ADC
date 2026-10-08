import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== DB状態確認 ===')
tables = ['Video', 'ProcessLog', 'Detection', 'Class', 'OvertakeEvents']
for t in tables:
    c.execute(f"SELECT COUNT(*) FROM {t}")
    print(f'{t}: {c.fetchone()[0]} rows')

print('\n=== 最新のDetection確認 ===')
c.execute("""
    SELECT run_id, model_name, COUNT(*) as det_count 
    FROM Detection 
    GROUP BY run_id, model_name 
    ORDER BY run_id DESC 
    LIMIT 20
""")
for row in c.fetchall():
    print(f'  Run {row[0]}: model={row[1]}, count={row[2]}')

print('\n=== モデル名別のDetection件数 ===')
c.execute("""
    SELECT model_name, COUNT(*) as det_count 
    FROM Detection 
    GROUP BY model_name
""")
for row in c.fetchall():
    print(f'  {row[0]}: {row[1]} rows')

conn.close()
