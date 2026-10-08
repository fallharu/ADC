import sqlite3
import os

db_path = 'db/my_app_data.db'
target_filename_part = '000G2603'
target_real_path = r'c:\Users\kurok\Downloads\G_ADC\ADC_08\output\1_250721\1_20250721_000G2603_bike_clips_20250926_183732\annotated_1_20250721_000G2603_bike_clips.mp4'

if not os.path.exists(target_real_path):
    print(f"Warning: Real path does not exist on disk: {target_real_path}")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # search
    print(f"Searching for video like '%{target_filename_part}%'...")
    cursor.execute("SELECT p.run_id, v.video_id, v.filename, v.source_path FROM ProcessLog p JOIN Video v ON p.video_id = v.video_id WHERE v.filename LIKE ?", (f'%{target_filename_part}%',))
    rows = cursor.fetchall()
    
    if rows:
        print(f"Found {len(rows)} matching runs:")
        for r in rows:
            print(r)
            run_id, video_id, fname, current_path = r
            
            # Update source_path
            print(f"Updating source_path for video_id {video_id} to {target_real_path}")
            cursor.execute("UPDATE Video SET source_path = ? WHERE video_id = ?", (target_real_path, video_id))
            conn.commit()
            print("Update committed.")
    else:
        print("No matches found.")
        
    conn.close()
except Exception as e:
    print(f"Error: {e}")
