import sqlite3
from Source_code.modules.db_manager import MAIN_DB_PATH, ensure_detection_columns, ensure_video_metadata_columns

def main():
    print(f"Target Database: {MAIN_DB_PATH}")
    print("Running ensures...")
    
    # ensure_detection_columns now includes front_distance_m
    ensure_detection_columns() 
    ensure_video_metadata_columns()
    
    print("✅ Schema update completed successfully.")

if __name__ == "__main__":
    main()
