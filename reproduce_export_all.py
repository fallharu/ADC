import sys
import os
import sqlite3
import pandas as pd
import traceback
import time

# Add Source_code to path
sys.path.append(os.path.join(os.getcwd(), 'Source_code'))

from modules import db_manager as dbm

def test_export_all_detections():
    print("Testing export_all_detections Logic with TIMING...")
    start_time = time.time()
    
    try:
        conn = sqlite3.connect(dbm.MAIN_DB_PATH)
        conn.text_factory = lambda b: b.decode("utf-8", "replace") if isinstance(b, (bytes, bytearray)) else b

        cursor = conn.cursor()

        def _columns(column_names, alias_prefix="", table_alias=""):
            return [
                f"{table_alias}.{col} AS {alias_prefix}{col}" if alias_prefix or table_alias else col
                for col in column_names
            ]

        # Table Info
        detection_cols = [row[1] for row in cursor.execute("PRAGMA table_info(Detection)")]
        processlog_cols = [row[1] for row in cursor.execute("PRAGMA table_info(ProcessLog)")]
        video_cols = [row[1] for row in cursor.execute("PRAGMA table_info(Video)")]
        try:
            class_cols = [row[1] for row in cursor.execute("PRAGMA table_info(ClassMaster)")]
            has_class_master = bool(class_cols)
        except:
            has_class_master = False

        select_cols = []
        for col in detection_cols:
            if col == "class_name": continue
            select_cols.append(f"d.{col} AS {col}")
            if col == "class_id":
                if "class_name" in detection_cols and has_class_master:
                    select_cols.append("COALESCE(NULLIF(d.class_name, ''), cm.class_name) AS class_name")
                elif "class_name" in detection_cols:
                    select_cols.append("d.class_name AS class_name")
                elif has_class_master:
                    select_cols.append("cm.class_name AS class_name")

        if "class_id" not in detection_cols:
            if "class_name" in detection_cols:
                select_cols.append("d.class_name AS class_name")
            elif has_class_master:
                select_cols.append("cm.class_name AS class_name")

        select_cols.extend(_columns(processlog_cols, alias_prefix="p_", table_alias="p"))
        select_cols.extend(_columns(video_cols, alias_prefix="v_", table_alias="v"))

        query = f"""
        SELECT
            {", ".join(select_cols)}
        FROM Detection d
        JOIN ProcessLog p ON d.run_id = p.run_id
        JOIN Video v ON p.video_id = v.video_id
        { "LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id" if has_class_master else "" }
        WHERE 1=1
        """
        
        t_query_start = time.time()
        print("Executing Query...")
        df = pd.read_sql_query(query, conn)
        t_query_end = time.time()
        print(f"Query returned {len(df)} rows. Time: {t_query_end - t_query_start:.2f}s")
        
        # Filtering Logic
        t_filter_start = time.time()
        
        expected_cols = []
        for col in detection_cols:
            if col == "class_name": continue
            expected_cols.append(col)
            if col == "class_id":
                if "class_name" in detection_cols or has_class_master:
                    expected_cols.append("class_name")
        if "class_id" not in detection_cols:
            if "class_name" in detection_cols or has_class_master:
                expected_cols.append("class_name")

        expected_cols.extend([f"p_{col}" for col in processlog_cols])
        expected_cols.extend([f"v_{col}" for col in video_cols])

        # Missing cols
        missing_cols = [col for col in expected_cols if col not in df.columns]
        for col in missing_cols:
            df[col] = None
        
        # Extra cols
        extra_cols = [col for col in df.columns if col not in expected_cols]
        if extra_cols:
            df = df.drop(columns=extra_cols)

        # --- FIX: Decode Bytes FIRST ---
        print("Decoding bytes...")
        if not df.empty:
            def _decode_bytes(value):
                if isinstance(value, memoryview):
                    value = value.tobytes()
                if isinstance(value, (bytes, bytearray)):
                    return value.decode("utf-8", "replace")
                return value

            object_cols = df.select_dtypes(include=["object"]).columns
            for col in object_cols:
                df[col] = df[col].map(_decode_bytes)
        # -------------------------------

        # Empty cols (The suspect)
        print("Starting Empty Column Check...")
        empty_cols = []
        for col in df.columns:
            t_col_start = time.time()
            series = df[col]
            if series.dtype == object:
                # Optimized check?
                # The original code:
                non_null = series.dropna()
                if non_null.empty:
                    empty_cols.append(col)
                elif non_null.astype(str).str.strip().eq("").all():
                    empty_cols.append(col)
            else:
                if not series.notna().any():
                    empty_cols.append(col)
            t_col_end = time.time()
            if t_col_end - t_col_start > 0.1:
                print(f"  Col '{col}' took {t_col_end - t_col_start:.2f}s")
                
        if empty_cols:
            df = df.drop(columns=empty_cols)
        
        t_filter_end = time.time()
        print(f"Filtering took: {t_filter_end - t_filter_start:.2f}s")

        # Ordering
        ordered_cols = [col for col in expected_cols if col in df.columns]
        if ordered_cols:
            df = df[ordered_cols]
            
        t_total = time.time() - start_time
        print(f"Total Time: {t_total:.2f}s")
        
        conn.close()

    except Exception as e:
        print("Export Logic Failed!")
        traceback.print_exc()

if __name__ == "__main__":
    test_export_all_detections()
