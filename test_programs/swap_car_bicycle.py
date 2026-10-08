"""
Class テーブルの car/bicycle を COCO 標準に合わせて修正
COCO: ID 1 = bicycle, ID 2 = car
"""
import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== 修正前 ===')
c.execute("SELECT class_id, class_name FROM Class WHERE class_id IN (1, 2)")
for row in c.fetchall():
    print(f'  ID {row[0]}: {row[1]}')

# 一時的に別の名前に変更してから入れ替え
c.execute("UPDATE Class SET class_name = 'temp_bicycle' WHERE class_id = 1")
c.execute("UPDATE Class SET class_name = 'temp_car' WHERE class_id = 2")

# COCO標準に合わせて入れ替え
c.execute("UPDATE Class SET class_name = 'bicycle' WHERE class_id = 1")
c.execute("UPDATE Class SET class_name = 'car' WHERE class_id = 2")

conn.commit()

print('\n=== 修正後 ===')
c.execute("SELECT class_id, class_name FROM Class WHERE class_id IN (1, 2)")
for row in c.fetchall():
    print(f'  ID {row[0]}: {row[1]}')

conn.close()
print('\n完了!')
