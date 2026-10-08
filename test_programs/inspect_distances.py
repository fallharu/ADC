import sqlite3
import pandas as pd
from Source_code.modules.db_manager import MAIN_DB_PATH

def inspect_distances():
    print(f"Connecting to {MAIN_DB_PATH}")
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        query = """
        SELECT 
            line_distance, 
            line_distance_m, 
            line_distance_cm 
        FROM Detection 
        WHERE line_distance IS NOT NULL 
        LIMIT 20
        """
        df = pd.read_sql_query(query, conn)
        print("Sample Data:")
        print(df)
        
        # Check stats
        print("\nStatistics:")
        stats_query = """
        SELECT 
            AVG(line_distance) as avg_raw,
            AVG(line_distance_m) as avg_m,
            AVG(line_distance_cm) as avg_cm,
            MAX(line_distance) as max_raw,
            MAX(line_distance_m) as max_m
        FROM Detection
        WHERE line_distance IS NOT NULL
        """
        cursor = conn.execute(stats_query)
        print(cursor.fetchone())

if __name__ == "__main__":
    inspect_distances()
