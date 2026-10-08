import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== Run 100249 の car/bicycle 検出確認 ===')
c.execute("""
    SELECT d.class_id, c.class_name, COUNT(*) 
    FROM Detection d
    LEFT JOIN Class c ON d.class_id = c.class_id
    WHERE d.run_id = 100249
      AND LOWER(c.class_name) IN ('car', 'bicycle', 'bus', 'truck')
    GROUP BY d.class_id, c.class_name
""")
results = c.fetchall()

if not results:
    print("car, bicycle, bus, truck の検出はありません。")
else:
    for row in results:
        print(f'  ID {row[0]} ("{row[1]}"): {row[2]} detections')
        
conn.close()
