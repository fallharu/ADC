from Source_code.modules.summary_csv_export import generate_summary_csv
from Source_code.modules.db_manager import MAIN_DB_PATH
import os

print(f"MAIN_DB_PATH: {MAIN_DB_PATH}")
try:
    csv_bytes = generate_summary_csv(MAIN_DB_PATH)
    print(f"Generated CSV size: {len(csv_bytes)} bytes")
    if len(csv_bytes) > 0:
        # Check if it has rows
        lines = csv_bytes.decode('utf-8-sig').splitlines()
        print(f"CSV Line count: {len(lines)}")
        if len(lines) > 0:
            print(f"Header: {lines[0]}")
        if len(lines) > 1:
            print(f"First row: {lines[1]}")
    else:
        print("Generated CSV is empty.")
except Exception as e:
    print(f"Error calling function: {e}")
