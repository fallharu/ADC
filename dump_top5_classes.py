import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== Run 100249 検出クラス TOP 5 ===')
c.execute("""
    SELECT d.class_id, c.class_name, COUNT(*) as cnt
    FROM Detection d
    LEFT JOIN Class c ON d.class_id = c.class_id
    WHERE d.run_id = 100249
    GROUP BY d.class_id, c.class_name
    ORDER BY cnt DESC
    LIMIT 5
""")
results = c.fetchall()

for row in results:
    print(f'  "{row[1]}" (ID {row[0]}): {row[2]} detections')

conn.close()
