import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print("=== Detection数が10件以上あるRunを探す ===\n")

c.execute("""
    SELECT p.run_id, p.calibration_profile, v.filename,
           (SELECT COUNT(*) FROM Detection d WHERE d.run_id = p.run_id) as det_count
    FROM ProcessLog p
    LEFT JOIN Video v ON p.video_id = v.video_id
    ORDER BY p.run_id DESC
    LIMIT 20
""")

for row in c.fetchall():
    run_id, profile, filename, det_count = row
    video_name = (filename or '')[:50]
    if det_count > 0:
        print(f"✓ Run {run_id}: det={det_count}, profile={profile}, {video_name}")
    else:
        print(f"✗ Run {run_id}: det={det_count} (データなし)")

conn.close()
