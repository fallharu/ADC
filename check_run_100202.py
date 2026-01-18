import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

test_run_id = 100202

print(f"=== Run ID {test_run_id} Detection 詳細 ===\n")

c.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN group_id IS NOT NULL THEN 1 ELSE 0 END) as has_group,
        SUM(CASE WHEN track_id IS NOT NULL THEN 1 ELSE 0 END) as has_track,
        SUM(CASE WHEN line_distance_m IS NOT NULL THEN 1 ELSE 0 END) as has_line_dist
    FROM Detection WHERE run_id = ?
""", (test_run_id,))
row = c.fetchone()
print(f"総Detection数: {row[0]}")
print(f"group_id有: {row[1]}")
print(f"track_id有: {row[2]}")
print(f"line_distance_m有: {row[3]}")

print(f"\n=== サンプルデータ (10件) ===")
c.execute("""
    SELECT auto_id, model_name, track_id, group_id, class_id
    FROM Detection 
    WHERE run_id = ?
    LIMIT 10
""", (test_run_id,))
for row in c.fetchall():
    print(f"  auto_id={row[0]}, model={row[1]}, track_id={row[2]}, group_id={row[3]}, class_id={row[4]}")

conn.close()
