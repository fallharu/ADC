import sqlite3

# Check current Class table and look for gaps
conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== 現在の Class テーブル ===')
c.execute("SELECT class_id, class_name FROM Class ORDER BY class_id")
classes = c.fetchall()
for row in classes:
    print(f'  {row[0]}: {row[1]}')

# Check if there are any class_ids in Detection that are not in Class
c.execute("""
    SELECT DISTINCT d.class_id 
    FROM Detection d 
    WHERE d.class_id NOT IN (SELECT class_id FROM Class)
""")
missing = c.fetchall()
if missing:
    print(f'\n⚠ Detection にあるが Class にないclass_id: {[r[0] for r in missing]}')
else:
    print('\nすべてのclass_idは Class テーブルに存在します')

conn.close()
