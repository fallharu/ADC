import sqlite3
import shutil
import os

BACKUP_PATH = 'db/my_app_data.db.backup_20260117_102900'
TARGET_PATH = 'db/my_app_data.db'

# Step 1: 現在のDBをバックアップ（念のため）
if os.path.exists(TARGET_PATH):
    safety_backup = TARGET_PATH + '.before_restore'
    shutil.copy2(TARGET_PATH, safety_backup)
    print(f"現在のDBを {safety_backup} にバックアップしました")

# Step 2: バックアップDBをコピー
shutil.copy2(BACKUP_PATH, TARGET_PATH)
print(f"バックアップから復元: {BACKUP_PATH} -> {TARGET_PATH}")

# Step 3: 全テーブルのデータを削除（スキーマは維持）
conn = sqlite3.connect(TARGET_PATH)
c = conn.cursor()

# テーブル一覧取得
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
tables = [row[0] for row in c.fetchall()]

print(f"\n{len(tables)} テーブルのデータを削除中...")
for table in tables:
    try:
        c.execute(f'DELETE FROM "{table}"')
        print(f"  {table}: {c.rowcount} 行削除")
    except Exception as e:
        print(f"  {table}: エラー - {e}")

conn.commit()

# Step 4: VACUUM でファイルサイズを縮小
print("\nVACUUM実行中...")
conn.execute("VACUUM")
conn.close()

# 結果表示
new_size = os.path.getsize(TARGET_PATH)
print(f"\n完了！新しいDBサイズ: {new_size / 1024:.1f} KB")
print("スキーマは維持され、データは空になりました。")
