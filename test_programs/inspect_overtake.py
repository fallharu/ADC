import sqlite3
import pandas as pd
import os

db_path = r'c:\Users\kurok\Downloads\G_ADC\ADC_08\db\my_app_data.db'

def inspect_overtake_data():
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    
    try:
        # Check columns
        print("--- Detection Table Columns ---")
        df_cols = pd.read_sql_query("SELECT * FROM Detection LIMIT 1", conn)
        print(df_cols.columns.tolist())
        
        cols = df_cols.columns.tolist()
        has_obj_id = 'obj_id' in cols
        pk_col = 'auto_id' if 'auto_id' in cols else 'detection_id'

        # Query data
        print("\n--- Detections with overtake_by ---")
        # Construct query dynamically
        sel_cols = [pk_col, 'run_id', 'frame_num', 'group_id', 'overtake_by']
        if has_obj_id:
            sel_cols.append('obj_id')
            
        query = f"SELECT {', '.join(sel_cols)} FROM Detection WHERE overtake_by IS NOT NULL LIMIT 5"
        try:
            df = pd.read_sql_query(query, conn)
            print(df)
        except Exception as e:
            print(f"Query failed: {e}")
            return

        if df.empty:
            print("No overtake events found.")
            return

        # Investigate the first row
        row = df.iloc[0]
        overtake_val = row['overtake_by']
        run_id = row['run_id']
        frame_num = row['frame_num']
        
        print(f"\n--- Investigating Partner for {pk_col}={row[pk_col]}, overtake_by={overtake_val} ---")
        
        # Check matches in potential columns
        print(f"Searching for partner where column == {overtake_val} (run_id={run_id}, frame={frame_num})")
        
        # 1. Check group_id
        q_grp = f"SELECT {pk_col}, group_id, obj_id FROM Detection WHERE run_id='{run_id}' AND frame_num={frame_num} AND group_id='{overtake_val}'"
        print("Match on group_id?:")
        print(pd.read_sql_query(q_grp, conn))

        # 2. Check obj_id (if exists)
        if has_obj_id:
            q_obj = f"SELECT {pk_col}, group_id, obj_id FROM Detection WHERE run_id='{run_id}' AND frame_num={frame_num} AND obj_id='{overtake_val}'"
            print("Match on obj_id?:")
            print(pd.read_sql_query(q_obj, conn))
            
        # 3. Check auto_id/detection_id (unlikely to match simple ID if it's cross-frame tracking, but possible)
        q_pk = f"SELECT {pk_col}, group_id FROM Detection WHERE {pk_col}={overtake_val}"
        print(f"Match on {pk_col}?:")
        print(pd.read_sql_query(q_pk, conn))

    finally:
        conn.close()

if __name__ == "__main__":
    inspect_overtake_data()
