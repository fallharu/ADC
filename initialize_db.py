import os
import shutil
from datetime import datetime
from Source_code.modules import db_manager

# DB Path (ensure this matches your environment's path)
DB_PATH = db_manager.MAIN_DB_PATH

def main():
    print(f"Target Database: {DB_PATH}")
    
    # 1. Backup
    if os.path.exists(DB_PATH):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{DB_PATH}.backup_{timestamp}"
        try:
            os.rename(DB_PATH, backup_path)
            print(f"✅ Existing database backed up to: {backup_path}")
            
            # Backup sidecar files if they exist
            for ext in ['-shm', '-wal']:
                sidecar = DB_PATH + ext
                if os.path.exists(sidecar):
                    try:
                        os.remove(sidecar) # Remove old sidecars for safety when starting fresh
                    except Exception:
                        pass
                        
        except Exception as e:
            print(f"❌ Failed to backup database: {e}")
            return
    else:
        print("ℹ️ No existing database found. Creating new one.")

    # 2. Initialize
    try:
        print("Initializing new database...")
        db_manager.init_db()
        print("✅ Database initialized successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize database: {e}")

if __name__ == "__main__":
    # Ensure 'db' directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    main()
