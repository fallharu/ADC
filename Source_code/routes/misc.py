from flask import send_from_directory, request, flash, redirect, url_for, current_app
import os
from . import main
from ..modules.db_manager import resolve_output_root

CSV_COLUMN_GUIDE_PATH = os.path.join("docs", "csv_column_guide.csv") # Example path

@main.route("/downloads/csv_columns")
def download_csv_column_guide():
    if not os.path.exists(CSV_COLUMN_GUIDE_PATH):
        flash("CSVカラム説明ファイルが見つかりません。", "danger")
        if request.referrer:
            return redirect(request.referrer)
        return redirect(url_for("main.index"))
        
    directory = os.path.dirname(os.path.abspath(CSV_COLUMN_GUIDE_PATH))
    filename = os.path.basename(CSV_COLUMN_GUIDE_PATH)
    return send_from_directory(directory, filename, as_attachment=True)


@main.route("/results/<path:filename>")
def results_file_serve(filename):
    directory = resolve_output_root()
    return send_from_directory(directory, filename)


@main.route("/exports/<path:filename>")
def exports_file_serve(filename):
    """エクスポートされたファイルをダウンロードするルート"""
    upload_folder = current_app.config.get("UPLOAD_FOLDER", "uploads")
    export_dir = os.path.join(upload_folder, "exports")
    if not os.path.isabs(export_dir):
        export_dir = os.path.abspath(export_dir)
    return send_from_directory(export_dir, filename, as_attachment=True)


@main.route("/reset_runs", methods=["POST"])
def reset_runs():
    """Runデータを全てリセットする。"""
    try:
        from ..modules.db_manager import reset_run_records
        reset_run_records()
        flash("すべてのRunデータをリセットしました。", "success")
    except Exception as e:
        current_app.logger.exception("Failed to reset runs")
        flash(f"リセットに失敗しました: {e}", "danger")
    return redirect(url_for("main.index"))


@main.route("/ensure_default_classes", methods=["POST"])
def ensure_default_classes():
    """デフォルトクラスをDBに登録する。"""
    try:
        from ..modules.db_manager import MAIN_DB_PATH, get_or_create_class_id
        import sqlite3
        
        # Standard classes to ensure
        default_classes = [
            "bicycle", "car", "bus", "truck", "motorcycle", "person"
        ]
        
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            for cls_name in default_classes:
                get_or_create_class_id(conn, cls_name)
                
        flash("デフォルトクラス (bicycle, car, etc.) を登録しました。", "success")
    except Exception as e:
        current_app.logger.exception("Failed to ensure default classes")
        flash(f"クラス登録に失敗しました: {e}", "danger")
    return redirect(url_for("main.index"))


@main.route("/api/update_folder_settings", methods=["POST"])
def update_folder_settings_api():
    """フォルダ設定（サブフォルダ設定含む）を更新するAPI"""
    from flask import jsonify

    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        folder_path = data.get("folder_path")
        if not folder_path:
            return jsonify({"status": "error", "message": "folder_path is required"}), 400

        # セキュリティチェック: ディレクトリトラバーサル防止
        if ".." in folder_path:
             return jsonify({"status": "error", "message": "Invalid folder path"}), 400
        
        # パス解決 (uploads基準と想定)
        upload_root = current_app.config.get("UPLOAD_FOLDER", "uploads")
        target_dir = os.path.abspath(os.path.join(upload_root, folder_path))
        
        if not os.path.exists(target_dir):
             return jsonify({"status": "error", "message": "Folder not found"}), 404

        from ..modules.folder_config import update_folder_settings
        
        # 更新内容を抽出
        updates = {}
        if "subfolders" in data:
            updates["subfolders"] = data["subfolders"]
            
        new_settings = update_folder_settings(target_dir, updates)
        
        return jsonify({
            "status": "success",
            "message": "Settings updated",
            "settings": new_settings
        })
        
    except Exception as e:
        current_app.logger.exception("Failed to update folder settings")
        return jsonify({"status": "error", "message": str(e)}), 500


