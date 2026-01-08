import sqlite3
import os
from typing import Any
from .db_manager import MAIN_DB_PATH

def _canonicalize_folder_alias(alias: str, filename: str) -> str:
    """簡易正規化: aliasが空ならファイル名の親フォルダを使うなど"""
    if alias:
        return alias.replace("\\", "/").strip("/")
    # aliasがない場合、filenameから抽出 (簡易)
    if not filename:
        return ""
    dirname = os.path.dirname(filename)
    return dirname.replace("\\", "/").strip("/")




def get_folder_details_for_ui(folder_alias: str) -> dict[str, Any]:
    """UI用のフォルダ詳細（サブフォルダ構造とRun一覧）を取得する。"""
    
    # 1. 対象のRunを取得
    target_runs = []
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # folder_alias に一致するものを検索 (folder_alias カラム OR output_folder の一部)
        # 厳密には list_folder_batches と同じロジックが望ましいが、簡易的に folder_alias カラムを見る
        # ※ list_folder_batches は _canonicalize_folder_alias を通しているため、ここでも合わせる必要がある
        
        # まずは全件取得してPython側でフィルタリング（件数が数万でなければ許容範囲）
        # 効率化するならSQLで絞り込むべきだが、canonicalizeロジックがPythonにあるため
        rows = c.execute("""
            SELECT 
                p.run_id, 
                v.filename, 
                p.folder_alias, 
                p.output_folder, 
                p.calibration_profile, 
                p.process_start,
                v.road_type, 
                v.collection_year
            FROM ProcessLog p
            LEFT JOIN Video v ON p.video_id = v.video_id
            ORDER BY p.run_id
        """).fetchall()
        

        
        ids_in_folder = []
        for row in rows:
            r_alias = (row["folder_alias"] or "").strip()
            r_filename = (row["filename"] or "").strip()
            # 正規化
            canonical = _canonicalize_folder_alias(r_alias, r_filename) or r_alias
            
            # マッチ判定: 完全一致 または スラッシュ区切りの親
            # folder_alias="new_x" の場合、 "new_x" や "new_x/sub" が対象
            if canonical == folder_alias:
                # 完全に一致＝このフォルダ直下（とみなす）
                ids_in_folder.append(row)
            elif canonical.startswith(folder_alias + "/"):
                # サブフォルダ
                ids_in_folder.append(row)

    # 2. 構造化
    # Runsリスト (フラット)
    runs_list = []
    
    # Subfolders (スコープ) 集計
    # Key: scope (relative path from folder_alias)
    scope_map = {}
    
    for row in ids_in_folder:
        run_id = row["run_id"]
        # 相対パス計算
        r_alias = (row["folder_alias"] or "").strip()
        canonical = _canonicalize_folder_alias(r_alias, row["filename"]) or r_alias
        
        rel_path = ""
        if canonical.startswith(folder_alias + "/"):
            rel_path = canonical[len(folder_alias)+1:]
        
        # Run Entry
        runs_list.append({
            "run_id": run_id,
            "filename": row["filename"],
            "relative_path": row["output_folder"] or row["filename"], # 表示用
            "profile": row["calibration_profile"],
            "folder_alias": canonical
        })
        
        # Scope Aggregation
        # scope は "subA", "subA/subB" など
        # 今回は「直下のサブフォルダ」単位でまとめるか、「登録されているエイリアス（＝最下層）」単位でまとめるか？
        # UIの要件: "サブフォルダ別プロファイル設定"
        # ユーザーは "new_x/2_250727" の用な粒度で見たいはず。
        # つまり canonical (full alias) そのものをキーにするのが自然。
        # ただし folder_alias 自体は除外（ルートなので）
        
        scope_key = canonical
        if scope_key == folder_alias:
            scope_key = "(root)" # 特別扱い
            
        entry = scope_map.get(scope_key)
        if not entry:
            entry = {
                "scope": canonical, # DB保存に使う値
                "display_label": rel_path if rel_path else "(ルート直下)",
                "path_label": rel_path,
                "run_count": 0,
                "profiles": set(),
                "road_types": set(),
                "collection_years": set(),
                "example_run_id": run_id, # プレビュー用
                "example_video": row["filename"] # ヒント用
            }
            scope_map[scope_key] = entry
            
        entry["run_count"] += 1
        if row["calibration_profile"]:
            entry["profiles"].add(row["calibration_profile"])
        if row["road_type"]:
            entry["road_types"].add(row["road_type"])
        if row["collection_year"]:
            entry["collection_years"].add(row["collection_year"])
            
    # 3. リスト化と整形
    subfolders = []
    for key, data in scope_map.items():
        # Profiles
        prof_list = sorted(list(data["profiles"]))
        # Road Types
        rt_list = sorted(list(data["road_types"]))
        mixed_rt = len(rt_list) > 1
        primary_rt = rt_list[0] if len(rt_list) == 1 else None
        
        # Years
        yr_list = sorted(list(data["collection_years"]))
        mixed_yr = len(yr_list) > 1
        primary_yr = yr_list[0] if len(yr_list) == 1 else None
        
        subfolders.append({
            "scope": data["scope"],
            "display_label": data["display_label"],
            "path_label": data["path_label"],
            "run_count": data["run_count"],
            "profiles": prof_list,
            "has_profile": len(prof_list) > 0,
            "road_type": primary_rt,
            "road_types_mixed": mixed_rt,
            "collection_year": primary_yr,
            "collection_years_mixed": mixed_yr,
            "example_run_id": data["example_run_id"],
            "example_video": data["example_video"]
        })
        
    # ソート
    subfolders.sort(key=lambda x: x["scope"])
    
    # 4. Profile Metadata (for UI badges)
    opt_folder = os.getenv("Opt_files", "output")
    calib_dir = os.path.join(opt_folder, "calibrations")
    from .profile_meta import load_profile_metadata
    profile_meta = load_profile_metadata(calib_dir)

    return {
        "folder_alias": folder_alias,
        "runs": runs_list,
        "subfolders": subfolders,
        "profile_metadata": profile_meta
    }

