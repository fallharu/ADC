# Source_code/app.py
from flask import Flask
import os
from dotenv import load_dotenv
from dotenv import load_dotenv

# .envファイルを読み込む
load_dotenv()
UPLOAD_FOLDER = os.getenv("Upload_folder", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# routesパッケージからBlueprintをインポート
from .routes import main

app = Flask(__name__, template_folder="../templates")
app.secret_key = "a-very-secret-key-for-adc-system"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Blueprintを登録
app.register_blueprint(main, url_prefix="/")

# データベースマイグレーション
import sqlite3
from .modules.db_manager import ensure_video_metadata_columns, MAIN_DB_PATH

with app.app_context():
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        ensure_video_metadata_columns(conn)
        print("✅ Database migration completed: video metadata columns ensured")
    
    # [ABC-B] ルート診断: 全エンドポイントを出力
    print("\n" + "="*80)
    print("[ABC-B] Registered Flask Routes:")
    print("="*80)
    for rule in app.url_map.iter_rules():
        methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
        print(f"  {rule.endpoint:50} {methods:20} {rule.rule}")
        if '/preview' in rule.rule:
            print(f"    ⭐ PREVIEW API FOUND: {rule.rule}")
    print("="*80 + "\n")


if __name__ == '__main__':
    app.run(debug=True)
