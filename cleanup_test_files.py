"""
使っていないテストプログラムと一時ファイルを削除するスクリプト
"""

import os
import shutil
from pathlib import Path

# プロジェクトルート
PROJECT_ROOT = Path(r"c:\Users\kurok\Downloads\G_ADC\ADC_08")

# 削除対象ファイル
FILES_TO_DELETE = [
    # デバッグファイル（ルート）
    "debug_api_struct.py",
    "debug_calibration_data.py",
    "debug_columns.py",
    "debug_db_paths.py",
    "debug_env.py",
    "debug_find_video.py",
    "debug_hash.py",
    "debug_master.py",
    "debug_run_info.py",
    "debug_schema.py",
    "debug_verify_logic.py",
    "debug_video_columns.py",
    "debug_video_search.py",
    "run_server_debug.py",
    
    # テストファイル（ルート）
    "temp_test.py",
    "test_line_drawing.py",
    "test_server_error.py",
    "test_thumbnail_api.py",
    "thumbnail_logic.py",
    
    # 検証ファイル（ルート）
    "verify_calibration.py",
    "verify_fix.py",
    "verify_fix_simple.py",
    "verify_image_annotation.py",
    "verify_manual_export.py",
    "verify_outlier_filtering.py",
    
    # チェックファイル（ルート）
    "check_db_paths.py",
    "check_db_schema.py",
    "check_db_structure.py",
    "check_syntax.py",
    
    # 一時ファイル・追加機能（ルート）
    "add_function.py",
    "add_function_safe.py",
    "add_get_run_video_info.py",
    "append_db_functions.py",
    "cleanup_manual_view.py",
    "insert_db_functions.py",
    "inspect_db.py",
    "find_syntax_error.py",
    "fix_null_bytes.py",
    "truncate_file.py",
    "update_video_metadata_function.py",
    "read_log.py",
    
    # ログ・出力ファイル（ルート）
    "app_debug.log",
    "db_inspection.txt",
    "db_paths_output.txt",
    "db_structure.json",
    "debug_output.txt",
    "debug_output_2.txt",
    "debug_start.log",
    "debug_verify.log",
    "detailed_error.log",
    "detailed_error_v2.log",
    "error_final.txt",
    "error_log.txt",
    "error_log_v2.txt",
    "full_output.txt",
    "paths.log",
    "server_debug_output.txt",
    "verify_result.txt",
    "verbose_import.log",
    "cols.txt",
    "tables.txt",
    "models.txt",
    
    # 一時JavaScript/JSONファイル
    "debug_chunk.js",
    "temp_check.js",
    
    # テスト出力ファイル
    "test_thumbnail.jpg",
    "test_comparative_report.xlsx",
    "test_comparative_report_v2.xlsx",
    "テスト＿卒論.xlsx",
    "テスト＿卒論_filled.xlsx",
    
    # Source_code内検証ファイル
    "Source_code/verify_calibration_check.py",
    "Source_code/verify_subfolder_api.py",
    "Source_code/verify_traffic_count.py",
    
    # Source_code内チェックファイル
    "Source_code/check_classes.py",
    "Source_code/check_db_manager_vars.py",
    "Source_code/check_schema.py",
    
    # Source_code内デバッグファイル
    "Source_code/debug_report_logic.py",
    
    # scripts内デバッグファイル
    "scripts/debug_import.py",
    "scripts/debug_imports.py",
    "scripts/debug_imports_full.py",
    
    # scripts内チェックファイル
    "scripts/check_all_databases.py",
    "scripts/check_data_structure.py",
    "scripts/check_db_structure.py",
    "scripts/check_schema.py",
    "scripts/check_vacuum.py",
    "scripts/check_video_schema.py",
    
    # scripts内テストファイル
    "scripts/test_calibration_tool.py",
    "scripts/test_inference_import.py",
    "scripts/test_manual_metrics_isolation.py",
    "scripts/test_migration.py",
]


def cleanup_files():
    """ファイルを削除"""
    print("=" * 80)
    print("使っていないテストプログラムと一時ファイルを削除します")
    print("=" * 80)
    print()
    
    deleted_count = 0
    not_found_count = 0
    total_size = 0
    
    for file_path in FILES_TO_DELETE:
        full_path = PROJECT_ROOT / file_path
        
        if full_path.exists():
            try:
                size = full_path.stat().st_size
                full_path.unlink()
                deleted_count += 1
                total_size += size
                print(f"✓ 削除: {file_path}")
            except Exception as e:
                print(f"✗ エラー: {file_path} - {e}")
        else:
            not_found_count += 1
            # print(f"- スキップ: {file_path} (存在しません)")
    
    print()
    print("=" * 80)
    print(f"削除完了: {deleted_count}個のファイル ({total_size / 1024 / 1024:.2f} MB)")
    if not_found_count > 0:
        print(f"見つからなかったファイル: {not_found_count}個")
    print("=" * 80)


if __name__ == "__main__":
    cleanup_files()
