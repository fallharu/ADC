import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

# 1. Classテーブルの現在のマッピング確認
print('=== 現在の Class テーブル (重要IDのみ) ===')
target_ids = [1, 2, 3, 5, 7, 12, 13, 16]
c.execute(f"SELECT class_id, class_name FROM Class WHERE class_id IN ({','.join(map(str, target_ids))})")
for cid, name in c.fetchall():
    print(f"  ID {cid}: {name}")

# 2. Run 100249 の検出クラス分布
print('\n=== Run 100249 検出内訳 (修正後) ===')
c.execute("""
    SELECT d.class_id, c.class_name, COUNT(*) as cnt
    FROM Detection d
    LEFT JOIN Class c ON d.class_id = c.class_id
    WHERE d.run_id = 100249
    GROUP BY d.class_id, c.class_name
    ORDER BY cnt DESC
""")
results = c.fetchall()

has_car = False
car_classes = {'car', 'bus', 'truck', 'vehicle'} 

if not results:
    print("  (データなし)")
else:
    for row in results:
        cid = row[0]
        cname = str(row[1]) if row[1] else "(不明)"
        count = row[2]
        print(f"  ID {cid} ({cname}): {count} 件")
        
        if cname.lower() in car_classes:
            has_car = True

print(f"\n判定結果: 車両クラス(car/bus/truck)は {'あり ✅' if has_car else 'なし ❌'}")

conn.close()
