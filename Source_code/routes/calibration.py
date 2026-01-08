



from flask import jsonify, request, current_app, render_template, flash, redirect, url_for, send_from_directory, send_file

import os

import sqlite3

import json

import cv2

import base64

import numpy as np

import io

import hashlib



from . import main

from ..modules.video_utils import probe_video, load_video_frame

from ..modules import db_manager as dbm

from ..modules.db_manager import MAIN_DB_PATH

from ..modules.folder_utils import find_source_video_path



from dotenv import load_dotenv



load_dotenv()



def ensure_calibration_dir():

    opt_files = os.getenv("Opt_files", "./output")

    # Clean up path if it has quotes

    opt_files = opt_files.strip('"').strip("'")

    

    calib_dir = os.path.join(opt_files, 'calibrations')

    os.makedirs(calib_dir, exist_ok=True)

    return calib_dir



def list_calibration_profiles():

    d = ensure_calibration_dir()

    profiles = []

    if os.path.exists(d):

        for f in os.listdir(d):

            if f.endswith(".json"):

                 profiles.append(f[:-5]) # remove .json

    return sorted(profiles)



def load_all_profile_metadata(profiles):

    meta = {}

    d = ensure_calibration_dir()

    for p in profiles:

        path = os.path.join(d, f"{p}.json")

        try:

            with open(path, "r", encoding="utf-8") as f:

                data = json.load(f)

                meta[p] = data

        except:

            meta[p] = {}

    return meta



def load_folder_settings(folder_path):

    settings_path = os.path.join(folder_path, "folder_settings.json")

    if os.path.exists(settings_path):

        try:

            with open(settings_path, 'r', encoding='utf-8') as f:

                return json.load(f)

        except:

            pass

    return {"profile": "", "is_always_display": False}



def save_folder_settings(folder_path, settings):

    settings_path = os.path.join(folder_path, "folder_settings.json")

    try:

        with open(settings_path, 'w', encoding='utf-8') as f:

            json.dump(settings, f, indent=2, ensure_ascii=False)

    except Exception as e:

        current_app.logger.error(f"Failed to save settings: {e}")



@main.route("/api/calibration_check/folders")

def calibration_check_folders_api():

    try:

        folders = set()

        folder_metadata = {}  # path -> {year, road, profile, alias, is_always_display}

        

        # Get folders from ProcessLog table joined with Video for metadata

        if os.path.exists(MAIN_DB_PATH):

            with sqlite3.connect(MAIN_DB_PATH) as conn:

                conn.row_factory = sqlite3.Row

                cursor = conn.cursor()

                

                # JOIN ProcessLog with Video to get all metadata

                cursor.execute("""

                    SELECT DISTINCT 

                        p.output_folder, 

                        p.folder_alias, 

                        p.calibration_profile,

                        p.run_id,

                        v.collection_year,

                        v.road_type

                    FROM ProcessLog p

                    LEFT JOIN Video v ON p.video_id = v.video_id

                    WHERE p.output_folder IS NOT NULL AND p.output_folder != ''

                """)

                

                for row in cursor.fetchall():

                    folder_path = row["output_folder"]

                    if folder_path:

                        norm = os.path.normpath(folder_path)

                        folders.add(norm)

                        

                        # Load local settings

                        local_settings = load_folder_settings(norm)

                        

                        # For compatibility with post_process: use folder_alias as primary key

                        # Store both folder_alias and output_folder for flexible access

                        folder_metadata[norm] = {

                            "alias": row["folder_alias"] or os.path.basename(norm),

                            "folder_alias": row["folder_alias"],  # Store for later use

                            "profile": row["calibration_profile"] or local_settings.get("profile", ""),

                            "collection_year": row["collection_year"],

                            "road_type": row["road_type"],

                            "run_id": row["run_id"],

                            "is_always_display": local_settings.get("is_always_display", False)

                        }

        

        valid_folders = sorted([f for f in folders if os.path.isdir(f)])

        

        profiles = list_calibration_profiles()

        profile_metadata = load_all_profile_metadata(profiles)



        

        folder_list = []

        calib_dir = ensure_calibration_dir()

        

        for f in valid_folders:

            meta = folder_metadata.get(f, {})

            profile_name = meta.get("profile", "")

            

            # Check if calibration lines exist for this profile

            has_calibration_lines = False

            if profile_name:

                profile_path = os.path.join(calib_dir, f"{profile_name}.json")

                if os.path.exists(profile_path):

                    try:

                        with open(profile_path, "r", encoding="utf-8") as fh:

                            calib_data = json.load(fh)

                            lines = calib_data.get("lines", {})

                            # Check if any line has data

                            has_calibration_lines = any(

                                lines.get(key) for key in [

                                    "left_white_line", "right_white_line", 

                                    "center_line", "left_mid_line", "right_mid_line"

                                ]

                            )

                    except Exception:

                        pass

            

            folder_list.append({

                "alias": meta.get("alias", os.path.basename(f)),

                "path": f,

                "profile": profile_name,

                "db_profile": profile_name,

                "folder_alias": meta.get("folder_alias"),  # Add for update API

                "collection_year": meta.get("collection_year"),

                "road_type": meta.get("road_type"),

                "run_id": meta.get("run_id"),

                "is_always_display": meta.get("is_always_display", False),

                "has_calibration_lines": has_calibration_lines  # NEW: Status indicator

            })



            

        return jsonify({

            "folders": folder_list,

            "profiles": profiles,

            "profile_metadata": profile_metadata,

            "known_folders": valid_folders

        })

        

    except Exception as e:

        current_app.logger.exception("List folders failed")

        return jsonify({"error": str(e)}), 500



@main.route("/api/calibration_check/update_folder", methods=["POST"])

