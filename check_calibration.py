import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== ProcessLog 確認: calibration_profile ===')
c.execute("""
    SELECT 
        p.run_id,
        p.calibration_profile,
        (SELECT COUNT(*) FROM Detection d WHERE d.run_id = p.run_id) as det_count,
        (SELECT COUNT(*) FROM Detection d WHERE d.run_id = p.run_id AND d.group_id IS NOT NULL) as has_group
    FROM ProcessLog p
    ORDER BY p.run_id DESC
    LIMIT 15
""")
for row in c.fetchall():
    print(f'  Run {row[0]}: profile="{row[1]}", det={row[2]}, group有={row[3]}')

print('\n=== キャリブレーションプロファイルの統計 ===')
c.execute("""
    SELECT calibration_profile, COUNT(*) as cnt
    FROM ProcessLog
    GROUP BY calibration_profile
""")
for row in c.fetchall():
    print(f'  "{row[0]}": {row[1]} runs')

conn.close()
