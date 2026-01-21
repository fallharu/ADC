import sqlite3
import pandas as pd
from Source_code.modules.db_manager import MAIN_DB_PATH

def check_overtake_counts():
    print(f"Connecting to {MAIN_DB_PATH}")
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        query = "SELECT count(clearance_distance_m) as m_count, count(clearance_distance_cm) as cm_count FROM OvertakeEvents"
        cursor = conn.execute(query)
        print(f"OvertakeEvents non-null counts: {cursor.fetchone()}")

if __name__ == "__main__":
    check_overtake_counts()