def calibration_check_update_folder_api():

    payload = request.get_json(silent=True) or {}

    folder_path = payload.get("folder_path")

    new_profile = payload.get("profile")

    collection_year = payload.get("collection_year")

    road_type = payload.get("road_type")

    is_always_display = payload.get("is_always_display")

    



    if not folder_path:

        return jsonify({"error": "No folder path"}), 400

        

    try:

        # Load existing local settings to preserve other keys

        local_settings = load_folder_settings(folder_path)

        settings_changed = False

        

        if new_profile is not None:

             local_settings["profile"] = new_profile

             settings_changed = True

             

        if is_always_display is not None:

             local_settings["is_always_display"] = is_always_display

             settings_changed = True



        if settings_changed:

            save_folder_settings(folder_path, local_settings)



        if os.path.exists(MAIN_DB_PATH):

             with sqlite3.connect(MAIN_DB_PATH) as conn:

                # Get folder_alias for this output_folder (for compatibility with post_process)

                cursor = conn.cursor()

                cursor.execute("SELECT DISTINCT folder_alias FROM ProcessLog WHERE output_folder = ? LIMIT 1", (folder_path,))

                row = cursor.fetchone()

                folder_alias = row[0] if row else None

                

                # Update Profile

                # Priority 1: Update via folder_alias (compatible with post_process)

                if new_profile and folder_alias:

                    conn.execute("UPDATE ProcessLog SET calibration_profile = ? WHERE folder_alias = ?", (new_profile, folder_alias))

                # Fallback: Update via output_folder (legacy compatibility)

                elif new_profile:

                    conn.execute("UPDATE ProcessLog SET calibration_profile = ? WHERE output_folder = ?", (new_profile, folder_path))

                

                # Update Video Metadata via ProcessLog mapping

                if collection_year is not None or road_type is not None:

                    # Find video_ids associated with this output_folder

                    cursor.execute("SELECT video_id FROM ProcessLog WHERE output_folder = ?", (folder_path,))

                    video_ids = [row[0] for row in cursor.fetchall()]

                    

                    if video_ids:

                        updates = []

                        params = []

                        if collection_year is not None:

                            updates.append("collection_year = ?")

                            params.append(collection_year)

                        if road_type is not None:

                            updates.append("road_type = ?")

                            params.append(road_type)

                        

                        if updates:

                             # Construct WHERE IN clause

                             placeholders = ','.join('?' for _ in video_ids)

                             sql = f"UPDATE Video SET {', '.join(updates)} WHERE video_id IN ({placeholders})"

                             params.extend(video_ids)

                             conn.execute(sql, params)

                

                conn.commit()

                

        return jsonify({"ok": True})

    except Exception as e:

        current_app.logger.exception("Update failed")

        return jsonify({"error": str(e)}), 500



