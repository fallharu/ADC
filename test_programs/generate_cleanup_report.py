"""
使っていないテストプログラムと一時ファイルの整理レポート生成
"""

import os
from pathlib import Path

# プロジェクトルート
PROJECT_ROOT = Path(r"c:\Users\kurok\Downloads\G_ADC\ADC_08")

# 削除候補ファイルのカテゴリ別リスト
CLEANUP_CANDIDATES = {
    "デバッグファイル（ルート）": [
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
    ],
    
    "テストファイル（ルート）": [
        "temp_test.py",
        "test_line_drawing.py",
        "test_server_error.py",
        "test_thumbnail_api.py",
        "thumbnail_logic.py",
    ],
    
    "検証ファイル（ルート）": [
        "verify_calibration.py",
        "verify_fix.py",
        "verify_fix_simple.py",
        "verify_image_annotation.py",
        "verify_manual_export.py",
        "verify_outlier_filtering.py",
    ],
    
    "チェックファイル（ルート）": [
        "check_db_paths.py",
        "check_db_schema.py",
        "check_db_structure.py",
        "check_syntax.py",
    ],
    
    "一時ファイル・追加機能（ルート）": [
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
    ],
    
    "ログ・出力ファイル（ルート）": [
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
    ],
    
    "一時JavaScript/JSONファイル": [
        "debug_chunk.js",
        "temp_check.js",
    ],
    
    "テスト出力ファイル": [
        "test_thumbnail.jpg",
        "test_comparative_report.xlsx",
        "test_comparative_report_v2.xlsx",
        "テスト＿卒論.xlsx",
        "テスト＿卒論_filled.xlsx",
    ],
    
    "Source_code内検証ファイル": [
        "Source_code/verify_calibration_check.py",
        "Source_code/verify_subfolder_api.py",
        "Source_code/verify_traffic_count.py",
    ],
    
    "Source_code内チェックファイル": [
        "Source_code/check_classes.py",
        "Source_code/check_db_manager_vars.py",
        "Source_code/check_schema.py",
    ],
    
    "Source_code内デバッグファイル": [
        "Source_code/debug_report_logic.py",
    ],
    
    "scripts内デバッグファイル": [
        "scripts/debug_import.py",
        "scripts/debug_imports.py",
        "scripts/debug_imports_full.py",
    ],
    
    "scripts内チェックファイル": [
        "scripts/check_all_databases.py",
        "scripts/check_data_structure.py",
        "scripts/check_db_structure.py",
        "scripts/check_schema.py",
        "scripts/check_vacuum.py",
        "scripts/check_video_schema.py",
    ],
    
    "scripts内テストファイル": [
        "scripts/test_calibration_tool.py",
        "scripts/test_inference_import.py",
        "scripts/test_manual_metrics_isolation.py",
        "scripts/test_migration.py",
    ],
}


def generate_report():
    """削除候補ファイルのレポートを生成"""
    output_file = PROJECT_ROOT / "cleanup_summary.txt"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("使っていないテストプログラムと一時ファイルの整理\n")
        f.write("=" * 80 + "\n\n")
        
        total_files = 0
        total_size = 0
        
        for category, files in CLEANUP_CANDIDATES.items():
            f.write(f"\n【{category}】({len(files)}個)\n")
            f.write("-" * 80 + "\n")
            
            category_size = 0
            for file_path in files:
                full_path = PROJECT_ROOT / file_path
                if full_path.exists():
                    size = full_path.stat().st_size
                    category_size += size
                    total_size += size
                    total_files += 1
                    size_mb = size / 1024 / 1024
                    if size_mb > 0.1:
                        f.write(f"  ✓ {file_path} ({size_mb:.2f} MB)\n")
                    else:
                        f.write(f"  ✓ {file_path}\n")
                else:
                    f.write(f"  ✗ {file_path} (存在しません)\n")
            
            if category_size > 0:
                f.write(f"  小計: {category_size / 1024 / 1024:.2f} MB\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write(f"合計: {total_files}個のファイル, {total_size / 1024 / 1024:.2f} MB\n")
        f.write("=" * 80 + "\n")
    
    print(f"レポートを生成しました: {output_file}")
    return output_file


if __name__ == "__main__":
    report_path = generate_report()
    print(f"\n{report_path} を確認してください。")
