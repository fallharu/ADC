
import sqlite3
import logging
from collections import Counter
from datetime import datetime
from typing import List, Dict, Tuple, Any

from .db_manager import MAIN_DB_PATH, configure_connection
from .calibration_loader import load_calibration_json

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
                        profile_name = row[0]
                        profile, _ = load_calibration_json(run_id, profile_name)
                        count_lines = profile.get("count_lines", []) if isinstance(profile, dict) else []
                    except FileNotFoundError:
                        logger.error(f"Calibration file not found for run_id {run_id}: {row[0]}")
                    except Exception as e:
                        logger.error(f"Failed to load calibration profile for run_id {run_id}: {e}")

                # ???????: ??????????????????Y???
                if not count_lines:
                    try:
                        c.execute(
                            """
                            SELECT d.y1, d.y2, c.class_name
                            FROM Detection d
                            JOIN Class c ON d.class_id = c.class_id
                            WHERE d.run_id = ? AND d.model_name != 'best'
                            """,
                            (run_id,),
                        )
                        bike_ys = []
                        for y1, y2, class_name in c.fetchall():
                            name = str(class_name or "").lower()
                            if "bicycle" in name or "bike" in name:
                                bike_ys.append(int(round((y1 + y2) / 2.0)))

                        if bike_ys:
                            y_mode = Counter(bike_ys).most_common(1)[0][0]
                            c.execute("SELECT MAX(x2) FROM Detection WHERE run_id = ?", (run_id,))
                            width_row = c.fetchone()
                            default_width = int(width_row[0]) if width_row and width_row[0] else 1920
                            count_lines = [
                                [[0, y_mode], [default_width, y_mode]],
                            ]
                            use_fallback = True
                            logger.info(
                                f"No count lines for run_id {run_id}. Using bicycle Y mode line (Y={y_mode})."
                            )
                        else:
                            raise ValueError("No bicycle detections")
                    except Exception:
                        logger.info(f"No count lines for run_id {run_id}. Using fallback lines (Y=700, Y=100).")
                        use_fallback = True
                        default_width = 1920
                        count_lines = [
                            [[0, 700], [default_width, 700]],  # Line A (Y=700)
                            [[0, 100], [default_width, 100]],  # Line B (Y=100)
                        ]

                # 2. Clear existing counts
                self._clear_counts(c, run_id)

                # Fetch Class Map (ClassMaster + Class)
                class_map = {}
                try:
                    c.execute("SELECT class_id, class_name FROM ClassMaster")
                    class_map.update({row[0]: row[1] for row in c.fetchall()})
                except sqlite3.Error:
                    pass
                try:
                    c.execute("SELECT class_id, class_name FROM Class")
                    for class_id, class_name in c.fetchall():
                        if class_id not in class_map:
                            class_map[class_id] = class_name
                except sqlite3.Error:
                    pass

                bicycle_ids = {
                    class_id
                    for class_id, class_name in class_map.items()
                    if 'bicycle' in str(class_name or '').lower()
                    or 'bike' in str(class_name or '').lower()
                }
                car_ids = {
                    class_id
                    for class_id, class_name in class_map.items()
                    if 'car' in str(class_name or '').lower()
                    or 'truck' in str(class_name or '').lower()
                    or 'bus' in str(class_name or '').lower()
                    or 'vehicle' in str(class_name or '').lower()
                }
                self._bicycle_ids = bicycle_ids
                self._car_ids = car_ids

                # 3. Fetch detections
                c.execute("""
                    SELECT obj_id, frame_num, x1, y1, x2, y2, class_id, model_name
                    FROM Detection
                    WHERE run_id = ?
                      AND (model_name IS NULL OR LOWER(model_name) != 'best')
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
                


                for row in rows:
                    obj_id, frame_num, x1, y1, x2, y2, class_id, model_name = row
                    
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
                        "class_id": class_id 
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

        class_id = trajectory[0]["class_id"]
        
        # クラス名を車両タイプに変換
        def get_vehicle_type(class_id):
            """Count using class_id only (YOLO results)."""
            if class_id in self._bicycle_ids:
                return '自転車'
            if class_id in self._car_ids:
                return '車'
            return 'その他'
        
        object_type = get_vehicle_type(class_id)
        
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
