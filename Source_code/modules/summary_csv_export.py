
import sqlite3
import pandas as pd
import io
from .db_manager import MAIN_DB_PATH

def generate_summary_csv(db_path: str = MAIN_DB_PATH) -> bytes:
    """
    Generate Overtake Summary CSV for all runs.
    Filters for rows where clearance_distance_m IS NOT NULL OR overtake = 1.
    """
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
        d.line_distance_m,
        d.l_line_cross_m,
        d.r_line_cross_m,
        d.l_line_distance_m,
        d.r_line_distance_m,
        d.lane_position_flag,
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
    
    try:
        with sqlite3.connect(db_path) as conn:
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
            
        if df.empty:
            # Return empty CSV with headers
            return b"Run ID,\xe5\x8b\x95\xe7\x94\xbb\xe3\x83\x95\xe3\x82\xa1\xe3\x82\xa4\xe3\x83\xab,\xe3\x83\x95\xe3\x83\xac\xe3\x83\xbc\xe3\x83\xa0,\xe8\x87\xaa\xe3\x82\xb0\xe3\x83\xab\xe3\x83\xbc\xe3\x83\x97ID,\xe8\x87\xaa\xe3\x82\xaf\xe3\x83\xa9\xe3\x82\xb9,\xe7\x9b\xb8\xe6\x89\x8b\xe3\x82\xb0\xe3\x83\xab\xe3\x83\xbc\xe3\x83\x97ID,\xe9\x9b\xa2\xe9\x9a\x94\xe8\xb7\x9d\xe9\x9b\xa2(m),\xe9\x9b\xa2\xe9\x9a\x94\xe8\xb7\x9d\xe9\x9b\xa2(cm),\xe6\x8e\xa5\xe8\xbf\x91\xe8\xb7\x9d\xe9\x9b\xa2(m),\xe8\xbf\xbd\xe3\x81\x84\xe8\xb6\x8a\xe3\x81\x97\xe3\x83\x95\xe3\x83\xa9\xe3\x82\xb0,\xe7\x99\xbd\xe7\xb7\x9a\xe8\xb7\x9d\xe9\x9b\xa2(m)\n"

        # Formatting
        df['overtake'] = df['overtake'].fillna(0).astype(int).apply(lambda x: 'あり' if x == 1 else '-')
        
        # Format floats/ints if needed? Pandas strict formatting is usually fine for CSV.
        # But rounding might be nice.
        if 'approach_distance_m' in df.columns:
            df['approach_distance_m'] = pd.to_numeric(df['approach_distance_m'], errors='coerce').round(4)

        # Calculate/Fill clearance_distance_cm
        if 'clearance_distance_cm' in df.columns:
            # If still null, calc from m
            mask_null_cm = df['clearance_distance_cm'].isnull()
            if 'clearance_distance_m' in df.columns:
                 df.loc[mask_null_cm, 'clearance_distance_cm'] = df.loc[mask_null_cm, 'clearance_distance_m'] * 100.0

            df['clearance_distance_cm'] = pd.to_numeric(df['clearance_distance_cm'], errors='coerce').round(2)

        if 'clearance_distance_m' in df.columns:
             df['clearance_distance_m'] = pd.to_numeric(df['clearance_distance_m'], errors='coerce').round(4)
        
        if 'line_distance_m' in df.columns:
            df['line_distance_m'] = pd.to_numeric(df['line_distance_m'], errors='coerce').round(4)

        # Calculate crossing columns based on direction
        def get_cross(row):
            direction = str(row.get('travel_direction', '')).strip().upper()
            l_cross = row.get('l_line_cross_m')
            r_cross = row.get('r_line_cross_m')
            l_dist = row.get('l_line_distance_m')
            r_dist = row.get('r_line_distance_m')
            lane_flag = str(row.get('lane_position_flag') or '').strip()
            
            # Check class for filtering
            class_name = str(row.get('class_name', '')).lower()
            is_bike = any(x in class_name for x in ['bicycle', 'bike', 'cyclist'])
            
            center_cross = None
            white_cross = None
            
            if direction == 'F':
                # F: Left=White, Right=Center
                white_cross = l_cross
                center_cross = r_cross
                white_dist = l_dist
                center_dist = r_dist
            else:
                # B: Left=Center, Right=White
                center_cross = l_cross
                white_cross = r_cross
                center_dist = l_dist
                white_dist = r_dist

            if lane_flag in {"+", "-"}:
                if lane_flag == "+":
                    center_cross = center_dist
                    white_cross = white_dist
                else:
                    center_cross = None
                    white_cross = None
            
            # Apply strict filtering:
            # White Cross -> Output ONLY if Bike
            if not is_bike:
                white_cross = None
            
            # Center Cross -> Output ONLY if NOT Bike (i.e. Car)
            if is_bike:
                center_cross = None
            
            return pd.Series([center_cross, white_cross], index=['中央線越え(m)', '白線越え(m)'])

        cross_df = df.apply(get_cross, axis=1)
        df = pd.concat([df, cross_df], axis=1)

        # Round crossing values
        df['中央線越え(m)'] = pd.to_numeric(df['中央線越え(m)'], errors='coerce').round(2)
        df['白線越え(m)'] = pd.to_numeric(df['白線越え(m)'], errors='coerce').round(2)

        def _presence_from_status_or_cross(status_value, cross_value, lane_flag, expected_cross_label, inside_label):
            if lane_flag in {"+", "-"}:
                return expected_cross_label if lane_flag == "+" else inside_label
            # Prioritize DB status if available
            if status_value is not None:
                status_text = str(status_value).strip()
                if status_text:
                    if status_text == expected_cross_label:
                        return expected_cross_label
                    elif status_text == inside_label:
                        return inside_label
                    # return status_text # Return as is? Or mapped?
            
            # Fallback to cross_value
            if pd.notnull(cross_value):
                if cross_value > 0:
                    return expected_cross_label
                else:
                    return inside_label
            return '-'

        center_status_col = "center_line_overtake_status" if "center_line_overtake_status" in df.columns else None
        white_status_col = "white_line_overtake_status" if "white_line_overtake_status" in df.columns else None

        df['中央線越え'] = df.apply(
            lambda row: _presence_from_status_or_cross(
                # Center Line: Suppress if class is Bike
                (row.get(center_status_col) if center_status_col else None) if not any(x in str(row.get('class_name', '')).lower() for x in ['bicycle', 'bike', 'cyclist']) else None,
                row.get('中央線越え(m)'), # Already Filtered (None if bike)
                row.get('lane_position_flag') if not any(x in str(row.get('class_name', '')).lower() for x in ['bicycle', 'bike', 'cyclist']) else None,
                '中央線越え',
                '中央線内側'
            ),
            axis=1,
        )
        df['白線越え'] = df.apply(
            lambda row: _presence_from_status_or_cross(
                # White Line: Suppress if class is NOT Bike (i.e. Car)
                (row.get(white_status_col) if white_status_col else None) if any(x in str(row.get('class_name', '')).lower() for x in ['bicycle', 'bike', 'cyclist']) else None,
                row.get('白線越え(m)'), # Already Filtered (None if car)
                row.get('lane_position_flag') if any(x in str(row.get('class_name', '')).lower() for x in ['bicycle', 'bike', 'cyclist']) else None,
                '白線越え',
                '白線内側'
            ),
            axis=1,
        )

        # Rename columns to Japanese
        column_map = {
            'run_id': 'Run ID',
            'video_filename': '動画ファイル',
            'frame_num': 'フレーム',
            'group_id': '自グループID',
            'class_name': '自クラス',
            'approach_partner_group_id': '相手グループID',
            'clearance_distance_m': '離隔距離(m)',
            'clearance_distance_cm': '離隔距離(cm)',
            'approach_distance_m': '接近距離(m)',
            'overtake': '追い越しフラグ',
            'line_distance_m': '白線距離(m)',
            '中央線越え(m)': '中央線越え(m)',
            '白線越え(m)': '白線越え(m)',
            '中央線越え': '中央線越え',
            '白線越え': '白線越え'
        }
        df = df.rename(columns=column_map)
        
        # Reorder if necessary (already selected in order)
        final_cols = list(column_map.values())
        # Ensure all exist
        for col in final_cols:
            if col not in df.columns:
                df[col] = None
                
        df = df[final_cols]
        
        return df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')

    except Exception as e:
        print(f"Error generating Summary CSV: {e}")
        return b""