@main.route("/calibration")
def calibration_view():
    """キャリブレーションエディタ（作成・編集）を表示する"""
    run_id = request.args.get("run_id", type=int)
    profile_name = request.args.get("profile") or request.args.get("load")
    path_hint = request.args.get("path_hint")
    
    # If no run_id provided (e.g. from "New Create"), use the latest run as context
    # Use 'is None' check because run_id=0 is valid
    if run_id is None:
        try:
            with sqlite3.connect(MAIN_DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(run_id) FROM ProcessLog")
                row = cursor.fetchone()
                if row and row[0] is not None:
                    run_id = row[0]
        except Exception:
            pass
            
    return render_template(
        "calibration.html", 
        run_id=run_id,
        profile_name=profile_name,
        path_hint=path_hint
    )

@main.route("/calibration_check")

def calibration_check_view():

    """フォルダ別キャリブレーション確認ページを表示する。"""

    return render_template("calibration_check.html", title="Calibration Verification")





@main.route("/api/calibration_check/folder_info", methods=["POST"])

def calibration_check_folder_info_api():

    """指定されたパスのフォルダ情報（存在確認・プロファイル設定）を返す。"""

    payload = request.get_json(silent=True) or {}

    folder_path = payload.get("folder_path")



    if not folder_path:

        return jsonify({"error": "フォルダパスが指定されていません。"}), 400

    

    # Remove quotes if user copied as path

    folder_path = folder_path.strip('"').strip("'")

    

    if not os.path.isdir(folder_path):

        return jsonify({"error": "指定されたパスはフォルダではありません。"}), 404



    # Get metadata from database by joining ProcessLog and Video

    collection_year = None

    road_type = None

    db_profile = None

    alias = ""

    

    try:

        with sqlite3.connect(MAIN_DB_PATH) as conn:

            conn.row_factory = sqlite3.Row

            cursor = conn.cursor()

            

            # JOIN ProcessLog with Video to get metadata

            cursor.execute("""

                SELECT 

                    p.folder_alias, 

                    p.calibration_profile,

                    v.collection_year,

                    v.road_type

                FROM ProcessLog p

                LEFT JOIN Video v ON p.video_id = v.video_id

                WHERE p.output_folder = ? 

                LIMIT 1

            """, (folder_path,))

            row = cursor.fetchone()

            if row:

                alias = row["folder_alias"]

                db_profile = row["calibration_profile"]

                collection_year = row["collection_year"]

                road_type = row["road_type"]

    except Exception:

        pass  # Use defaults if DB query fails

            

    return jsonify({

        "path": folder_path,

        "alias": alias or os.path.basename(folder_path),

        "profile": db_profile or "",

        "db_profile": db_profile or "",

        "collection_year": collection_year,

        "road_type": road_type

    })





@main.route("/api/calibration_check/all_files")

def calibration_check_all_files_api():

    """全動画ファイルの一覧とメタデータを返す"""

    try:

        files = []

        if os.path.exists(MAIN_DB_PATH):

            with sqlite3.connect(MAIN_DB_PATH) as conn:

                conn.row_factory = sqlite3.Row

                cursor = conn.cursor()

                cursor.execute("""

                    SELECT 

                        v.video_id,

                        v.filename,

                        v.source_path,

                        v.collection_year,

                        v.road_type,

                        p.output_folder,

                        p.calibration_profile,

                        p.folder_alias

                    FROM Video v

                    LEFT JOIN ProcessLog p ON v.video_id = p.video_id

                    WHERE p.output_folder IS NOT NULL AND p.output_folder != ''

                    ORDER BY p.output_folder, v.filename

                """)

                for row in cursor.fetchall():

                    folder_path = row["output_folder"]

                    # Load local settings for fallback

                    local_settings = load_folder_settings(folder_path)

                    

                    files.append({

                        "video_id": row["video_id"],

                        "filename": row["filename"],
                        "source_path": row["source_path"],  # Add source_path for calibration tool
                        "folder_path": folder_path,

                        "folder_alias": row["folder_alias"] or os.path.basename(folder_path),

                        "profile": row["calibration_profile"] or local_settings.get("profile", ""),

                        "collection_year": row["collection_year"],

                        "road_type": row["road_type"],

                        "db_profile": row["calibration_profile"] or "",

                        "is_always_display": local_settings.get("is_always_display", False)

                    })

        return jsonify({"files": files})

    except Exception as e:

        current_app.logger.exception("List all files failed")

        return jsonify({"error": str(e)}), 500



@main.route("/api/calibration_check/thumbnail")

def calibration_check_thumbnail_api():

    """指定されたフォルダの代表サムネイル画像を返す（キャッシュ対応）。"""

    folder_path = request.args.get("folder")

    if not folder_path:

        return jsonify({"error": "Folder path required"}), 400

        

    folder_path = folder_path.strip('"').strip("'")
    folder_path = folder_path.replace("\\", "/")

    current_app.logger.info(f"[THUMBNAIL] Received request for folder: {folder_path}")
    current_app.logger.info(f"Thumb req: {folder_path} (exists={os.path.exists(folder_path)})")

    

    # --- Cache Logic ---
    # Normalize to forward slashes for hashing consistency
    norm_path = folder_path.replace("\\", "/")
    current_app.logger.info(f"Thumb req: {folder_path} (norm={norm_path})")
    
    # Get calibration profile early for cache key
    # Prioritize folder_alias for compatibility with post_process page
    calibration_profile_for_cache = None
    folder_alias_match = None
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # First try: Get folder_alias from output_folder
            cursor.execute("""
                SELECT DISTINCT folder_alias, calibration_profile
                FROM ProcessLog 
                WHERE output_folder = ? 
                LIMIT 1
            """, (folder_path,))
            row = cursor.fetchone()
            if row:
                folder_alias_match = row["folder_alias"]
                if row["calibration_profile"]:
                    calibration_profile_for_cache = row["calibration_profile"]
    except Exception:
        pass
    
    # --- Cache Logic ---
    cache_dir = os.path.join(os.getcwd(), "cache", "img")
    os.makedirs(cache_dir, exist_ok=True)
    # Include profile in cache key to invalidate when profile changes
    cache_key = f"{norm_path}|{calibration_profile_for_cache or 'no_profile'}"
    path_hash = hashlib.md5(cache_key.encode('utf-8')).hexdigest()
    cache_file = os.path.join(cache_dir, f"{path_hash}.jpg")

    if os.path.exists(cache_file):
        return send_file(cache_file, mimetype='image/jpeg')

    # --- Generation Logic ---
    sample_video_path = None
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            sql = """
                SELECT v.source_path
                FROM ProcessLog p
                JOIN Video v ON p.video_id = v.video_id
                WHERE p.output_folder LIKE ? 
                LIMIT 1
            """
            with open("debug_output.txt", "a", encoding="utf-8") as f:
                f.write(f"DEBUG: Searching DB for {folder_path}\n")
            cursor.execute(sql, (folder_path,))
            row = cursor.fetchone()
            if row and row["source_path"]:
                 with open("debug_output.txt", "a", encoding="utf-8") as f:
                    f.write(f"DEBUG: Hit 1: {row['source_path']} Exists: {os.path.exists(row['source_path'])}\n")
            if row and row["source_path"] and os.path.exists(row["source_path"]):
                sample_video_path = row["source_path"]
            
            # Retry 1: Windows backslashes (Double Wildcard)
            if not sample_video_path:
                win_path = "%" + folder_path.replace("/", "\\") + "%"
                with open("debug_output.txt", "a", encoding="utf-8") as f:
                    f.write(f"DEBUG: Retry LIKE {win_path}\n")
                cursor.execute(sql, (win_path,))
                row = cursor.fetchone()
                if row and row["source_path"]:
                     with open("debug_output.txt", "a", encoding="utf-8") as f:
                        f.write(f"DEBUG: Hit 2: {row['source_path']} Exists: {os.path.exists(row['source_path'])}\n")
                if row and row["source_path"] and os.path.exists(row["source_path"]):
                    sample_video_path = row["source_path"]

            # Retry 2: Absolute Path (Double Wildcard)
            if not sample_video_path:
                abs_path = "%" + os.path.abspath(folder_path).replace("/", "\\") + "%"
                with open("debug_output.txt", "a", encoding="utf-8") as f:
                    f.write(f"DEBUG: Retry Abs {abs_path}\n")
                cursor.execute(sql, (abs_path,))
                row = cursor.fetchone()
                if row and row["source_path"]:
                     with open("debug_output.txt", "a", encoding="utf-8") as f:
                        f.write(f"DEBUG: Hit 3: {row['source_path']} Exists: {os.path.exists(row['source_path'])}\n")
                if row and row["source_path"] and os.path.exists(row["source_path"]):
                    sample_video_path = row["source_path"]

            # Retry 3: Basename (Already Wildcard prefix, add suffix?)
            # Basename usually doesn't need suffix unless partial match risk.
            if not sample_video_path:
                basename = os.path.basename(folder_path.replace("\\", "/").rstrip("/"))
                wild_base = "%" + basename + "%" # Use double wild here too
                with open("debug_output.txt", "a", encoding="utf-8") as f:
                    f.write(f"DEBUG: Retry Basename {wild_base}\n")
                cursor.execute(sql, (wild_base,))
                row = cursor.fetchone()
                if row and row["source_path"]:
                     with open("debug_output.txt", "a", encoding="utf-8") as f:
                        f.write(f"DEBUG: Hit 4: {row['source_path']} Exists: {os.path.exists(row['source_path'])}\n")
                if row and row["source_path"] and os.path.exists(row["source_path"]):
                    sample_video_path = row["source_path"]

    except Exception as e:
        current_app.logger.warning(f"DB lookup failed: {e}")

    # Fallback: Search in folder
    if not sample_video_path:
        check_path = folder_path.replace("/", os.sep) # Use native for fs
        if os.path.isdir(check_path):
             # ... existing fs logic ...
             pass # I need to keep the fs logic below
             
    # Since I'm replacing a block, I need to be careful not to delete the fs logic below if I don't include it.
    # The target block ended at 730 which was inside the Retry logic I added in previous step.
    # I should re-read 720-750 to be safe or rewrite the FS logic here too.
    
    # Let's rewrite FS logic to be clean.
    check_path = folder_path.replace("/", os.sep)
    if not sample_video_path and os.path.isdir(check_path):
        video_exts = {".mp4", ".avi", ".mov", ".mkv"}
        try:
            for f in os.listdir(check_path):
                if os.path.splitext(f)[1].lower() in video_exts:
                    sample_video_path = os.path.join(check_path, f)
                    break
        except Exception:
            pass

    if not sample_video_path:
        current_app.logger.warning(f"Video not found for: {folder_path} (win={folder_path.replace('/', '\\\\')})")
        return jsonify({"error": "Video not found"}), 404

    # Get calibration profile for this folder
    # Try multiple formats: absolute + backslash/forward slash + relative path
    calibration_profile = None
    folder_path_backslash = folder_path.replace("/", "\\")
    
    # Also try relative path from output folder
    output_folder = os.getenv("Opt_files", "output")
    folder_path_relative = None
    try:
        abs_folder = os.path.abspath(folder_path_backslash)
        abs_output = os.path.abspath(output_folder)
        if abs_folder.startswith(abs_output):
            folder_path_relative = os.path.relpath(abs_folder, abs_output).replace("\\", "/")
            current_app.logger.info(f"[THUMBNAIL] Relative path: {folder_path_relative}")
    except Exception as e:
        current_app.logger.warning(f"[THUMBNAIL] Could not compute relative path: {e}")
    
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Priority 1: Use folder_alias if we found it earlier (compatible with post_process)
            if folder_alias_match:
                current_app.logger.info(f"[THUMBNAIL] Using folder_alias: {folder_alias_match}")
                cursor.execute("""
                    SELECT calibration_profile 
                    FROM ProcessLog 
                    WHERE folder_alias = ?
                    LIMIT 1
                """, (folder_alias_match,))
                row = cursor.fetchone()
                if row and row["calibration_profile"]:
                    calibration_profile = row["calibration_profile"]
                    current_app.logger.info(f"[THUMBNAIL] Found calibration profile via folder_alias: {calibration_profile}")
            
            # Priority 2: Fallback to output_folder matching (legacy compatibility)
            if not calibration_profile:
                # Build list of paths to try
                paths_to_try = [folder_path, folder_path_backslash]
                if folder_path_relative:
                    paths_to_try.append(folder_path_relative)
                    paths_to_try.append(folder_path_relative.replace("/", "\\"))
                
                current_app.logger.info(f"[THUMBNAIL] Trying paths: {paths_to_try}")
                
                # Try exact match first with all path variants
                placeholders = " OR ".join(["output_folder = ?"] * len(paths_to_try))
                query = f"""
                    SELECT calibration_profile 
                    FROM ProcessLog 
                    WHERE {placeholders}
                    LIMIT 1
                """
                cursor.execute(query, tuple(paths_to_try))
                row = cursor.fetchone()
                
                if row and row["calibration_profile"]:
                    calibration_profile = row["calibration_profile"]
                    current_app.logger.info(f"[THUMBNAIL] Found calibration profile via output_folder: {calibration_profile}")
                else:
                    current_app.logger.info(f"[THUMBNAIL] No calibration profile found for any path variant")
    except Exception as e:
        current_app.logger.warning(f"Failed to get calibration profile: {e}")
        import traceback
        current_app.logger.warning(traceback.format_exc())


    # Load calibration lines if profile exists
    lines_draw_data = {}
    if calibration_profile:
        calib_dir = ensure_calibration_dir()
        profile_path = os.path.join(calib_dir, f"{calibration_profile}.json")
        current_app.logger.info(f"[THUMBNAIL] Looking for calibration file at: {profile_path}")
        
        if os.path.exists(profile_path):
            try:
                with open(profile_path, "r", encoding="utf-8") as fh:
                    calib_data = json.load(fh)
                    
                lines_raw = calib_data.get("lines") or {}
                
                def clean_points(pts):
                    if not pts: return []
                    return [tuple(map(int, p)) for p in pts if isinstance(p, list) and len(p) >= 2]

                lines_draw_data = {
                    "left_white_line": clean_points(lines_raw.get("left_white_line")),
                    "right_white_line": clean_points(lines_raw.get("right_white_line")),
                    "center_line": clean_points(lines_raw.get("center_line")),
                    "left_mid_line": clean_points(lines_raw.get("left_mid_line")),
                    "right_mid_line": clean_points(lines_raw.get("right_mid_line")),
                }
                current_app.logger.info(f"[THUMBNAIL] Loaded {len([v for v in lines_draw_data.values() if v])} line groups from profile")
            except Exception as e:
                current_app.logger.warning(f"Failed to load calibration profile: {e}")
        else:
            current_app.logger.warning(f"[THUMBNAIL] Calibration profile file not found: {profile_path}")


    # Extract Frame (Target 100th frame)
    try:
        current_app.logger.info(f"Extracting frame from: {sample_video_path}")
        cap = cv2.VideoCapture(sample_video_path)
        if not cap.isOpened():
             return jsonify({"error": "Failed to open video"}), 500
             
        # Request 100th frame (index 99)
        target_frame = 99
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames > 0:
            target_frame = min(target_frame, total_frames - 1)
            
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return jsonify({"error": "Failed to read frame"}), 500
            
        # Draw calibration lines on frame if available
        if lines_draw_data:
            # Draw on full-size frame first
            draw_calibration_lines(frame, lines_draw_data)
            current_app.logger.info(f"Drew calibration lines for profile: {calibration_profile}")
            
        # Resize for thumbnail (after drawing so lines scale properly)
        h, w = frame.shape[:2]
        target_w = 320
        scale = target_w / w
        target_h = int(h * scale)
        small_frame = cv2.resize(frame, (target_w, target_h))
        
        # Save to Cache
        try:
            cv2.imwrite(cache_file, small_frame)
        except Exception as e:
            current_app.logger.warning(f"Failed to write cache: {e}")
            
        return send_file(cache_file, mimetype='image/jpeg')

    except Exception as e:
        current_app.logger.error(f"Thumbnail generation failed: {e}")
        return jsonify({"error": str(e)}), 500


@main.route("/api/calibration_check/file_thumbnail", methods=["GET"])
def calibration_check_file_thumbnail_api():
    """個別動画ファイルのサムネイル画像を返す（100フレーム目、リサイズ済み）"""
    video_path = request.args.get("video_path", "")
    
    if not video_path or not os.path.exists(video_path):
        # 1x1 transparent PNG fallback
        fallback = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        return send_file(io.BytesIO(fallback), mimetype='image/png')

    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return jsonify({"error": "動画を開けませんでした"}), 500
        
        # 100フレーム目を取得
        target_frame = 99
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames > 0:
            target_frame = min(target_frame, total_frames - 1)
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return jsonify({"error": "フレーム読み込みに失敗"}), 500
        
        # リサイズ
        h, w = frame.shape[:2]
        target_w = 160
        scale = target_w / w
        target_h = int(h * scale)
        small_frame = cv2.resize(frame, (target_w, target_h))
        
        # JPEG変換
        _, buffer = cv2.imencode('.jpg', small_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return send_file(io.BytesIO(buffer.tobytes()), mimetype='image/jpeg')
        
    except Exception as e:
        current_app.logger.error(f"File thumbnail failed: {e}")
        return jsonify({"error": str(e)}), 500


@main.route("/api/calibration_check/file_preview", methods=["POST"])
def calibration_check_file_preview_api():
    """個別動画ファイルにキャリブレーションラインを描画したプレビュー画像を生成する"""
    payload = request.get_json(silent=True) or {}
    video_path = payload.get("video_path", "")
    profile_name = payload.get("profile", "")
    
    if not video_path:
        return jsonify({"error": "動画パスが指定されていません"}), 400
    
    if not os.path.exists(video_path):
        return jsonify({"error": f"動画ファイルが見つかりません: {video_path}"}), 404
    
    filename = os.path.basename(video_path)
    
    try:
        # 動画フレーム取得
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return jsonify({"error": "動画を開けませんでした"}), 500
        
        # 100フレーム目を取得
        target_frame = 99
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames > 0:
            target_frame = min(target_frame, total_frames - 1)
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return jsonify({"error": "フレーム読み込みに失敗しました"}), 500
        
        # キャリブレーションラインを描画
        lines_draw_data = {}
        if profile_name:
            cal_folder = os.path.join(os.getenv("CALIBRATION_FOLDER", "calibration"))
            profile_path = os.path.join(cal_folder, f"{profile_name}.json")
            
            if os.path.exists(profile_path):
                try:
                    with open(profile_path, "r", encoding="utf-8") as f:
                        profile_data = json.load(f)
                    
                    lines_raw = profile_data.get("lines", {})
                    
                    def clean_points(pts):
                        if not pts:
                            return None
                        return [[int(p["x"]), int(p["y"])] for p in pts if isinstance(p, dict) and "x" in p and "y" in p]
                    
                    lines_draw_data = {
                        "count_line": clean_points(lines_raw.get("count_line")),
                        "left_lane_line": clean_points(lines_raw.get("left_lane_line")),
                        "right_lane_line": clean_points(lines_raw.get("right_lane_line")),
                        "left_mid_line": clean_points(lines_raw.get("left_mid_line")),
                        "right_mid_line": clean_points(lines_raw.get("right_mid_line")),
                    }
                except Exception as e:
                    current_app.logger.warning(f"Failed to load calibration profile: {e}")
        
        # ライン描画
        if lines_draw_data:
            draw_calibration_lines(frame, lines_draw_data)
        
        # リサイズ（適度なサイズに）
        h, w = frame.shape[:2]
        max_w = 800
        if w > max_w:
            scale = max_w / w
            frame = cv2.resize(frame, (max_w, int(h * scale)))
        
        # JPEG変換してbase64エンコード
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        b64_str = base64.b64encode(buffer.tobytes()).decode('utf-8')
        
        return jsonify({
            "image_base64": b64_str,
            "filename": filename,
            "profile": profile_name if profile_name else "未設定",
            "has_lines": bool(lines_draw_data and any(v for v in lines_draw_data.values())),
            "image_width": frame.shape[1],
            "image_height": frame.shape[0]
        })
        
    except Exception as e:
        current_app.logger.exception("File preview generation failed")
        return jsonify({"error": str(e)}), 500



from flask import send_file, send_from_directory



def send_file_from_directory(directory, filename):

    # Secure way to send file

    return send_from_directory(directory, filename)





import numpy as np



@main.route("/api/calibration_check/update_folder", methods=["POST"])
def apply_calibration():
    """フォルダに対してキャリブレーションプロファイルを適用（または解除）するAPI"""
    data = request.json
    folder_path = data.get("folder_path")
    profile_name = data.get("profile")

    if not folder_path:
        return jsonify({"error": "Folder path is required"}), 400

    # ... (existing profile saving logic) ...
    # Instead of full re-implementation, let's just insert the cache logic
    # But for robustness, I will re-implement the critical part or append cache logic
    
    # Existing logic saves to JSON in folder.
    # We just need to ADD the cache saving here if it doesn't exist?
    # User said: "Save when calibration is granted" -> "DBwo reference... take 100f as photo"
    # This implies we should ensure the cache exists now.
    
    # Let's delegate to the thumbnail generator or run it here.
    # Running it here ensures it's ready.
    
    try:
        # Save profile log etc (existing)
        meta_path = os.path.join(folder_path, "calibration_metadata.json")
        meta = {}
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        
        meta["calibration_profile"] = profile_name
        meta["updated_at"] = cv2.getTickCount() # Placeholder timestamp
        
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=4)
            

            

        # Update Cache (Force Create if missing)
        cache_dir = os.path.join(os.getcwd(), "cache", "img")
        os.makedirs(cache_dir, exist_ok=True)
        # Normalize to forward slashes for hashing consistency
        norm_path = folder_path.replace("\\", "/")
        path_hash = hashlib.md5(norm_path.encode('utf-8')).hexdigest()
        cache_file = os.path.join(cache_dir, f"{path_hash}.jpg")

        

        if not os.path.exists(cache_file):

            # Extract 100th frame logic

            try:

                # 1. Find video source (Simplified logic here or reuse helper)

                sample_video_path = None

                with sqlite3.connect(MAIN_DB_PATH) as conn:

                    conn.row_factory = sqlite3.Row

                    cursor = conn.cursor()

                    cursor.execute("""

                        SELECT v.source_path

                        FROM ProcessLog p

                        JOIN Video v ON p.video_id = v.video_id

                        WHERE p.output_folder = ? 

                        LIMIT 1

                    """, (folder_path,))

                    row = cursor.fetchone()

                    if row and row["source_path"] and os.path.exists(row["source_path"]):

                         sample_video_path = row["source_path"]



                if not sample_video_path:

                     # Check folder directly

                     for f in os.listdir(folder_path):

                         if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):

                             sample_video_path = os.path.join(folder_path, f)

                             break

                             

                if sample_video_path:

                    cap = cv2.VideoCapture(sample_video_path)

                    if cap.isOpened():

                        # Target 100th frame (index 99)

                        target_frame = 99

                        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

                        if total_frames > 0:

                            target_frame = min(target_frame, total_frames - 1)

                            

                        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

                        ret, frame = cap.read()

                        cap.release()

                        

                        if ret:

                            # Resize

                            h, w = frame.shape[:2]

                            target_w = 320

                            scale = target_w / w

                            target_h = int(h * scale)

                            small_frame = cv2.resize(frame, (target_w, target_h))

                            cv2.imwrite(cache_file, small_frame)

                            current_app.logger.info(f"Cached thumbnail for {folder_path} at {cache_file}")

            except Exception as e:

                current_app.logger.warning(f"Failed to generate cache on apply: {e}")



    except Exception as e:

        current_app.logger.error(f"Failed to apply: {e}")

        return jsonify({"error": str(e)}), 500



    return jsonify({"success": True, "message": f"Applied {profile_name}"})



