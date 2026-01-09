import sqlite3

# データベースに接続
conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print("既存のTrafficCountテーブルを削除...")
c.execute("DROP TABLE IF EXISTS TrafficCount")

print("新しいTrafficCountテーブルを作成...")
c.execute("""
    CREATE TABLE TrafficCount (
        count_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER,
        line_name TEXT,
        object_type TEXT,
        direction TEXT,
        count INTEGER,
        created_at TEXT,
        FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
    )
""")

conn.commit()

# 確認
c.execute("PRAGMA table_info(TrafficCount)")
columns = c.fetchall()
print("\n=== 新しいカラム構成 ===")
for col in columns:
    print(f"  {col[1]} ({col[2]})")

print("\n✓ TrafficCountテーブルが正常に再作成されました")

conn.close()
