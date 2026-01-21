import sqlite3

# 正しいパスでデータベースに接続
conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

# テーブルスキーマを取得
c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='TrafficCount'")
result = c.fetchone()

if result:
    print("=== TrafficCountテーブルのスキーマ ===")
    print(result[0])
    print()
    
    # カラム情報を取得
    c.execute("PRAGMA table_info(TrafficCount)")
    columns = c.fetchall()
    print("=== カラム情報 ===")
    for col in columns:
        print(f"  {col[1]} ({col[2]})")
    
    # データ件数を確認
    c.execute("SELECT COUNT(*) FROM TrafficCount")
    count = c.fetchone()[0]
    print(f"\n総レコード数: {count}")
    
else:
    print("TrafficCountテーブルが見つかりません")
    print("\n=== 存在するテーブル一覧 ===")
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    for table in tables:
        print(f"  - {table[0]}")

conn.close()
