
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
    SELECT
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
    LEFT JOIN Video v ON d.video_id = v.video_id
    LEFT JOIN Class c ON d.class_id = c.class_id
    WHERE d.clearance_distance_m IS NOT NULL OR d.overtake = 1
    ORDER BY d.run_id, d.frame_num
    """
    
    try:
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(query, conn)
            
        if df.empty:
            # Return empty CSV with headers
            return b"Run ID,\xe5\x8b\x95\xe7\x94\xbb\xe3\x83\x95\xe3\x82\xa1\xe3\x82\xa4\xe3\x83\xab,\xe3\x83\x95\xe3\x83\xac\xe3\x83\xbc\xe3\x83\xa0,\xe8\x87\xaa\xe3\x82\xb0\xe3\x83\xab\xe3\x83\xbc\xe3\x83\x97ID,\xe8\x87\xaa\xe3\x82\xaf\xe3\x83\xa9\xe3\x82\xb9,\xe7\x9b\xb8\xe6\x89\x8b\xe3\x82\xb0\xe3\x83\xab\xe3\x83\xbc\xe3\x83\x97ID,\xe9\x9b\xa2\xe9\x9a\x94\xe8\xb7\x9d\xe9\x9b\xa2(m),\xe9\x9b\xa2\xe9\x9a\x94\xe8\xb7\x9d\xe9\x9b\xa2(cm),\xe6\x8e\xa5\xe8\xbf\x91\xe8\xb7\x9d\xe9\x9b\xa2(m),\xe8\xbf\xbd\xe3\x81\x84\xe8\xb6\x8a\xe3\x81\x97\xe3\x83\x95\xe3\x83\xa9\xe3\x82\xb0,\xe7\x99\xbd\xe7\xb7\x9a\xe8\xb7\x9d\xe9\x9b\xa2(m)\n"

        # Formatting
        df['overtake'] = df['overtake'].fillna(0).astype(int).apply(lambda x: 'あり' if x == 1 else '-')
        
        # Format floats/ints if needed? Pandas strict formatting is usually fine for CSV.
        # But rounding might be nice.
        if 'clearance_distance_m' in df.columns:
            df['clearance_distance_m'] = df['clearance_distance_m'].round(4)
        if 'clearance_distance_cm' in df.columns:
            df['clearance_distance_cm'] = df['clearance_distance_cm'].round(2)
        if 'approach_distance_m' in df.columns:
            df['approach_distance_m'] = df['approach_distance_m'].round(4)
        if 'line_distance' in df.columns:
            df['line_distance'] = df['line_distance'].round(4)

        # Calculate crossing columns based on direction
        def get_cross(row):
            direction = str(row.get('travel_direction', '')).strip().upper()
            l_cross = row.get('l_line_cross_m')
            r_cross = row.get('r_line_cross_m')
            
            center_cross = None
            white_cross = None
            
            if direction == 'F':
                # F: Left=White, Right=Center
                white_cross = l_cross
                center_cross = r_cross
            else:
                # B: Left=Center, Right=White
                center_cross = l_cross
                white_cross = r_cross
            
            return pd.Series([center_cross, white_cross], index=['中央線越え(m)', '白線越え(m)'])

        cross_df = df.apply(get_cross, axis=1)
        df = pd.concat([df, cross_df], axis=1)

        # Round crossing values
        df['中央線越え(m)'] = pd.to_numeric(df['中央線越え(m)'], errors='coerce').round(2)
        df['白線越え(m)'] = pd.to_numeric(df['白線越え(m)'], errors='coerce').round(2)

        def to_presence_flag(series: pd.Series) -> pd.Series:
            return series.apply(lambda value: 'あり' if pd.notnull(value) and value > 0 else 'なし')

        df['中央線追い越し'] = to_presence_flag(df['中央線越え(m)'])
        df['外側線追い越し'] = to_presence_flag(df['白線越え(m)'])

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
            'line_distance': '白線距離(m)',
            '中央線越え(m)': '中央線越え(m)',
            '白線越え(m)': '白線越え(m)',
            '中央線追い越し': '中央線追い越し',
            '外側線追い越し': '外側線追い越し'
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
