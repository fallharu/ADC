import sys
import os
from dotenv import load_dotenv

# Ensure we can import modules
sys.path.append(os.getcwd())

load_dotenv()

try:
    from Source_code.modules.db_manager import ensure_manual_overtake_event_columns, MAIN_DB_PATH
    print(f"Migrating DB at: {MAIN_DB_PATH}")
    ensure_manual_overtake_event_columns()
    print("Migration completed successfully.")
except Exception as e:
    print(f"Migration failed: {e}")
