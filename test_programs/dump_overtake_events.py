import sqlite3
import pandas as pd
from Source_code.modules.db_manager import MAIN_DB_PATH

def dump_overtake_events():
    print(f"Connecting to {MAIN_DB_PATH}")
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        df = pd.read_sql_query("SELECT * FROM OvertakeEvents", conn)
        print(df.head())
        print(df.columns)
        print(df.describe())

if __name__ == "__main__":
    dump_overtake_events()
