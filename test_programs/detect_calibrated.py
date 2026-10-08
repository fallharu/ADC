import sqlite3
import os

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

opt_folder = os.getenv('Opt_files', 'output').strip('"')
calib_dir = os.path.join(opt_folder, 'calibrations')

print('=== キャリブレーション適用済みRun ===\n')

# Get all runs with their detection counts
c.execute("""
    SELECT p.run_id, p.calibration_profile, p.video_id, v.filename,
           (SELECT COUNT(*) FROM Detection d WHERE d.run_id = p.run_id) as det_count,
           (SELECT COUNT(*) FROM Detection d WHERE d.run_id = p.run_id AND d.line_distance_m IS NOT NULL) as has_dist
    FROM ProcessLog p
    LEFT JOIN Video v ON p.video_id = v.video_id
    ORDER BY p.run_id DESC
""")
rows = c.fetchall()

applied_count = 0
file_exists_count = 0

for run_id, profile, video_id, filename, det_count, has_dist in rows:
    # Check if calibration file exists
    calib_file = os.path.join(calib_dir, f'calibration_{run_id}.json')
    file_exists = os.path.isfile(calib_file)
    
    if profile or file_exists:
        status = []
        if profile:
            status.append(f'profile="{profile}"')
            applied_count += 1
        if file_exists:
            status.append('file存在')
            file_exists_count += 1
        if has_dist > 0:
            status.append(f'距離計算済({has_dist}件)')
        
        video_name = (filename or '')[:40]
        print(f'Run {run_id}: {video_name}')
        print(f'         → {", ".join(status)}')

print(f'\n=== サマリー ===')
print(f'総Run数: {len(rows)}')
print(f'キャリブレーションファイル存在: {file_exists_count}')
print(f'プロファイル適用済み: {applied_count}')

conn.close()
