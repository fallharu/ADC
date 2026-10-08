import sqlite3
import pandas as pd
from Source_code.modules.db_manager import MAIN_DB_PATH
import os

def debug_export():
    print(f"Connecting to DB: {MAIN_DB_PATH}")
    ot_count = 0
    det_count = 0
    query_rows = 0
    
    conn = None
    try:
        conn = sqlite3.connect(MAIN_DB_PATH)
        cursor = conn.cursor()
        
        # 1. Total OvertakeEvents
        try:
            cursor.execute("SELECT COUNT(*) FROM OvertakeEvents")
            ot_count = cursor.fetchone()[0]
        except Exception as e:
            print(f"Error counting OvertakeEvents: {e}")
        
        # 2. Total Detection
        try:
            cursor.execute("SELECT COUNT(*) FROM Detection")
            det_count = cursor.fetchone()[0]
        except Exception as e:
            print(f"Error counting Detection: {e}")

        # 3. Class Names
        try:
            cursor.execute("SELECT * FROM Class")
            # Just verify it doesn't fail
            classes = cursor.fetchall()
        except:
            pass
            
        # 4. Run the query
        query = """
        SELECT DISTINCT
            d.run_id,
            d.frame_num,
            d.group_id,
            c.class_name
        FROM Detection d
        JOIN OvertakeEvents o ON d.run_id = o.run_id 
            AND d.frame_num = o.event_frame_num
            AND (d.group_id = o.overtaker_group_id OR d.group_id = o.overtaken_group_id)
        LEFT JOIN Class c ON d.class_id = c.class_id
        WHERE 
            (
                (d.group_id = o.overtaker_group_id AND LOWER(c.class_name) IN ('car', 'bus', 'truck'))
                OR
                (d.group_id = o.overtaken_group_id AND LOWER(c.class_name) IN ('bicycle', 'bike', 'cyclist'))
            )
        """
        
        df = pd.read_sql_query(query, conn)
        query_rows = len(df)
        print(f"Query returned {query_rows} rows.")
        
    except Exception as e:
        print(f"Global Error: {e}")
    finally:
        if conn:
            conn.close()
        
        print(f"\n--- SUMMARY ---")
        print(f"DB Path used: {os.path.abspath(MAIN_DB_PATH)}")
        print(f"Total OvertakeEvents: {ot_count}")
        print(f"Total Detection: {det_count}")
        print(f"Query returned: {query_rows} rows")

if __name__ == "__main__":
    debug_export()
