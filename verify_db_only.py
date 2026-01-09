import sys
import os
import pandas as pd

# Add source code to path
sys.path.append(os.getcwd())
try:
    from Source_code.modules import db_manager as dbm
except ImportError:
    pass

def verify_db_only():
    print("--- Verifying DB Only ---")
    try:
        print("Calling get_track_data_for_export...")
        data = dbm.get_track_data_for_export(run_id=None)
        
        if not isinstance(data, dict):
            print("[ERROR] Data is not a dict")
            return

        for k, v in data.items():
            print(f"Key: {k}, Type: {type(v)}")
            if isinstance(v, pd.DataFrame):
                print(f"  Shape: {v.shape}")
                print(f"  Columns: {v.columns.tolist()}")
                if not v.empty:
                    print(f"  First Row: {v.iloc[0].to_dict()}")
            else:
                print("  Not a dataframe")
        
        print("[SUCCESS] DB Fetch complete.")
    except Exception as e:
        print(f"[ERROR] DB Fetch failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_db_only()
