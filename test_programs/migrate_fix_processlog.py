import sqlite3
from Source_code.modules.db_manager import MAIN_DB_PATH, ensure_processlog_columns

def main():
    print(f"Target Database: {MAIN_DB_PATH}")
    print("Running ensure_processlog_columns...")
    
    ensure_processlog_columns()
    
    print("✅ Schema update for ProcessLog completed successfully.")

if __name__ == "__main__":
    main()
