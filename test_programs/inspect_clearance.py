import sqlite3
import pandas as pd
from Source_code.modules.db_manager import MAIN_DB_PATH

def inspect_clearance():
    print(f"Connecting to {MAIN_DB_PATH}")
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        query = """
        SELECT 
            clearance_distance_m, 
            clearance_distance_cm
        FROM Detection 
        WHERE clearance_distance_m IS NOT NULL OR clearance_distance_cm IS NOT NULL
        LIMIT 20
        """
        try:
            df = pd.read_sql_query(query, conn)
            print("Sample Data:")
            print(df)
            
            # Check stats
            print("\nStatistics:")
            stats_query = """
            SELECT 
                AVG(clearance_distance_m) as avg_m,
                AVG(clearance_distance_cm) as avg_cm,
                MAX(clearance_distance_m) as max_m,
                MAX(clearance_distance_cm) as max_cm
            FROM Detection
            WHERE clearance_distance_m IS NOT NULL
            """
            cursor = conn.execute(stats_query)
            print(cursor.fetchone())
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    inspect_clearance()
