import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== run_id 100179 の Detection 確認 ===')
c.execute("""
    SELECT model_name, COUNT(*) as cnt 
    FROM Detection 
    WHERE run_id = 100179 
    GROUP BY model_name
""")
for row in c.fetchall():
    print(f'  {row[0]}: {row[1]} rows')

print('\n=== run_id 100247 の Detection 確認 ===')
c.execute("""
    SELECT model_name, COUNT(*) as cnt 
    FROM Detection 
    WHERE run_id = 100247 
    GROUP BY model_name
""")
for row in c.fetchall():
    print(f'  {row[0]}: {row[1]} rows')

print('\n=== model_name が best 以外の件数 ===')
c.execute("""
    SELECT run_id, model_name, COUNT(*) as cnt 
    FROM Detection 
    WHERE LOWER(model_name) != 'best'
    GROUP BY run_id, model_name
    ORDER BY run_id DESC
    LIMIT 20
""")
for row in c.fetchall():
    print(f'  Run {row[0]}: {row[1]} = {row[2]} rows')

conn.close()
