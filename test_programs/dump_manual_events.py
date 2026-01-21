import sqlite3
import pandas as pd
from Source_code.modules.db_manager import MAIN_DB_PATH

def dump_manual_events():
    print(f"Connecting to {MAIN_DB_PATH}")
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        df = pd.read_sql_query("SELECT * FROM ManualOvertakeEvents", conn)
        print(df.head())
        print(df.columns)
        # Check clearance columns specifically
        if 'clearance_distance_m' in df.columns:
            print("\nClearance Distance M:")
            print(df['clearance_distance_m'])
        if 'clearance_distance_cm' in df.columns:
            print("\nClearance Distance CM:")
            print(df['clearance_distance_cm'])

if __name__ == "__main__":
    dump_manual_events()
