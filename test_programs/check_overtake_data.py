import sqlite3
import os

print("Searching for database files with Detection table...")

# 複数のDB候補をチェック
db_candidates = [
    'ADC.db',
    'adc_data.db', 
    'database.db',
    'tracking_results.db',
    os.path.join('db', 'my_app.db'),
    os.path.join('db', 'my_app_data.db')
]

found_db = None

for db_path in db_candidates:
    if not os.path.exists(db_path):
        continue
    
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # テーブル一覧
        tables = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        
        if 'Detection' in tables:
            print(f"\n===== Found Detection table in: {db_path} =====")
            found_db = db_path
            
            # overtakeデータの確認
            total = c.execute('SELECT COUNT(*) FROM Detection').fetchone()[0]
            print(f'全検出レコード数: {total}')
            
            overtake_1 = c.execute('SELECT COUNT(*) FROM Detection WHERE overtake = 1').fetchone()[0]
            print(f'overtake=1のレコード数: {overtake_1}')
            
            overtake_not_null = c.execute('SELECT COUNT(*) FROM Detection WHERE overtake IS NOT NULL').fetchone()[0]
            print(f'overtakeがNULL以外のレコード数: {overtake_not_null}')
            
            # overtake値の分布
            dist = c.execute('SELECT overtake, COUNT(*) FROM Detection GROUP BY overtake LIMIT 10').fetchall()
            print(f'\novertake列の値の分布:')
            for val, count in dist:
                print(f'  overtake={val}: {count}件')
            
            # サンプルデータ
            if overtake_1 > 0:
                samples = c.execute('SELECT auto_id, run_id, frame_num, overtake, overtake_after, overtake_by FROM Detection WHERE overtake = 1 LIMIT 5').fetchall()
                print(f'\novertake=1のサンプルデータ (最初の5件):')
                for s in samples:
                    print(f'  ID={s[0]}, Run={s[1]}, Frame={s[2]}, overtake={s[3]}, overtake_after={s[4]}, overtake_by={s[5]}')
        
        conn.close()
    except Exception as e:
        print(f'Error checking {db_path}: {e}')

if not found_db:
    print("\nDetection table not found in any database!")
