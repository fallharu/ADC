"""
Run ID 100202 後処理テスト
キャリブレーションプロファイル: 2_250802_y
"""
import sqlite3
import sys
import traceback
sys.path.insert(0, '.')

from Source_code.modules.db_manager import MAIN_DB_PATH

test_run_id = 100202
profile_name = "2_250802_y"

print(f"=== Run ID {test_run_id} 後処理テスト ===\n")

# First, set the calibration_profile in ProcessLog
conn = sqlite3.connect(MAIN_DB_PATH)
c = conn.cursor()

# Check current state
c.execute("SELECT calibration_profile FROM ProcessLog WHERE run_id = ?", (test_run_id,))
row = c.fetchone()
print(f"現在のprofile: {row[0] if row else 'Runが見つかりません'}")

if row:
    # Set the profile
    c.execute("UPDATE ProcessLog SET calibration_profile = ? WHERE run_id = ?", (profile_name, test_run_id))
    conn.commit()
    print(f"プロファイルを '{profile_name}' に設定しました")

c.execute("""
    SELECT COUNT(*) FROM Detection WHERE run_id = ?
""", (test_run_id,))
det_count = c.fetchone()[0]
print(f"Detection数: {det_count}")
conn.close()

# Now run post-processing
print("\n--- 後処理実行開始 ---\n")

steps = [
    ("1. グループID", "Source_code.modules.group_id", "assign_group_ids"),
    ("2. 運動学", "Source_code.modules.kinematics_analyzer", "assign_kinematics"),
    ("3. 追い越し", "Source_code.modules.overtake", "assign_overtake"),
    ("4. 接近/離隔", "Source_code.modules.approach_distance", "assign_approach_and_clearance"),
    ("5. 白線距離", "Source_code.modules.lane_distance", "assign_lane_distance"),
    ("6. 車両間距離", "Source_code.modules.inter_vehicle_distance", "analyze_proximity"),
    ("7. TTC", "Source_code.modules.ttc_calculator", "assign_ttc"),
]

results = []
for label, module_path, func_name in steps:
    print(f"{label}...")
    try:
        module = __import__(module_path, fromlist=[func_name])
        func = getattr(module, func_name)
        result = func(test_run_id)
        print(f"  ✓ 成功: {result}")
        results.append((label, "OK", None))
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        traceback.print_exc()
        results.append((label, "NG", str(e)))

print("\n=== 結果サマリー ===")
for label, status, error in results:
    if status == "OK":
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}: {error}")

# Check results
print("\n=== DB確認 ===")
conn = sqlite3.connect(MAIN_DB_PATH)
c = conn.cursor()
c.execute(f"""
    SELECT 
        SUM(CASE WHEN group_id IS NOT NULL THEN 1 ELSE 0 END) as has_group,
        SUM(CASE WHEN speed_km_h IS NOT NULL THEN 1 ELSE 0 END) as has_speed,
        SUM(CASE WHEN line_distance_m IS NOT NULL THEN 1 ELSE 0 END) as has_line_dist
    FROM Detection WHERE run_id = {test_run_id}
""")
row = c.fetchone()
print(f"Run {test_run_id}: group_id有={row[0]}, speed_km_h有={row[1]}, line_distance_m有={row[2]}")
conn.close()
