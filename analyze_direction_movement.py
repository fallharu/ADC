import sqlite3
import pandas as pd

db_path = 'db/my_app_data.db'

def analyze_movement():
    try:
        conn = sqlite3.connect(db_path)
        
        # 追跡データ（track_idが同じもののy座標変化）を取得
        # travel_directionFとBそれぞれについて、代表的なtrack_idを抽出して動きを見る
        
        # まずFとBを持つtrack_idを探す
        query_ids = """
        SELECT track_id, travel_direction, run_id 
        FROM Detection 
        WHERE travel_direction IN ('F', 'B') 
        GROUP BY track_id, travel_direction 
        LIMIT 10
        """
        df_ids = pd.read_sql_query(query_ids, conn)
        
        # それらのtrack_idについて、フレームごとのy座標を取得
        # measure_y または (y1+y2)/2
        track_stats = []
        for index, row in df_ids.iterrows():
            tid = row['track_id']
            direction = row['travel_direction']
            rid = row['run_id']
            
            # 時系列データを取得
            q_track = f"""
            SELECT frame_num, (y1 + y2) / 2.0 as center_y
            FROM Detection
            WHERE run_id = {rid} AND track_id = {tid}
            ORDER BY frame_num
            """
            df_track = pd.read_sql_query(q_track, conn)
            
            if len(df_track) > 1:
                start_y = df_track.iloc[0]['center_y']
                end_y = df_track.iloc[-1]['center_y']
                diff = end_y - start_y
                movement = "Down (Increase Y)" if diff > 0 else "Up (Decrease Y)"
                track_stats.append({
                    "Direction_Label": direction,
                    "Start_Y": start_y,
                    "End_Y": end_y,
                    "Diff": diff,
                    "Movement": movement
                })

        msg = ""
        msg += "--- Track ID Samples ---\n"
        msg += str(df_ids) + "\n\n"
        msg += "--- Movement Analysis ---\n"
        msg += str(pd.DataFrame(track_stats))
        
        with open('movement_analysis_utf8.txt', 'w', encoding='utf-8') as f:
            f.write(msg)
            
        print("Analysis saved to movement_analysis_utf8.txt")
        
        conn.close()
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_movement()
