import sqlite3
import pandas as pd
import os

# DBパスの設定
db_path = 'db/my_app_data.db'
output_csv = 'overtake_analysis_dump.csv'

def export_db_to_csv():
    try:
        # DB接続
        conn = sqlite3.connect(db_path)
        
        # クエリの作成
        # OvertakeEventsをベースに、Video情報の年度・道路タイプ、
        # そしてDetectionテーブルから「追い越し車両」の進行方向(travel_direction)を取得して結合
        query = """
        SELECT 
            v.collection_year as Year,
            v.road_type as Road_Type,
            p.run_id as Run_ID,
            v.filename as Video_Name,
            e.overtake_event_id as Event_ID,
            e.event_frame_num as Frame_Num,
            e.overtaker_auto_id as Overtaker_ID,
            d.travel_direction as Travel_Direction,
            d.x1, d.y1, d.x2, d.y2,
            e.speed_profile_json IS NOT NULL as Has_Speed_Profile
        FROM OvertakeEvents e
        JOIN ProcessLog p ON e.run_id = p.run_id
        JOIN Video v ON p.video_id = v.video_id
        LEFT JOIN Detection d ON e.run_id = d.run_id 
             AND e.event_frame_num = d.frame_num 
             AND e.overtaker_auto_id = d.auto_id
        ORDER BY v.collection_year, v.road_type, p.run_id, e.event_frame_num
        """
        
        # Pandasで読み込み
        df = pd.read_sql_query(query, conn)
        
        # CSVに出力 (utf-8 with BOM for Excel compatibility in Japan)
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        
        print(f"Successfully exported data to {output_csv}")
        print(f"Total rows: {len(df)}")
        
        # データの概要を表示 (各Travel_Directionの件数など)
        if not df.empty:
            print("\n--- Travel Direction Distribution ---")
            print(df['Travel_Direction'].value_counts(dropna=False))
            
            print("\n--- Processed Status by Year ---")
            print(df.groupby(['Year', 'Has_Speed_Profile']).size())

        conn.close()
        
    except Exception as e:
        print(f"Error exporting data: {e}")

if __name__ == "__main__":
    export_db_to_csv()
