
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

    def count(self, run_id: int) -> None:
        """
        Perform traffic counting for a specific run_id.
        Counts are stored in the TrafficCount table.
        """
        try:
            with sqlite3.connect(MAIN_DB_PATH) as conn:
                configure_connection(conn)
                c = conn.cursor()

                # 1. Fetch calibration payload
                c.execute("SELECT calibration_profile FROM ProcessLog WHERE run_id = ?", (run_id,))
                row = c.fetchone()
                if not row or not row[0]:
                    logger.info(f"No calibration profile for run_id {run_id}. Skipping counting.")
                    return
                
                try:
                    profile = json.loads(row[0])
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in calibration profile for run_id {run_id}.")
                    return

                count_lines = profile.get("count_lines", [])
                if not count_lines:
                    logger.info(f"No count lines defined for run_id {run_id}. Skipping counting.")
                    self._clear_counts(c, run_id)
                    conn.commit()
                    return

                # 2. Clear existing counts
                self._clear_counts(c, run_id)

                # Fetch Class Map
                c.execute("SELECT class_id, class_name FROM Class")
                class_map = {row[0]: row[1] for row in c.fetchall()}

                # 3. Fetch detections
                # Order by obj_id, then frame_num to reconstruct trajectories easily
                # Note: class_id is available, not class_name directly
                c.execute("""
                    SELECT obj_id, frame_num, x1, y1, x2, y2, class_id 
                    FROM Detection 
                    WHERE run_id = ? 
                    ORDER BY obj_id, frame_num
                """, (run_id,))
                
                rows = c.fetchall()
                if not rows:
                    logger.info(f"No detections for run_id {run_id}.")
                    return

                # 4. Process trajectories
                current_id = None
                trajectory = []
                counts = {} # Key: (line_index, class_name), Value: count
                
                # Initialize counts for all lines
                for i in range(len(count_lines)):
                    # Store line index as key, later assume names if available (or generate "Line N")
                    pass

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

                # 5. Save results
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for (line_idx, class_name), count in counts.items():
                    line_data = count_lines[line_idx]
                    # Generate a name if not present in structure (currently structure is [[p1, p2]])
                    # Maybe 1-based index name
                    line_name = f"Line {line_idx + 1}"
                    
                    c.execute("""
                        INSERT INTO TrafficCount (run_id, count_type, object_type, count, line_name, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (run_id, 'line_cross', class_name, count, line_name, created_at))
                
                conn.commit()
                logger.info(f"Traffic counting completed for run_id {run_id}. Saved {len(counts)} records.")

        except Exception as e:
            logger.exception(f"Error in traffic counting for run_id {run_id}: {e}")

    def _clear_counts(self, c: sqlite3.Cursor, run_id: int):
        c.execute("DELETE FROM TrafficCount WHERE run_id = ?", (run_id,))

    def _process_trajectory(self, trajectory: List[Dict], count_lines: List[Any], counts: Dict):
        if len(trajectory) < 2:
            return

        class_name = trajectory[0]["class"]
        
        # Check intersections for each line
        for line_idx, line_def in enumerate(count_lines):
             # line_def is [[x1, y1], [x2, y2]]
             if len(line_def) < 2: continue
             l1 = line_def[0]
             l2 = line_def[1]
             
             crossed = False
             
             for i in range(len(trajectory) - 1):
                 p1 = trajectory[i]["pt"]
                 p2 = trajectory[i+1]["pt"]
                 
                 if self._intersects(p1, p2, l1, l2):
                     crossed = True
                     break # Count only once per line per object
             
             if crossed:
                 key = (line_idx, class_name)
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