@main.route("/api/calibration_check/verify", methods=["POST"])

def calibration_check_verify_api():

    """指定フォルダのサンプル動画を取得し、キャリブレーションラインを焼き込んだ画像を返却する。"""

    payload = request.get_json(silent=True) or {}

    folder_path = payload.get("folder_path")

    profile_name = payload.get("profile")



    if not folder_path or not os.path.isdir(folder_path):

        return jsonify({"error": "有効なフォルダパスが指定されていません。"}), 400

    if not profile_name:

        # Try to load profile from folder settings JSON

        settings = load_folder_settings(folder_path)

        profile_name = settings.get("profile", "")

        # If still no profile, we proceed to show raw image (no error)



    # Remove quotes if user copied as path

    folder_path = folder_path.strip('"').strip("'")

    

    # --- Cache Check ---

    # Cache file naming: check_img_{profile}.jpg

    # Use specific name for raw image if no profile

    safe_profile_name = profile_name if profile_name else "raw_no_profile"

    cache_filename = f"check_img_{safe_profile_name}.jpg"

    cache_path = os.path.join(folder_path, cache_filename)

    

    if os.path.exists(cache_path):

        try:

            with open(cache_path, "rb") as f:

                img_data = f.read()

            b64_str = base64.b64encode(img_data).decode('utf-8')

            

            # Read image dimension just for returning matching metadata if needed

            img = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)

            h, w = img.shape[:2] if img is not None else (0, 0)



            return jsonify({

                "image_base64": b64_str,

                "image_width": w,

                "image_height": h,

                "video_filename": "cached_image",

                "is_baked": bool(profile_name),

                "lines": {} 
            })
        except Exception as e:
            current_app.logger.warning(f"Failed to read cache: {e}")
            # Fallback to generate new one
            pass

    # --- Generate New ---
    
    # 1. Get video source_path
    sample_video_path = None
    
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT v.source_path
                FROM ProcessLog p
                JOIN Video v ON p.video_id = v.video_id
                WHERE p.output_folder = ? OR p.output_folder LIKE ?
                LIMIT 1
            """, (folder_path, f"%{folder_path}"))
            row = cursor.fetchone()
            if row and row["source_path"] and os.path.exists(row["source_path"]):
                sample_video_path = row["source_path"]
    except Exception:
        pass

    # Fallback: search for video in output folder
    if not sample_video_path:
        video_exts = {".mp4", ".avi", ".mov", ".mkv"}
        try:
            files = os.listdir(folder_path)
            files.sort()
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in video_exts:
                    sample_video_path = os.path.join(folder_path, f)
                    break 
        except OSError:
            pass
            
    # Try finding source video via folder_utils (Robust Fallback)
    if not sample_video_path:
         try:
             found_path = find_source_video_path(folder_path)
             if found_path and os.path.exists(found_path):
                 sample_video_path = found_path
                 current_app.logger.info(f"Resolved source path via folder_utils: {sample_video_path}")
         except Exception as e:
             current_app.logger.warning(f"find_source_video_path failed: {e}")
         
    if not sample_video_path:
        return jsonify({"error": "フォルダ内に検証用動画ファイルが見つかりませんでした。"}), 404

    # 2. Load Calibration Profile (If exists)
    lines_draw_data = {}
    
    if profile_name:
        calib_dir = ensure_calibration_dir()
        profile_path = os.path.join(calib_dir, f"{profile_name}.json")
        
        if os.path.exists(profile_path):
            try:

                with open(profile_path, "r", encoding="utf-8") as fh:

                    calib_data = json.load(fh)

                    

                lines_raw = calib_data.get("lines") or {}

                

                def clean_points(pts):

                    if not pts: return []

                    return [tuple(map(int, p)) for p in pts if isinstance(p, list) and len(p) >= 2]



                lines_draw_data = {

                    "left_white_line": clean_points(lines_raw.get("left_white_line")),

                    "right_white_line": clean_points(lines_raw.get("right_white_line")),

                    "center_line": clean_points(lines_raw.get("center_line")),

                    "left_mid_line": clean_points(lines_raw.get("left_mid_line")),

                    "right_mid_line": clean_points(lines_raw.get("right_mid_line")),

                }

            except Exception:

                pass # Fail silently or just ignore profile if broken

        else:

             # If profile specified but missing, we treat it as no profile effectively for display, 

             # but maybe warn user? For now just show raw.

             pass



    # 4. Get Sample Frame

    try:

        # Simple frame load

        cap = cv2.VideoCapture(sample_video_path)

        if not cap.isOpened():

             raise ValueError("Video open failed")

        

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        target_frame = min(30, total_frames // 2) if total_frames > 0 else 0

        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

        ret, frame = cap.read()

        cap.release()

        

        if not ret or frame is None:

            raise ValueError("Frame load failed")



        # 5. Draw Lines (Baking) - Only if we have data

        if lines_draw_data:

            draw_calibration_lines(frame, lines_draw_data)

        

        # 6. Save to Cache

        try:

            cv2.imwrite(cache_path, frame)

        except Exception as e:

            current_app.logger.warning(f"Failed to write cache: {e}")



        # 7. Encode

        ret, buffer = cv2.imencode('.jpg', frame)

        b64_str = base64.b64encode(buffer).decode('utf-8')

        

        return jsonify({

            "image_base64": b64_str,

            "image_width": frame.shape[1],

            "image_height": frame.shape[0],

            "video_filename": os.path.basename(sample_video_path),

            "is_baked": bool(lines_draw_data),

            "lines": {} 

        })



    except Exception as e:

        current_app.logger.exception("Verification frame generation failed")

        return jsonify({"error": f"検証画像の生成に失敗しました: {e}"}), 500



def draw_calibration_lines(img, lines):

    """画像にキャリブレーションラインを描画する (OpenCV)"""

    # Colors (BGR)

    COLOR_CYAN = (255, 255, 0)

    COLOR_YELLOW = (0, 255, 255)

    COLOR_ORANGE = (0, 165, 255) # Orange-ish BGR

    

    thickness = 2

    

    # Helper for polylines

    def draw(pts, color, thick=2):

        if pts and len(pts) >= 2:

            cv2.polylines(img, [np.array(pts, dtype=np.int32)], isClosed=False, color=color, thickness=thick)


    # Draw each line safely (check if key exists and has data)
    draw(lines.get("left_white_line", []), COLOR_CYAN, 3)

    draw(lines.get("right_white_line", []), COLOR_CYAN, 3)

    draw(lines.get("center_line", []), COLOR_YELLOW, 2)

    

    # Dashed lines (simulated with standard lines for now as cv2 has no simple dashed line)

    # Or keep them solid with distinct color for visibility

    draw(lines.get("left_mid_line", []), COLOR_ORANGE, 2)

    draw(lines.get("right_mid_line", []), COLOR_ORANGE, 2)










@main.route("/calibration/delete_profile", methods=["POST"])

def delete_profile():

    """キャリブレーションプロファイルを削除する"""

    profile_name = request.form.get("profile_name")

    

    if not profile_name:

        flash("削除するプロファイル名が指定されていません。", "warning")

        return redirect(url_for("main.post_process"))

        

    try:

        # 1. Delete file

        calib_dir = ensure_calibration_dir()

        file_path = os.path.join(calib_dir, f"{profile_name}.json")

        if os.path.exists(file_path):

            os.remove(file_path)

            

        # 2. Clear references in DB

        if os.path.exists(MAIN_DB_PATH):

            with sqlite3.connect(MAIN_DB_PATH) as conn:

                conn.execute(

                    "UPDATE ProcessLog SET calibration_profile = NULL WHERE calibration_profile = ?", 

                    (profile_name,)

                )

                conn.commit()

                

        flash(f"プロファイル '{profile_name}' を削除しました。", "info")

    except Exception as e:
        current_app.logger.exception("Failed to delete profile")
        flash(f"プロファイルの削除に失敗しました: {e}", "danger")
        
    return redirect(url_for("main.post_process"))

# --- Subfolder Profile Management API ---

@main.route("/api/calibration_check/folder_runs/<path:folder_alias>")
def calibration_check_folder_runs_api(folder_alias):
    """指定フォルダ（エイリアス）内のRunとサブフォルダ構造を返すAPI"""
    try:
        from ..modules.db_manager_helpers import get_folder_details_for_ui
        data = get_folder_details_for_ui(folder_alias)
        return jsonify(data)
    except Exception as e:
        current_app.logger.exception(f"Failed to fetch folder runs for {folder_alias}")
        return jsonify({"status": "error", "message": str(e)}), 500


@main.route("/api/calibration_check/apply_scope_profile", methods=["POST"])
def calibration_check_apply_scope_profile_api():
    """サブフォルダ単位でのプロファイル適用API"""
    try:
        data = request.json
        
        # Single scope update (legacy/simple mode)
        if "scope" in data:
            items = [{
                "scope": data["scope"],
                "profile": data.get("profile"),
                "display": data.get("scope")  # fallback
            }]
        # Bulk scope update
        elif "scope_profiles" in data:
             items = data["scope_profiles"]
        else:
            return jsonify({"status": "error", "message": "No scope specified"}), 400

        from ..modules.db_manager_helpers import apply_calibration_scope_bulk
        result = apply_calibration_scope_bulk(items)
        
        # Invalidate cache for affected folders
        _invalidate_thumbnail_cache_for_scopes(items)
        
        return jsonify({
            "status": "ok",
            "updated_scopes": result["updated_scopes"],
            "unmatched_scopes": result["unmatched_scopes"]
        })
        
    except Exception as e:
        current_app.logger.exception("Failed to apply scope profile")
        return jsonify({"status": "error", "message": str(e)}), 500


@main.route("/api/calibration_check/apply_run_profiles", methods=["POST"])
def calibration_check_apply_run_profiles_api():
    """選択されたRun IDへのプロファイル一括適用API"""
    try:
        payload = request.json
        run_ids = payload.get("run_ids", [])
        profile = payload.get("profile")
        collection_year = payload.get("collection_year")
        road_type = payload.get("road_type")
        
        if not run_ids:
             return jsonify({"status": "error", "message": "No run_ids provided"}), 400
             
        # Apply calibration profile
        count = 0
        if profile:
            from ..modules.db_manager_helpers import apply_calibration_profile_to_runs
            count = apply_calibration_profile_to_runs(run_ids, profile)
        
        # Update collection_year and road_type if provided
        if collection_year is not None or road_type is not None:
            try:
                with sqlite3.connect(MAIN_DB_PATH) as conn:
                    cursor = conn.cursor()
                    
                    # Get video_ids for these run_ids
                    placeholders = ",".join("?" for _ in run_ids)
                    cursor.execute(f"""
                        SELECT DISTINCT video_id
                        FROM ProcessLog
                        WHERE run_id IN ({placeholders})
                    """, run_ids)
                    
                    video_ids = [row[0] for row in cursor.fetchall()]
                    
                    if video_ids:
                        updates = []
                        params = []
                        
                        if collection_year is not None:
                            updates.append("collection_year = ?")
                            params.append(collection_year)
                        
                        if road_type is not None:
                            updates.append("road_type = ?")
                            params.append(road_type)
                        
                        if updates:
                            vid_placeholders = ",".join("?" for _ in video_ids)
                            sql = f"UPDATE Video SET {', '.join(updates)} WHERE video_id IN ({vid_placeholders})"
                            params.extend(video_ids)
                            cursor.execute(sql, params)
                            conn.commit()
                            count = max(count, len(video_ids))
            except Exception as e:
                current_app.logger.warning(f"Failed to update year/type: {e}")
        
        # Invalidate cache for affected run folders
        _invalidate_thumbnail_cache_for_runs(run_ids)
        
        return jsonify({
            "status": "ok",
            "updated_run_ids": run_ids,
            "count": count,
            "applied_profile": profile
        })
    except Exception as e:
        current_app.logger.exception("Failed to apply run profiles")
        return jsonify({"status": "error", "message": str(e)}), 500


def _invalidate_thumbnail_cache_for_scopes(items):
    """サブフォルダスコープのサムネイルキャッシュを無効化"""
    try:
        cache_dir = os.path.join(os.getcwd(), "cache", "img")
        if not os.path.exists(cache_dir):
            return
            
        for item in items:
            scope = item.get("scope", "")
            if not scope:
                continue
                
            # Get all folders matching this scope
            with sqlite3.connect(MAIN_DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # scope can be a folder path or alias
                cursor.execute("""
                    SELECT DISTINCT output_folder, calibration_profile
                    FROM ProcessLog
                    WHERE output_folder LIKE ? OR folder_alias LIKE ?
                """, (f"%{scope}%", f"%{scope}%"))
                
                for row in cursor.fetchall():
                    folder_path = row["output_folder"]
                    profile = row["calibration_profile"]
                    
                    # Delete old cache
                    norm_path = folder_path.replace("\\", "/")
                    cache_key = f"{norm_path}|{profile or 'no_profile'}"
                    path_hash = hashlib.md5(cache_key.encode('utf-8')).hexdigest()
                    cache_file = os.path.join(cache_dir, f"{path_hash}.jpg")
                    
                    if os.path.exists(cache_file):
                        os.remove(cache_file)
                        current_app.logger.info(f"Invalidated cache for {folder_path}")
    except Exception as e:
        current_app.logger.warning(f"Failed to invalidate cache: {e}")


def _invalidate_thumbnail_cache_for_runs(run_ids):
    """Run IDsのサムネイルキャッシュを無効化"""
    try:
        cache_dir = os.path.join(os.getcwd(), "cache", "img")
        if not os.path.exists(cache_dir):
            return
            
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            placeholders = ",".join("?" for _ in run_ids)
            cursor.execute(f"""
                SELECT DISTINCT output_folder, calibration_profile
                FROM ProcessLog
                WHERE run_id IN ({placeholders})
            """, run_ids)
            
            for row in cursor.fetchall():
                folder_path = row["output_folder"]
                profile = row["calibration_profile"]
                
                # Delete old cache
                norm_path = folder_path.replace("\\", "/")
                cache_key = f"{norm_path}|{profile or 'no_profile'}"
                path_hash = hashlib.md5(cache_key.encode('utf-8')).hexdigest()
                cache_file = os.path.join(cache_dir, f"{path_hash}.jpg")
                
                if os.path.exists(cache_file):
                    os.remove(cache_file)
                    current_app.logger.info(f"Invalidated cache for run folder {folder_path}")
    except Exception as e:
        current_app.logger.warning(f"Failed to invalidate cache: {e}")


# --- Calibration Editor API ---

def _get_video_path_calib(run_id, path_hint=None):
    if path_hint: return path_hint
    if not run_id: return None
    path = None
    if os.path.exists(MAIN_DB_PATH):
        try:
            with sqlite3.connect(MAIN_DB_PATH) as conn:
                cursor = conn.cursor()
                # ProcessLog経由でvideo_idを取得し、Videoのsource_pathを取得
                cursor.execute("""
                    SELECT v.source_path 
                    FROM Video v 
                    JOIN ProcessLog p ON v.video_id = p.video_id 
                    WHERE p.run_id = ?
                """, (run_id,))
                row = cursor.fetchone()
                if row: path = row[0]
        except: pass
    return path

@main.route("/api/calibration/<int:run_id>/metadata")
def calibration_metadata(run_id):
    path_hint = request.args.get("path_hint")
    path = _get_video_path_calib(run_id, path_hint)
    
    if not path or not os.path.exists(path):
        current_app.logger.warning(f"Video not found for run {run_id}, path {path}")
        return jsonify({"error": "Video not found"}), 404
        
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return jsonify({"error": "Cannot open video"}), 500
        
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    
    return jsonify({
        "width": width, 
        "height": height, 
        "total_frames": count
    })

@main.route("/api/calibration/<int:run_id>/frame")
def calibration_frame(run_id):
    path_hint = request.args.get("path_hint")
    frame_idx = request.args.get("frame", 0, type=int)
    path = _get_video_path_calib(run_id, path_hint)
    
    if not path or not os.path.exists(path):
        return "Video/File not found", 404
        
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        return "Frame not found", 404
        
    ret, buf = cv2.imencode(".jpg", frame)
    return send_file(io.BytesIO(buf), mimetype="image/jpeg")

@main.route("/api/calibration/<int:run_id>/data")
def calibration_data(run_id):
    profile = request.args.get("profile")
    if profile:
        fpath = os.path.join(ensure_calibration_dir(), f"{profile}.json")
        if os.path.exists(fpath):
            try:
                with open(fpath, encoding='utf-8') as f:
                    return jsonify(json.load(f))
            except: pass
    return jsonify({})

@main.route("/api/calibration/<int:run_id>/save", methods=["POST"])
def calibration_save(run_id):
    data = request.json
    profile_name = data.get("profile_name")
    if not profile_name: return jsonify({"error": "No name"}), 400
    
    path = os.path.join(ensure_calibration_dir(), f"{profile_name}.json")
    try:
        with open(path, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        
    return jsonify({"status": "ok", "profile_name": profile_name})

@main.route("/api/calibration/<int:run_id>/lane_test")
def calibration_lane_test(run_id):
    return jsonify([])
