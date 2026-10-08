import traceback
from Source_code.modules.summary_csv_export import generate_summary_csv
from Source_code.modules.db_manager import MAIN_DB_PATH

try:
    generate_summary_csv(MAIN_DB_PATH)
except Exception:
    traceback.print_exc()
