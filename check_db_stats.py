import sqlite3
import sys

db_path = 'db/my_app_data.db'

def check_db():
    try:
        with open('db_check_result.txt', 'w', encoding='utf-8') as f:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            f.write('--- 2025 Overtake Counts ---\n')
            query = """
            SELECT 
                v.road_type, 
                COUNT(e.overtake_event_id) as total, 
                SUM(CASE WHEN e.speed_profile_json IS NOT NULL THEN 1 ELSE 0 END) as processed 
            FROM OvertakeEvents e 
            JOIN ProcessLog p ON e.run_id = p.run_id 
            JOIN Video v ON p.video_id = v.video_id 
            WHERE v.collection_year = 2025 
            GROUP BY v.road_type
            """
            cursor.execute(query)
            rows = cursor.fetchall()
            for row in rows:
                f.write(f"Road Type: {row[0]}, Total Events: {row[1]}, Processed Events: {row[2]}\n")
                
            f.write('\n--- OvertakeEvents Columns ---\n')
            cursor.execute('PRAGMA table_info(OvertakeEvents)')
            cols = [r[1] for r in cursor.fetchall()]
            f.write(str(cols) + '\n')

            f.write('\n--- Detection Columns ---\n')
            cursor.execute('PRAGMA table_info(Detection)')
            cols = [r[1] for r in cursor.fetchall()]
            f.write(str(cols) + '\n')
            
            conn.close()
        print("Done writing to db_check_result.txt")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_db()
