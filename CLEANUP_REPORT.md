# 使っていないテストプログラムと一時ファイルの整理 - 完了レポート

## 整理日時
2025-12-31

## 削除したファイル

### 合計
- **89個のファイル**
- **約3.90 MB**

### カテゴリ別削除ファイル

#### 1. デバッグファイル（14個）
- debug_api_struct.py
- debug_calibration_data.py
- debug_columns.py
- debug_db_paths.py
- debug_env.py
- debug_find_video.py
- debug_hash.py
- debug_master.py
- debug_run_info.py
- debug_schema.py
- debug_verify_logic.py
- debug_video_columns.py
- debug_video_search.py
- run_server_debug.py

#### 2. テストファイル（5個）
- temp_test.py
- test_line_drawing.py
- test_server_error.py
- test_thumbnail_api.py
- thumbnail_logic.py

#### 3. 検証ファイル（6個）
- verify_calibration.py
- verify_fix.py
- verify_fix_simple.py
- verify_image_annotation.py
- verify_manual_export.py
- verify_outlier_filtering.py

#### 4. チェックファイル（4個）
- check_db_paths.py
- check_db_schema.py
- check_db_structure.py
- check_syntax.py

#### 5. 一時ファイル・追加機能（12個）
- add_function.py
- add_function_safe.py
- add_get_run_video_info.py
- append_db_functions.py
- cleanup_manual_view.py
- insert_db_functions.py
- inspect_db.py
- find_syntax_error.py
- fix_null_bytes.py
- truncate_file.py
- update_video_metadata_function.py
- read_log.py

#### 6. ログ・出力ファイル（21個）
- app_debug.log
- db_inspection.txt
- db_paths_output.txt
- db_structure.json
- debug_output.txt (0.30 MB)
- debug_output_2.txt
- debug_start.log
- debug_verify.log
- detailed_error.log
- detailed_error_v2.log
- error_final.txt
- error_log.txt
- error_log_v2.txt
- full_output.txt
- paths.log
- server_debug_output.txt
- verify_result.txt
- verbose_import.log (3.24 MB) ★最大
- cols.txt
- tables.txt
- models.txt

#### 7. 一時JavaScript/JSONファイル（2個）
- debug_chunk.js
- temp_check.js

#### 8. テスト出力ファイル（5個）
- test_thumbnail.jpg
- test_comparative_report.xlsx
- test_comparative_report_v2.xlsx
- テスト＿卒論.xlsx
- テスト＿卒論_filled.xlsx

#### 9. Source_code内の検証・チェック・デバッグファイル（7個）
- Source_code/verify_calibration_check.py
- Source_code/verify_subfolder_api.py
- Source_code/verify_traffic_count.py
- Source_code/check_classes.py
- Source_code/check_db_manager_vars.py
- Source_code/check_schema.py
- Source_code/debug_report_logic.py

#### 10. scripts内のテスト・デバッグ・チェックファイル（13個）
- scripts/debug_import.py
- scripts/debug_imports.py
- scripts/debug_imports_full.py
- scripts/check_all_databases.py
- scripts/check_data_structure.py
- scripts/check_db_structure.py
- scripts/check_schema.py
- scripts/check_vacuum.py
- scripts/check_video_schema.py
- scripts/test_calibration_tool.py
- scripts/test_inference_import.py
- scripts/test_manual_metrics_isolation.py
- scripts/test_migration.py

## 残っているファイル（有用な可能性があるため保持）

### scripts内
- analyze_database.py - データベース分析
- analyze_excel.py - Excel分析
- extract_db_stats.py - DB統計抽出
- extract_db_summary.py - DBサマリー抽出
- fill_from_database.py - DBからデータ挿入
- fill_thesis_data.py - 論文データ作成
- fill_thesis_excel.py - 論文Excelデータ作成
- generate_ppt.py - PowerPoint生成
- generate_thesis_docx.py - 論文Word生成
- verify_excel.py - Excel検証
- verify_filled_excel.py - 入力済みExcel検証
- エラーチェックGPU.py - GPU動作確認

### tests内（全て保持）
- test_lane_scale.py
- test_manual_overtake_verify.py
- test_manual_reset.py
- test_measure_points.py

## 今後の推奨事項

1. **定期的な整理**: 開発中に生成されるデバッグファイルやログファイルを定期的に削除
2. **.gitignore更新**: 以下のパターンを追加することを検討
   - `debug_*.py`
   - `test_*.py`（testsディレクトリ外）
   - `verify_*.py`（Source_code外）
   - `check_*.py`（Source_code/scripts外）
   - `*.log`
   - `*_output.txt`
3. **ログディレクトリの活用**: 一時的なログやデバッグ出力は`log/`ディレクトリに集約
