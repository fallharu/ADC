import sqlite3
import os

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== クラスID確認 ===')
target_names = ['horse', 'car', 'bicycle', 'motorcycle', 'bus', 'truck']
placeholders = ','.join(['?'] * len(target_names))
c.execute(f"SELECT class_id, class_name FROM Class WHERE LOWER(class_name) IN ({placeholders})", target_names)
rows = c.fetchall()
for cid, name in rows:
    print(f'  ID {cid}: {name}')

print('\n=== .env ファイル確認 ===')
env_path = '.env'
if os.path.exists(env_path):
    print(f'  {env_path} が存在します (絶対パス: {os.path.abspath(env_path)})')
    with open(env_path, 'r', encoding='utf-8') as f:
        content = f.read()
        print('  --- 内容(一部) ---')
        # Show lines related to OVERTAKE
        for line in content.splitlines():
            if 'OVERTAKE' in line:
                print(f'  {line}')
else:
    print(f'  {env_path} が見つかりません')

conn.close()
