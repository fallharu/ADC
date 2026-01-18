"""
Run ID 100202 白線距離のみテスト
"""
import sqlite3
import sys
import traceback
import os
sys.path.insert(0, '.')

from Source_code.modules.db_manager import MAIN_DB_PATH
from Source_code.modules.calibration_loader import build_calibration_candidates, load_calibration_json

test_run_id = 100202
profile_name = "2_250802_y"

print(f"=== Run ID {test_run_id} キャリブレーション読み込みテスト ===\n")

# Check calibration file
calib_dir, candidates = build_calibration_candidates(test_run_id, profile_name)
print(f"キャリブレーションディレクトリ: {calib_dir}")
print(f"探索パス候補:")
for cand in candidates:
    exists = os.path.isfile(cand)
    print(f"  {cand} → {'✓存在' if exists else '✗なし'}")

# Try to load
print("\n--- キャリブレーションJSON読み込み ---")
try:
    data, path = load_calibration_json(test_run_id, profile_name)
    print(f"✓ 読み込み成功: {path}")
    print(f"  キー一覧: {list(data.keys())}")
    if 'white_line_left' in data:
        print(f"  white_line_left: {len(data['white_line_left'])} points")
    if 'white_line_right' in data:
        print(f"  white_line_right: {len(data['white_line_right'])} points")
except Exception as e:
    print(f"✗ 読み込み失敗: {e}")
    traceback.print_exc()

# Now test lane_distance
print("\n--- 白線距離計算テスト ---")
try:
    from Source_code.modules.lane_distance import assign_lane_distance
    result = assign_lane_distance(test_run_id)
    print(f"✓ 成功: {result}")
except Exception as e:
    print(f"✗ エラー: {e}")
    traceback.print_exc()

# Check DB
print("\n--- DB確認 ---")
conn = sqlite3.connect(MAIN_DB_PATH)
c = conn.cursor()
c.execute("""
    SELECT 
        SUM(CASE WHEN line_distance_m IS NOT NULL THEN 1 ELSE 0 END) as has_line_dist,
        SUM(CASE WHEN l_line_distance_m IS NOT NULL THEN 1 ELSE 0 END) as has_l_dist,
        SUM(CASE WHEN r_line_distance_m IS NOT NULL THEN 1 ELSE 0 END) as has_r_dist,
        SUM(CASE WHEN group_id IS NOT NULL THEN 1 ELSE 0 END) as has_group
    FROM Detection WHERE run_id = ?
""", (test_run_id,))
row = c.fetchone()
print(f"line_distance_m有={row[0]}, l_line有={row[1]}, r_line有={row[2]}, group_id有={row[3]}")
conn.close()
