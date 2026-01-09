import sqlite3

conn = sqlite3.connect('Source_code/modules/main.db')
c = conn.cursor()

# テーブルスキーマを取得
c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='TrafficCount'")
result = c.fetchone()

if result:
    print("=== TrafficCountテーブルのスキーマ ===")
    print(result[0])
    print()
    
    # サンプルデータを取得
    c.execute("SELECT * FROM TrafficCount LIMIT 10")
    rows = c.fetchall()
    
    if rows:
        print("=== サンプルデータ ===")
        c.execute("PRAGMA table_info(TrafficCount)")
        columns = [col[1] for col in c.fetchall()]
        print("カラム:", ", ".join(columns))
        print()
        for row in rows:
            print(row)
    else:
        print("データが存在しません")
    
    # データ件数を確認
    c.execute("SELECT COUNT(*) FROM TrafficCount")
    count = c.fetchone()[0]
    print(f"\n総レコード数: {count}")
    
else:
    print("TrafficCountテーブルが見つかりません")

conn.close()
