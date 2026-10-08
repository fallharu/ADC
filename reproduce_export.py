import sys
import os
import traceback

# Adjust path to import modules
sys.path.append(os.path.join(os.getcwd(), 'Source_code'))

from modules.full_csv_export import generate_full_csv
from modules.db_manager import MAIN_DB_PATH

def test_export():
    print(f"Testing export with DB: {MAIN_DB_PATH}")
    try:
        csv_bytes = generate_full_csv(MAIN_DB_PATH)
        print(f"Export successful! Size: {len(csv_bytes)} bytes")
        with open("test_export.csv", "wb") as f:
            f.write(csv_bytes)
        print("Written to test_export.csv")
    except Exception as e:
        print("Export failed!")
        traceback.print_exc()

if __name__ == "__main__":
    test_export()
