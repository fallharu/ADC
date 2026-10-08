import sys
import os
import sqlite3
import datetime
import traceback

# Add Source_code to path
sys.path.append(os.path.join(os.getcwd(), 'Source_code'))

from modules import db_manager as dbm

def test_db_backup():
    print("Testing DB Backup Logic...")
    try:
        # Mimic the logic in export_db
        output_dir = os.path.join(os.getcwd(), 'OutPut')
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"test_backup_{timestamp}.db"
        backup_filepath = os.path.join(output_dir, backup_filename)
        
        print(f"Source DB: {dbm.MAIN_DB_PATH}")
        print(f"Target Backup: {backup_filepath}")
        
        run_backup(dbm.MAIN_DB_PATH, backup_filepath)
        print("Backup successful!")
        
    except Exception as e:
        print("Backup Failed!")
        traceback.print_exc()

def run_backup(src_path, dst_path):
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"Source DB not found: {src_path}")
        
    src_conn = sqlite3.connect(src_path)
    dst_conn = sqlite3.connect(dst_path)
    
    with dst_conn:
        src_conn.backup(dst_conn)
        
    dst_conn.close()
    src_conn.close()

if __name__ == "__main__":
    test_db_backup()
