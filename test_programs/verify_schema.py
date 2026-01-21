import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== Detection テーブル スキーマ ===')
c.execute("PRAGMA table_info(Detection)")
cols = c.fetchall()
for col in cols:
    print(f'  {col[1]}: {col[2]} (nullable={not col[3]})')

# Required columns for post-processing
required_cols = [
    'auto_id', 'run_id', 'video_id', 'class_id', 'frame_num',
    'x1', 'y1', 'x2', 'y2', 'model_name', 'track_id', 'confidence',
    'group_id', 'speed_km_h', 'measure_x', 'measure_y',
    'line_distance', 'line_distance_m', 'l_line_distance_m', 'r_line_distance_m',
    'travel_direction'
]
existing_cols = [col[1] for col in cols]
missing = [c for c in required_cols if c not in existing_cols]
if missing:
    print(f'\n⚠ 不足カラム: {missing}')
else:
    print('\n✓ 必要なカラムはすべて存在します')

print('\n=== OvertakeEvents テーブル スキーマ ===')
c.execute("PRAGMA table_info(OvertakeEvents)")
for col in c.fetchall():
    print(f'  {col[1]}: {col[2]}')

conn.close()
