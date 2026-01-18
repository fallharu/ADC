import os
from dotenv import load_dotenv

# 実装モジュールの読み込み前に環境変数を設定できるよう、
# 可能な限り早い段階で load_dotenv を呼び出す可能性があるが、
# app.py 内でも load_dotenv() されているため、ここでは上書きを優先する
load_dotenv()

# テスト環境の設定
os.environ["FLASK_ENV"] = "development"
# .env から TEST_DB_PATH を取得。なければデフォルト。
test_db = os.getenv("TEST_DB_PATH", "db/test_adc.db")
os.environ["MAIN_DB_PATH"] = test_db

from Source_code.app import app
from Source_code.modules import db_manager

def run_test_server():
    print("="*60)
    print("🚀 ADC Test Server Starting...")
    print(f"📁 Database Path: {os.environ['MAIN_DB_PATH']}")
    
    # DB初期化（テーブル作成・マイグレーション）
    print("🔧 Initializing Database...")
    try:
        db_manager.init_db()
        print("✅ Database initialized successfully.")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        return

    print("🌐 Access: http://127.0.0.1:5001")
    print("🛠️  Mode: Development / Debug")
    print("="*60)
    
    # port 5001 で起動（既存の run_test_server.py と合わせる）
    app.run(host="0.0.0.0", port=5001, debug=True)

if __name__ == '__main__':
    run_test_server()
