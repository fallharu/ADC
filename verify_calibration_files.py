import sqlite3
import os
import json

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

opt_folder = os.getenv('Opt_files', 'output').strip('"')
calib_dir = os.path.join(opt_folder, 'calibrations')

print(f'=== キャリブレーションディレクトリ: {calib_dir} ===')
print(f'存在: {os.path.exists(calib_dir)}')
if os.path.exists(calib_dir):
    print(f'ファイル数: {len(os.listdir(calib_dir))}')

print('\n=== 最新15件のProcessLog ===')
c.execute("""
    SELECT run_id, calibration_profile
    FROM ProcessLog
    ORDER BY run_id DESC
    LIMIT 15
""")
rows = c.fetchall()

for run_id, profile in rows:
    # Check if corresponding file exists
    candidates = []
    if profile:
        candidates.append(os.path.join(calib_dir, f'{profile}.json'))
    candidates.append(os.path.join(calib_dir, f'calibration_{run_id}.json'))
    
    found = None
    valid = False
    for cand in candidates:
        if os.path.isfile(cand):
            found = cand
            try:
                with open(cand, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                valid = True
            except:
                valid = False
            break
    
    if found:
        status = '✓ JSON有効' if valid else '✗ JSON無効'
    else:
        status = '✗ ファイルなし'
    
    print(f'  Run {run_id}: profile="{profile}" → {status}')

conn.close()
