import sqlite3
import pandas as pd
from Source_code.modules.db_manager import MAIN_DB_PATH

def inspect_db():
    conn = sqlite3.connect(MAIN_DB_PATH)
    
    # Check Detection table for the specific run and frame
    query = """
    SELECT 
        d.run_id, 
        d.frame_num, 
        d.group_id, 
        d.class_id, 
        c.class_name,
        d.l_line_cross_m,
        d.r_line_cross_m
    FROM Detection d
    LEFT JOIN Class c ON d.class_id = c.class_id
    WHERE d.run_id = '100655' AND d.frame_num = 345 AND d.group_id = 2
    """
    
    df = pd.read_sql_query(query, conn)
    print("Detection Records for 100655 / Frame 345 / Group 2:")
    print(df)
    
    # Check OvertakeEvents
    query_events = """
    SELECT * 
    FROM OvertakeEvents 
    WHERE run_id = '100655' AND event_frame_num = 345
    """
    df_events = pd.read_sql_query(query_events, conn)
    print("\nOvertake Events for 100655 / Frame 345:")
    print(df_events)

    conn.close()

if __name__ == "__main__":
    inspect_db()
