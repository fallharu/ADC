import sys
sys.path.insert(0, 'Source_code')

from modules.db_manager import init_db

# データベースを初期化（テーブルが存在しない場合のみ作成）
print("データベースを初期化しています...")
init_db()
print("初期化完了: TrafficCountテーブルが作成されました")
