import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== Detection テーブルの class_id 分布 (Run 100249) ===')
c.execute("""
    SELECT d.class_id, c.class_name, COUNT(*) 
    FROM Detection d
    LEFT JOIN Class c ON d.class_id = c.class_id
    WHERE d.run_id = 100249
    GROUP BY d.class_id, c.class_name
""")
results = c.fetchall()
if not results:
    print("検出データなし")
else:
    for row in results:
        print(f'  ID {row[0]} ("{row[1]}"): {row[2]} detections')

conn.close()