@main.route("/api/update_run_metadata", methods=["POST"])
def update_run_metadata_api():
    """Runのメタデータ(年度、拡幅)を更新するAPI"""
    from flask import jsonify

    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        run_id = data.get("run_id")
        if not run_id:
            return jsonify({"status": "error", "message": "run_id is required"}), 400

        collection_year = data.get("collection_year")
        road_type = data.get("road_type")
        
        # db_manager から関数をインポート (循環参照回避のためここで行う場合もあるが、misc.pyならトップレベルでも可。
        # ただし、db_manager.pyの構造上、関数はモジュールトップレベルにある。)
        from ..modules.db_manager import update_run_metadata
        
        success = update_run_metadata(run_id, collection_year, road_type)
        
        if success:
            return jsonify({"status": "success", "message": "Metadata updated"})
        else:
            # 失敗原因: RunIDが存在しない、更新エラーなど
            return jsonify({"status": "error", "message": "Failed to update metadata. Invalid Run ID?"}), 404
            
    except Exception as e:
        current_app.logger.exception("Failed to update run metadata")
        return jsonify({"status": "error", "message": str(e)}), 500


@main.route("/api/batch_update_run_metadata", methods=["POST"])
def batch_update_run_metadata():
    """複数のRunのメタデータ(年度、拡幅)を一括更新するAPI"""
    from flask import jsonify

    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        run_ids = data.get("run_ids")
        if not run_ids or not isinstance(run_ids, list):
            return jsonify({"status": "error", "message": "run_ids list is required"}), 400

        collection_year = data.get("collection_year")
        road_type = data.get("road_type")
        
        # db_manager から関数をインポート
        from ..modules.db_manager import batch_update_run_metadata_direct
        
        # 空文字の場合はNoneに変換して「変更なし」として扱う
        # クライアント側で明示的に値をクリアしたい場合は別途対応が必要だが、
        # 現状のUIは「(変更なし)」が空文字を送ってくるため、これを無視する。
        if collection_year == "":
            collection_year = None
        if road_type == "":
            road_type = None

        updated_count, errors = batch_update_run_metadata_direct(run_ids, collection_year, road_type)
        
        return jsonify({
            "status": "success", 
            "message": f"Updated {updated_count} runs (Video records).",
            "updated_count": updated_count,
            "error_count": errors
        })
            
    except Exception as e:
        current_app.logger.exception("Failed to batch update run metadata")
        return jsonify({"status": "error", "message": str(e)}), 500


@main.route("/batch_update_runs", methods=["POST"])
def batch_update_runs_form():
    """Runメタデータ一括更新（フォーム送信・リダイレクト版）"""
    try:
        from ..modules.db_manager import batch_update_run_metadata_direct
        
        run_ids = request.form.getlist("run_ids")
        collection_year = request.form.get("collection_year")
        road_type = request.form.get("road_type")
        
        # run_idsに空文字などが含まれる場合のクリーニング
        valid_run_ids = []
        for rid in run_ids:
            try:
                if rid:
                    valid_run_ids.append(int(rid))
            except ValueError:
                pass
                
        if not valid_run_ids:
            flash("更新対象のRunが選択されていません。", "warning")
            return redirect(url_for("main.detections", mode="runs"))

        # 空文字ならNone (変更なし)
        if not collection_year:
            collection_year = None
        if not road_type:
            road_type = None
            
        if collection_year is None and road_type is None:
             flash("変更する項目を入力してください。", "warning")
             return redirect(url_for("main.detections", mode="runs"))

        updated, errors = batch_update_run_metadata_direct(valid_run_ids, collection_year, road_type)
        
        if errors > 0:
            flash(f"{updated}件更新しましたが、{errors}件のエラーが発生しました。", "warning")
        else:
            flash(f"{updated}件のRunを更新しました。", "success")
            
    except Exception as e:
        current_app.logger.exception("Failed to batch update runs via form")
        flash(f"エラーが発生しました: {e}", "danger")
        
    return redirect(url_for("main.detections", mode="runs"))
