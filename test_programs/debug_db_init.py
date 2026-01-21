import os
import sqlite3
import traceback

# Setup Env
os.environ["MAIN_DB_PATH"] = "db/test_adc_debug.db"

# Cleanup old
if os.path.exists("db/test_adc_debug.db"):
    os.remove("db/test_adc_debug.db")

try:
    from Source_code.modules import db_manager
    print(f"DB Manager imported. Path: {db_manager.MAIN_DB_PATH}")

    print("Initializing DB...")
    db_manager.init_db()
    print("DB Initialized successfully.")

except Exception:
    traceback.print_exc()
