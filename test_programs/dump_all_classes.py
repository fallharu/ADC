import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== Run 100249 全検出クラス内訳 ===')
c.execute("""
    SELECT d.class_id, c.class_name, COUNT(*) as cnt
    FROM Detection d
    LEFT JOIN Class c ON d.class_id = c.class_id
    WHERE d.run_id = 100249
    GROUP BY d.class_id, c.class_name
    ORDER BY cnt DESC
""")
results = c.fetchall()

if not results:
    print("検出データなし")
else:
    for row in results:
        cid = row[0]
        cname = row[1]
        count = row[2]
        print(f'  ID {cid}: "{cname}" ({count} detections)')

conn.close()
