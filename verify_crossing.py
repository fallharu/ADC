import sys
import os
import sqlite3
import pandas as pd

# Add Source_code to path
sys.path.append(os.path.abspath('Source_code'))

from modules.lane_distance import assign_lane_distance
from modules.db_manager import MAIN_DB_PATH

RUN_IDS = [100364, 100355]

def verify():
    for run_id in RUN_IDS:
        print(f"\n--- Verifying Run ID {run_id} ---")
        print(f"Running assign_lane_distance for Run ID {run_id}...")
        try:
            assign_lane_distance(run_id)
        except Exception as e:
            print(f"Error during calculation for {run_id}: {e}")
            continue

        print("Checking database for Detection results...")
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            # Check Detection table
            query = f"SELECT auto_id, lane_position_flag, l_line_cross_m, r_line_cross_m FROM Detection WHERE run_id = {run_id} AND (l_line_cross_m IS NOT NULL OR r_line_cross_m IS NOT NULL) LIMIT 5"
            df = pd.read_sql_query(query, conn)
            
            if df.empty:
                print(f"No crossing detections found for Run {run_id}.")
            else:
                print("Found crossing detections in Detection table:")
                print(df)
            
            # Check OvertakeEvents table
            print("\nChecking OvertakeEvents table...")
            # We need to re-run assign_overtake to populate OvertakeEvents with new columns, 
            # BUT only if we can find the assign_overtake function.
            try:
                from modules.overtake import assign_overtake
                print(f"Running assign_overtake for Run ID {run_id}...")
                assign_overtake(run_id)
                
                ot_query = f"SELECT overtake_event_id, overtaker_l_line_cross_m, overtaker_r_line_cross_m, overtaken_l_line_cross_m, overtaken_r_line_cross_m FROM OvertakeEvents WHERE run_id = {run_id} LIMIT 5"
                ot_df = pd.read_sql_query(ot_query, conn)
                if ot_df.empty:
                    print(f"No events found in OvertakeEvents for Run {run_id}.")
                else:
                    print("Found event crossing data in OvertakeEvents:")
                    print(ot_df)
            except ImportError:
                print("Could not import assign_overtake, skipping event check.")
            except Exception as e:
                print(f"Error checking OvertakeEvents for {run_id}: {e}")

if __name__ == "__main__":
    verify()
