import sqlite3
import os
import json

# Check calibration profiles and validate JSON files
conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== ProcessLog のキャリブレーションプロファイル ===')
c.execute("""
    SELECT run_id, calibration_profile
    FROM ProcessLog
    WHERE calibration_profile IS NOT NULL AND calibration_profile != ''
    ORDER BY run_id DESC
    LIMIT 10
""")
profiles = c.fetchall()
for row in profiles:
    print(f'  Run {row[0]}: profile="{row[1]}"')

print('\n=== キャリブレーションJSONファイル確認 ===')
calib_dir = 'calibrations'
if os.path.exists(calib_dir):
    files = os.listdir(calib_dir)
    print(f'calibrations/ フォルダ内: {len(files)} ファイル')
    for f in files[:10]:
        fpath = os.path.join(calib_dir, f)
        try:
            with open(fpath, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            has_white = 'white_line_left' in data or 'white_line' in data
            print(f'  ✓ {f}: 読み込みOK (white_line={has_white})')
        except json.JSONDecodeError as e:
            print(f'  ✗ {f}: JSON読み込みエラー: {e}')
        except Exception as e:
            print(f'  ✗ {f}: その他エラー: {e}')
else:
    print('calibrations/ フォルダが見つかりません')

# Check if profile matches any file
print('\n=== プロファイル名とファイルの一致確認 ===')
if profiles and os.path.exists(calib_dir):
    for run_id, profile_name in profiles[:5]:
        # Try different naming patterns
        candidates = [
            f'{profile_name}.json',
            f'calibration_{profile_name}.json',
            f'{profile_name}',
        ]
        found = False
        for cand in candidates:
            if os.path.exists(os.path.join(calib_dir, cand)):
                print(f'  Run {run_id}: "{profile_name}" → {cand} ✓')
                found = True
                break
        if not found:
            print(f'  Run {run_id}: "{profile_name}" → ファイルが見つかりません ✗')

conn.close()
