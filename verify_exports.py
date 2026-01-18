import sys
import os
import sqlite3
import pandas as pd
import io

# Add Source_code to path
sys.path.append(os.path.abspath('Source_code'))

from modules.summary_csv_export import generate_summary_csv
from modules.kanaoka_export import generate_kanaoka_excel
from modules.db_manager import MAIN_DB_PATH

def verify():
    print(f"\n--- Verifying Exports ---")
    
    # Verify Summary CSV
    print("\n[Summary CSV Export]")
    try:
        csv_bytes = generate_summary_csv(MAIN_DB_PATH)
        # Summary export returns bytes now
        df_csv = pd.read_csv(io.BytesIO(csv_bytes))
        cols = df_csv.columns.tolist()
        # print(f"Columns: {cols}")
        if '中央線越え(m)' in cols and '白線越え(m)' in cols:
            print("SUCCESS: Crossing columns found in Summary CSV!")
            # Check for non-null values
            cross_data = df_csv[(df_csv['中央線越え(m)'].notnull()) | (df_csv['白線越え(m)'].notnull())]
            if not cross_data.empty:
                print("Found crossing data in CSV (Top 5):")
                print(cross_data[['Run ID', 'フレーム', '中央線越え(m)', '白線越え(m)']].head())
            else:
                print("No crossing data found in CSV records.")
        else:
            print("FAILURE: Crossing columns MISSING in Summary CSV!")
    except Exception as e:
        print(f"Error in Summary CSV export: {e}")

    # Verify Kanaoka Excel
    print("\n[Kanaoka Excel Export]")
    try:
        excel_bytes = generate_kanaoka_excel(MAIN_DB_PATH)
        df_excel = pd.read_excel(io.BytesIO(excel_bytes))
        cols = df_excel.columns.tolist()
        
        target_cols = [
            "追い越し側中央線越え(m)", "追い越し側白線越え(m)",
            "追い越され側中央線越え(m)", "追い越され側白線越え(m)"
        ]
        
        found = [c for c in target_cols if c in cols]
        if len(found) == len(target_cols):
            print("SUCCESS: All crossing columns found in Kanaoka Excel!")
            # Check for non-null values
            cross_excel = df_excel[df_excel[target_cols].notnull().any(axis=1)]
            if not cross_excel.empty:
                print("Found crossing data in Excel (Top 5):")
                print(cross_excel[['フレーム'] + target_cols].head())
            else:
                print("No crossing data found in Excel records.")
        else:
            print(f"FAILURE: Missing columns in Excel: {set(target_cols) - set(found)}")
            
    except Exception as e:
        print(f"Error in Kanaoka Excel export: {e}")

if __name__ == "__main__":
    verify()
