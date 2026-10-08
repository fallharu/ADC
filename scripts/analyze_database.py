import sqlite3
import os

# メインのデータベースを確認
db_path = r'C:\Users\kurok\Downloads\G_ADC\ADC_08\database.db'

if not os.path.exists(db_path):
    print(f"データベースが見つかりません: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# テーブル一覧を取得
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

print("【データベース内のテーブル】")
print("="*80)
for table in tables:
    print(f"  {table[0]}")

print("\n")

# 各テーブルのスキーマと件数を確認
for table in tables:
    table_name = table[0]
    print(f"\n{'='*80}")
    print(f"テーブル: {table_name}")
    print(f"{'='*80}")
    
    # スキーマを取得
    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = cursor.fetchall()
    print("\nカラム構成:")
    for col in columns:
        print(f"  [{col[1]}] {col[2]}")
    
    # レコード数を取得
    cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
    count = cursor.fetchone()[0]
    print(f"\nレコード数: {count}件")
    
    # サンプルデータを表示（最初の3件）
    if count > 0:
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 3;")
        samples = cursor.fetchall()
        print(f"\nサンプルデータ（最大3件）:")
        col_names = [col[1] for col in columns]
        for i, sample in enumerate(samples, 1):
            print(f"\n  --- レコード {i} ---")
            for col_name, value in zip(col_names, sample):
                print(f"  {col_name}: {value}")

conn.close()

print("\n" + "="*80)
print("データベース分析完了")
