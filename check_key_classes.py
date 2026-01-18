import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== 重要クラスのマッピング確認 ===')
# COCO標準: 1=bicycle, 2=car
check_ids = [1, 2, 3, 5, 7, 100, 101, 102]
coco_names = {1: 'bicycle', 2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}

for cid in check_ids:
    c.execute("SELECT class_name FROM Class WHERE class_id = ?", (cid,))
    row = c.fetchone()
    db_name = row[0] if row else '(未登録)'
    coco = coco_names.get(cid, 'カスタム')
    print(f'  ID {cid}: DB="{db_name}" (COCO標準={coco})')

# 現在のDBで car/bicycle がどのIDか
print('\n=== "car"/"bicycle" の現在のID ===')
c.execute("SELECT class_id, class_name FROM Class WHERE LOWER(class_name) IN ('car', 'bicycle')")
for row in c.fetchall():
    print(f'  "{row[1]}" = ID {row[0]}')

conn.close()
