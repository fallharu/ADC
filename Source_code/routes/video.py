from flask import render_template, request, jsonify, redirect, url_for, flash, current_app
import os
from werkzeug.utils import secure_filename
from . import main
from ..modules.utils import allowed_file, sanitize_folder_alias

PATH_LINK_FILENAME = ".pathlink"

@main.route("/upload", methods=["GET", "POST"])
def upload_video():
    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)

    if request.method == "POST":
        mode = request.form.get("mode", "upload")

        if mode == "link":
            folder_path = (request.form.get("folder_path") or "").strip()
            alias_input = (request.form.get("folder_alias") or "").strip()
            if not folder_path:
                flash("フォルダパスを入力してください。", "danger")
                return redirect(request.url)

            abs_path = os.path.abspath(folder_path)
            if not os.path.isdir(abs_path):
                flash("指定したフォルダが見つかりません。", "danger")
                return redirect(request.url)

            alias_source = alias_input or os.path.basename(abs_path)
            sanitized_alias = sanitize_folder_alias(alias_source)
            if not sanitized_alias:
                flash("登録名を正しく入力してください。", "danger")
                return redirect(request.url)

            target_dir = os.path.join(upload_folder, sanitized_alias)
            if os.path.exists(target_dir):
                link_file = os.path.join(target_dir, PATH_LINK_FILENAME)
                if os.path.isfile(link_file):
                    try:
                        with open(link_file, "r", encoding="utf-8") as existing_link:
                            existing_path = existing_link.read().strip()
                    except OSError:
                        existing_path = ""
                    if existing_path and os.path.abspath(existing_path) == abs_path:
                        flash("指定したフォルダは既に登録されています。", "info")
                        return redirect(url_for("main.detect"))
                flash("同名のフォルダが既に存在します。別名を指定してください。", "danger")
                return redirect(request.url)

            try:
                os.makedirs(target_dir, exist_ok=True)
            except OSError as exc:
                flash(f"フォルダ登録用のディレクトリ作成に失敗しました: {exc}", "danger")
                return redirect(request.url)

            link_file = os.path.join(target_dir, PATH_LINK_FILENAME)
            try:
                with open(link_file, "w", encoding="utf-8") as handle:
                    handle.write(abs_path)
            except OSError as exc:
                flash(f"フォルダ登録に失敗しました: {exc}", "danger")
                try:
                    if os.path.isfile(link_file):
                        os.remove(link_file)
                    if os.path.isdir(target_dir) and not os.listdir(target_dir):
                        os.rmdir(target_dir)
                except OSError:
                    pass
                return redirect(request.url)

            flash(f"フォルダを登録しました: {sanitized_alias}", "success")
            return redirect(url_for("main.detect"))

        file = request.files.get("file")
        if not file or file.filename == "":
            flash("動画ファイルを選択してください。", "danger")
            return redirect(request.url)
        if allowed_file(file.filename):
            filename = secure_filename(file.filename)
            save_path = os.path.join(upload_folder, filename)
            file.save(save_path)
            flash(f"アップロード完了: {filename}", "success")
            return redirect(url_for("main.index"))
        flash("対応していないファイル形式です。", "danger")
        return redirect(request.url)

    return render_template("upload.html")
