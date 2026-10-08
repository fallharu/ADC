# Source_code/app.py
from flask import Flask, jsonify, render_template, request
import os
from dotenv import load_dotenv
from dotenv import load_dotenv

# .envファイルを読み込む
load_dotenv()
UPLOAD_FOLDER = os.getenv("Upload_folder", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# routesパッケージからBlueprintをインポート
from .routes import main
from .routes.verify_route import verify_bp
from .routes.results import results_bp

app = Flask(__name__, template_folder="../templates")
app.secret_key = "a-very-secret-key-for-adc-system"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Blueprintを登録
from .routes.check_sheet_routes import check_sheet_bp
app.register_blueprint(main, url_prefix="/")
app.register_blueprint(verify_bp)
app.register_blueprint(check_sheet_bp)
app.register_blueprint(results_bp)


def _wants_json_error():
    if request.path.startswith("/api/"):
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


@app.errorhandler(404)
def page_not_found(error):
    if _wants_json_error():
        return jsonify({"error": "Not found", "message": "The requested resource was not found."}), 404
    return render_template(
        "error.html",
        status_code=404,
        title="ページが見つかりません",
        message="指定されたページは存在しないか、移動された可能性があります。",
    ), 404


@app.errorhandler(500)
def internal_server_error(error):
    if _wants_json_error():
        return jsonify({"error": "Internal server error", "message": "An unexpected error occurred."}), 500
    return render_template(
        "error.html",
        status_code=500,
        title="サーバーエラー",
        message="処理中に問題が発生しました。直前の操作を確認して、必要に応じてログを確認してください。",
    ), 500

# データベースマイグレーション
import sqlite3
from .modules.db_manager import (
    ensure_video_metadata_columns,
    ensure_detection_columns,
    ensure_manual_overtake_event_columns,
    ensure_overtake_event_columns,
    ensure_manual_annotation_schema,
    ensure_normalized_detection_schema,
    MAIN_DB_PATH,
)

with app.app_context():
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        ensure_video_metadata_columns(conn)
        ensure_detection_columns(conn)
        ensure_manual_overtake_event_columns(conn)
        ensure_overtake_event_columns(conn)
        ensure_normalized_detection_schema(conn)
        print("[OK] Database migration completed: all schema columns ensured")
    ensure_manual_annotation_schema()  # 内部でDB接続を管理
    
    # [ABC-B] ルート診断: 全エンドポイントを出力
    print("\n" + "="*80)
    print("[ABC-B] Registered Flask Routes:")
    print("="*80)
    for rule in app.url_map.iter_rules():
        methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
        print(f"  {rule.endpoint:50} {methods:20} {rule.rule}")
        if '/preview' in rule.rule:
            print(f"    PREVIEW API FOUND: {rule.rule}")
    print("="*80 + "\n")


if __name__ == '__main__':
    app.run(debug=True)
