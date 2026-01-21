import sqlite3
import pandas as pd
from Source_code.modules.db_manager import MAIN_DB_PATH
import traceback

def reproduce_error():
    print(f"Connecting to DB: {MAIN_DB_PATH}")
    db_path = MAIN_DB_PATH
    
    query = """
    SELECT DISTINCT
        d.run_id,
        v.filename as video_filename,
        d.frame_num,
        d.group_id,
        c.class_name,
        d.approach_partner_group_id,
        d.clearance_distance_m,
        d.clearance_distance_cm,
        d.approach_distance_m,
        d.overtake,
        d.line_distance,
        d.l_line_cross_m,
        d.r_line_cross_m,
        d.travel_direction
    FROM Detection d
    JOIN OvertakeEvents o ON d.run_id = o.run_id 
        AND d.frame_num = o.event_frame_num
        AND (d.group_id = o.overtaker_group_id OR d.group_id = o.overtaken_group_id)
    LEFT JOIN Video v ON d.video_id = v.video_id
    LEFT JOIN Class c ON d.class_id = c.class_id
    WHERE 
        (
            (d.group_id = o.overtaker_group_id AND LOWER(c.class_name) IN ('car', 'bus', 'truck'))
            OR
            (d.group_id = o.overtaken_group_id AND LOWER(c.class_name) IN ('bicycle', 'bike', 'cyclist'))
        )
    ORDER BY d.run_id, d.frame_num, d.group_id
    """
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(Detection)")
        detection_columns = {row[1] for row in cursor.fetchall()}

        extra_cols = []
        if "center_line_overtake_status" in detection_columns:
            extra_cols.append("d.center_line_overtake_status")
        if "white_line_overtake_status" in detection_columns:
            extra_cols.append("d.white_line_overtake_status")

        if extra_cols:
            query = query.replace("d.travel_direction", "d.travel_direction,\n        " + ",\n        ".join(extra_cols))

        df = pd.read_sql_query(query, conn)
        print(f"Loaded DataFrame with {len(df)} rows.")
        print("Dtypes:")
        print(df.dtypes)
        
        if df.empty:
            print("DF is empty!")
            return

        # Formatting steps from summary_csv_export.py
        
        print("Formatting 'overtake'...")
        df['overtake'] = df['overtake'].fillna(0).astype(int).apply(lambda x: 'あり' if x == 1 else '-')
        
        print("Rounding 'clearance_distance_m'...")
        if 'clearance_distance_m' in df.columns:
            df['clearance_distance_m'] = df['clearance_distance_m'].round(4)
            
        print("Rounding 'clearance_distance_cm'...")
        if 'clearance_distance_cm' in df.columns:
            df['clearance_distance_cm'] = df['clearance_distance_cm'].round(2)
            
        print("Rounding 'approach_distance_m'...")
        if 'approach_distance_m' in df.columns:
            df['approach_distance_m'] = df['approach_distance_m'].round(4)
            
        print("Rounding 'line_distance'...")
        if 'line_distance' in df.columns:
            df['line_distance'] = df['line_distance'].round(4)

        # Calculate crossing columns based on direction (Simplified logic print)
        print("Calculating cross columns...")
        def get_cross(row):
            direction = str(row.get('travel_direction', '')).strip().upper()
            l_cross = row.get('l_line_cross_m')
            r_cross = row.get('r_line_cross_m')
            class_name = str(row.get('class_name', '')).lower()
            is_bike = any(x in class_name for x in ['bicycle', 'bike', 'cyclist'])
            center_cross = None
            white_cross = None
            if direction == 'F':
                white_cross = l_cross
                center_cross = r_cross
            else:
                center_cross = l_cross
                white_cross = r_cross
            if not is_bike: white_cross = None
            if is_bike: center_cross = None
            return pd.Series([center_cross, white_cross], index=['中央線越え(m)', '白線越え(m)'])

        cross_df = df.apply(get_cross, axis=1)
        df = pd.concat([df, cross_df], axis=1)

        print("Rounding '中央線越え(m)'...")
        df['中央線越え(m)'] = pd.to_numeric(df['中央線越え(m)'], errors='coerce').round(2)
        
        print("Rounding '白線越え(m)'...")
        df['白線越え(m)'] = pd.to_numeric(df['白線越え(m)'], errors='coerce').round(2)

        print("Done!")

    except Exception:
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    reproduce_error()
