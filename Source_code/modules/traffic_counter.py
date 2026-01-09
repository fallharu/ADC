
import json
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Tuple, Any

from .db_manager import MAIN_DB_PATH, configure_connection

logger = logging.getLogger(__name__)

class TrafficCounter:
    """
    Traffic counting logic based on line crossing.
    """

    def count(self, run_id: int) -> Dict[str, int]:
        """
        Perform traffic counting for a specific run_id.
        Counts are stored in the TrafficCount table.
        Returns: {"car": count, "bicycle": count} for reporting.
        """
        result = {"car": 0, "bicycle": 0}
        
        try:
            with sqlite3.connect(MAIN_DB_PATH) as conn:
                configure_connection(conn)
                c = conn.cursor()

                # 1. Fetch calibration payload
                c.execute("SELECT calibration_profile FROM ProcessLog WHERE run_id = ?", (run_id,))
                row = c.fetchone()
                
                count_lines = []
                use_fallback = False
                
                if row and row[0]:
                    try:
                        profile = json.loads(row[0])
                        count_lines = profile.get("count_lines", [])
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON in calibration profile for run_id {run_id}.")
                
                # フォールバック: カウント線がない場合は Y=700 と Y=100 を使用
                if not count_lines:
                    logger.info(f"No count lines for run_id {run_id}. Using fallback lines (Y=700, Y=100).")
                    use_fallback = True
                    default_width = 1920
                    count_lines = [
                        [[0, 700], [default_width, 700]],  # Line A (Y=700)
                        [[0, 100], [default_width, 100]],  # Line B (Y=100)
                    ]

                # 2. Clear existing counts
                self._clear_counts(c, run_id)

                # Fetch Class Map
                c.execute("SELECT class_id, class_name FROM ClassMaster")
                class_map = {row[0]: row[1] for row in c.fetchall()}

                # 3. Fetch detections
                c.execute("""
                    SELECT obj_id, frame_num, x1, y1, x2, y2, class_id 
                    FROM Detection 
                    WHERE run_id = ? 
                    ORDER BY obj_id, frame_num
                """, (run_id,))
                
                rows = c.fetchall()
                if not rows:
                    logger.info(f"No detections for run_id {run_id}.")
                    return result

                # 4. Process trajectories
                current_id = None
                trajectory = []
                counts = {}  # Key: (line_index, object_type, direction), Value: count
                
                def get_vehicle_type(class_name):
                    """クラス名を車または自転車に分類"""
                    class_lower = class_name.lower()
                    if 'bicycle' in class_lower or 'bike' in class_lower:
                        return '自転車'
                    elif 'car' in class_lower or 'truck' in class_lower or 'bus' in class_lower or 'vehicle' in class_lower:
                        return '車'
                    else:
                        return '車'

                for row in rows:
                    obj_id, frame_num, x1, y1, x2, y2, class_id = row
                    class_name = class_map.get(class_id, f"Unknown({class_id})")
                    cx = (x1 + x2) / 2
                    cy = (y1 + y2) / 2
                    
                    if obj_id != current_id:
                        if current_id is not None:
                            self._process_trajectory(trajectory, count_lines, counts)
                        current_id = obj_id
                        trajectory = []
                    
                    trajectory.append({
                        "frame": frame_num,
                        "pt": (cx, cy),
                        "class": class_name 
                    })
                
                # Process last trajectory
                if trajectory:
                    self._process_trajectory(trajectory, count_lines, counts)

                # 5. フォールバック時: 多い方のカウント線を採用
                if use_fallback and len(count_lines) == 2:
                    # 各ラインの合計を計算
                    line_totals = [0, 0]
                    for (line_idx, obj_type, direction), cnt in counts.items():
                        line_totals[line_idx] += cnt
                    
                    # 多い方を採用
                    best_line = 0 if line_totals[0] >= line_totals[1] else 1
                    logger.info(f"Fallback: Line {best_line+1} selected (totals: {line_totals})")
                    
                    # 少ない方のデータを削除
                    counts = {k: v for k, v in counts.items() if k[0] == best_line}

                # 6. Save results
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for (line_idx, object_type, direction), count in counts.items():
                    line_name = "Line A (Y=700)" if use_fallback and line_idx == 0 else \
                                "Line B (Y=100)" if use_fallback and line_idx == 1 else \
                                f"Line {line_idx + 1}"
                    
                    direction_label = "下向き" if direction == "down" else "上向き"
                    
                    c.execute("""
                        INSERT INTO TrafficCount (run_id, line_name, object_type, direction, count, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (run_id, line_name, object_type, direction_label, count, created_at))
                    
                    # 結果集計
                    if object_type == '車':
                        result["car"] += count
                    elif object_type == '自転車':
                        result["bicycle"] += count
                
                conn.commit()
                logger.info(f"Traffic counting completed for run_id {run_id}. Car: {result['car']}, Bicycle: {result['bicycle']}")

        except Exception as e:
            logger.exception(f"Error in traffic counting for run_id {run_id}: {e}")
        
        return result

    def _clear_counts(self, c: sqlite3.Cursor, run_id: int):
        c.execute("DELETE FROM TrafficCount WHERE run_id = ?", (run_id,))

    def _process_trajectory(self, trajectory: List[Dict], count_lines: List[Any], counts: Dict):
        if len(trajectory) < 2:
            return

        class_name = trajectory[0]["class"]
        
        # クラス名を車両タイプに変換
        def get_vehicle_type(class_name):
            class_lower = class_name.lower()
            if 'bicycle' in class_lower or 'bike' in class_lower:
                return '自転車'
            elif 'car' in class_lower or 'truck' in class_lower or 'bus' in class_lower or 'vehicle' in class_lower:
                return '車'
            else:
                return '車'
        
        object_type = get_vehicle_type(class_name)
        
        # Check intersections for each line
        for line_idx, line_def in enumerate(count_lines):
             # line_def is [[x1, y1], [x2, y2]]
             if len(line_def) < 2: continue
             l1 = line_def[0]
             l2 = line_def[1]
             
             crossed = False
             crossing_direction = None
             
             for i in range(len(trajectory) - 1):
                 p1 = trajectory[i]["pt"]
                 p2 = trajectory[i+1]["pt"]
                 
                 if self._intersects(p1, p2, l1, l2):
                     crossed = True
                     # 進行方向を判定: Y座標の変化で判断
                     # Y座標が増加 = 下向き、減少 = 上向き
                     if p2[1] > p1[1]:
                         crossing_direction = "down"  # 下向き
                     else:
                         crossing_direction = "up"    # 上向き
                     break # Count only once per line per object
             
             if crossed and crossing_direction:
                 key = (line_idx, object_type, crossing_direction)
                 counts[key] = counts.get(key, 0) + 1

    def _intersects(self, p1, p2, p3, p4):
        """
        Check if line segment p1-p2 intersects with p3-p4.
        """
        def ccw(A, B, C):
            # (C.y-A.y) * (B.x-A.x) > (B.y-A.y) * (C.x-A.x)
            return (C[1]-A[1]) * (B[0]-A[0]) > (B[1]-A[1]) * (C[0]-A[0])

        # Return true if intersection
        # p1, p2 is segment 1
        # p3, p4 is segment 2
        return (ccw(p1, p3, p4) != ccw(p2, p3, p4)) and (ccw(p1, p2, p3) != ccw(p1, p2, p4))

