import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== Detection テーブルの距離関連カラム確認 ===')

# Check if distance columns have values
c.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN line_distance_m IS NOT NULL THEN 1 ELSE 0 END) as has_line_dist_m,
        SUM(CASE WHEN l_line_distance_m IS NOT NULL THEN 1 ELSE 0 END) as has_l_line_dist_m,
        SUM(CASE WHEN r_line_distance_m IS NOT NULL THEN 1 ELSE 0 END) as has_r_line_dist_m,
        SUM(CASE WHEN measure_x IS NOT NULL THEN 1 ELSE 0 END) as has_measure_x,
        SUM(CASE WHEN measure_y IS NOT NULL THEN 1 ELSE 0 END) as has_measure_y,
        SUM(CASE WHEN group_id IS NOT NULL THEN 1 ELSE 0 END) as has_group_id,
        SUM(CASE WHEN speed_km_h IS NOT NULL THEN 1 ELSE 0 END) as has_speed
    FROM Detection
""")
row = c.fetchone()
print(f'総Detection数: {row[0]}')
print(f'line_distance_m 有: {row[1]}')
print(f'l_line_distance_m 有: {row[2]}')
print(f'r_line_distance_m 有: {row[3]}')
print(f'measure_x 有: {row[4]}')
print(f'measure_y 有: {row[5]}')
print(f'group_id 有: {row[6]}')
print(f'speed_km_h 有: {row[7]}')

print('\n=== サンプルデータ (5件) ===')
c.execute("""
    SELECT run_id, frame_num, model_name, group_id, 
           line_distance_m, l_line_distance_m, r_line_distance_m, speed_km_h
    FROM Detection 
    WHERE line_distance_m IS NOT NULL OR group_id IS NOT NULL
    LIMIT 5
""")
for row in c.fetchall():
    print(f'  Run {row[0]}, Frame {row[1]}: model={row[2]}, group={row[3]}, '
          f'line_dist={row[4]}, l_dist={row[5]}, r_dist={row[6]}, speed={row[7]}')

conn.close()
