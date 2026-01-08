from flask import render_template, request, jsonify, redirect, url_for, flash, current_app
import os
import time

from . import main
from ..modules import db_manager as dbm
from ..modules.db_manager import (
    MAIN_DB_PATH,
    configure_connection,
    get_database_sidecar_files,
    diagnose_sqlite_database,
    replace_main_database,
    create_new_main_database,
    vacuum_database,
    DatabaseInitializationError,
)

@main.route("/manage_db")
def manage_db_view():
    """データベース管理機能（Vacuum, Reset, Replace, Diagnose）を提供するページ。"""
    try:
        sidecars = get_database_sidecar_files(MAIN_DB_PATH)
        for s in sidecars:
            if s["size"] > 0:
                s["size_kb"] = f"{s['size'] / 1024:.1f} KB"
            else:
                s["size_kb"] = "0 B"
        
        diagnosis = diagnose_sqlite_database(MAIN_DB_PATH)
    except Exception as e:
        current_app.logger.exception("Failed to load DB diagnostics")
        flash(f"DB情報の取得に失敗しました: {e}", "danger")
        sidecars = []
        diagnosis = {"ok": False, "error": str(e)}

    return render_template(
        "manage_db.html",
        title="Database Management",
        db_path=MAIN_DB_PATH,
        sidecars=sidecars,
        diagnosis=diagnosis,
    )

@main.route("/optimize_database", methods=["POST"])
def optimize_database():
    """データベースをVACUUMしてサイズを最適化する。"""
    try:
        initial_size = os.path.getsize(MAIN_DB_PATH)
        vacuum_database()
        final_size = os.path.getsize(MAIN_DB_PATH)
        reduced = initial_size - final_size
        msg = f"データベースを最適化しました。削減サイズ: {reduced / 1024:.1f} KB"
        flash(msg, "success")
    except Exception as e:
        current_app.logger.exception("Vacuum failed")
        flash(f"最適化に失敗しました: {e}", "danger")
    return redirect(url_for("main.manage_db_view"))

@main.route("/reset_database", methods=["POST"])
def reset_database_route():
    """データベースを新規作成（リセット）する。"""
    try:
        create_new_main_database(MAIN_DB_PATH)
        flash("新しいデータベースを作成しました。", "success")
    except DatabaseInitializationError as e:
        flash(f"データベースの初期化に失敗しました: {e}", "danger")
    except Exception as e:
        current_app.logger.exception("Reset failed")
        flash(f"リセット操作中にエラーが発生しました: {e}", "danger")
    return redirect(url_for("main.manage_db_view"))


@main.route("/register_location", methods=["POST"])
def register_location():
    """新しい観測地点(Location)を登録する"""
    name = request.form.get("location_name", "").strip()
    if not name:
        flash("地点名を入力してください", "warning")
        return redirect(request.referrer or url_for("main.index"))
        
    try:
        from ..modules.db_manager import register_location
        loc_id = register_location(name)
        flash(f"地点 '{name}' を登録しました (ID: {loc_id})", "success")
    except Exception as e:
        flash(f"地点登録エラー: {e}", "danger")
        
    return redirect(request.referrer or url_for("main.index"))