def apply_calibration_profile_to_runs(run_ids: list[int], profile_name: str) -> int:
    """指定したRun IDリストにプロファイルを一括適用する。更新件数を返す。"""
    if not run_ids:
        return 0
        
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        c = conn.cursor()
        # profile_name が空文字 or __CLEAR__ なら NULL にする
        val = None if not profile_name or profile_name == "__CLEAR__" else profile_name
        
        # IN句の構築
        placeholders = ",".join(["?"] * len(run_ids))
        sql = f"UPDATE ProcessLog SET calibration_profile = ? WHERE run_id IN ({placeholders})"
        params = [val] + run_ids
        
        c.execute(sql, params)
        conn.commit()
        return c.rowcount

def apply_calibration_scope_bulk(items: list[dict]) -> dict:
    """
    複数のスコープに対する変更を一括適用する。
    items: [{ "scope": "alias", "profile": "pname" }, ...]
    """
    updated_scopes = []
    unmatched_scopes = []
    
    # 実際の実装: スコープごとに該当するRun IDを特定して update する
    # 効率化のため、まず全Runの alias マッピングを取得してもよいが、ここではループで処理する
    
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        c = conn.cursor()
        
        for item in items:
            scope = item.get("scope")
            profile = item.get("profile")
            display = item.get("display")
            
            if not scope:
                continue
                
            val = None if not profile or profile == "__CLEAR__" else profile
            
            # folder_alias が scope と一致するRunを更新
            # ※ 本来は正規化ロジックが必要だが、scopeは正規化済みの値をJSから受け取ると仮定
            c.execute("UPDATE ProcessLog SET calibration_profile = ? WHERE folder_alias = ?", (val, scope))
            
            if c.rowcount > 0:
                updated_scopes.append({
                    "scope": scope,
                    "applied_profile": profile,
                    "run_count": c.rowcount,
                    "display": display
                })
            else:
                unmatched_scopes.append(scope)
                
        conn.commit()
        
    return {
        "updated_scopes": updated_scopes,
        "unmatched_scopes": unmatched_scopes
    }

def update_profile_by_folder_path(folder_path: str, profile_name: str) -> int:
    """指定されたフォルダパス（output_folder）を持つRunのプロファイルを更新する。"""
    if not folder_path:
        return 0
        
    val = None if not profile_name or profile_name == "__CLEAR__" else profile_name
    
    # Normalize input path for robust matching
    norm_input = folder_path.replace("\\", "/").rstrip("/").lower()
    
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        c = conn.cursor()
        
        # Robust Update: Match lowercase normalized path
        # SQLite doesn't have a native normalize function, so we do it in SQL
        c.execute("""
            UPDATE ProcessLog 
            SET calibration_profile = ? 
            WHERE 
                LOWER(REPLACE(output_folder, '\\', '/')) = ? 
                OR 
                LOWER(REPLACE(output_folder, '\\', '/')) = ?
        """, (val, norm_input, norm_input + "/")) # match folder exactly or folder/ (trailing slash) context
        
        count = c.rowcount
        conn.commit()
        return count



_SENTINEL = object()

def update_video_metadata(run_ids: list[int], road_type: Any = _SENTINEL, collection_year: Any = _SENTINEL) -> int:
    """Update road_type and collection_year for specified run_ids."""
    if not run_ids:
        return 0

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        c = conn.cursor()
        
        updates = []
        params = []
        
        if road_type is not _SENTINEL:
            updates.append("road_type = ?")
            # If empty string, treat as NULL
            params.append(road_type if road_type else None)
            
        if collection_year is not _SENTINEL:
            updates.append("collection_year = ?")
            params.append(collection_year)
            
        if not updates:
            return 0
            
        # Get video_ids from ProcessLog for these run_ids
        placeholders = ",".join(["?"] * len(run_ids))
        
        sql = f"""
            UPDATE Video 
            SET {', '.join(updates)} 
            WHERE video_id IN (
                SELECT video_id FROM ProcessLog WHERE run_id IN ({placeholders})
            )
        """
        params.extend(run_ids)
        
        c.execute(sql, params)
        conn.commit()
        return c.rowcount
