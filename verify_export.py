import sys
import os
import pandas as pd
import io

# Add source code to path
sys.path.append(os.getcwd())
from Source_code.modules import db_manager as dbm

def verify_export():
    print("--- Verifying Track Data Export ---")
    
    # Check 1: Simple OpenPyXL Test
    print("\n[Test 1] Simple OpenPyXL Write...")
    try:
        bio = io.BytesIO()
        with pd.ExcelWriter(bio, engine='openpyxl') as writer:
            pd.DataFrame({'A': [1,2], 'B': [3,4]}).to_excel(writer, sheet_name='Test', index=False)
        print("  OK: Simple write success.")
    except Exception as e:
        print(f"  FAIL: Simple write failed: {e}")
        return

    # Check 2: Fetch DB Data
    print("\n[Test 2] Fetch Data from DB...")
    try:
        data = dbm.get_track_data_for_export(run_id=None)
        df_bicycle = data.get('bicycle')
        df_overtake = data.get('overtake')
        
        b_len = len(df_bicycle) if df_bicycle is not None else 0
        o_len = len(df_overtake) if df_overtake is not None else 0
        print(f"  Bicycle Rows: {b_len}")
        print(f"  Overtake Rows: {o_len}")
        
    except Exception as e:
        print(f"  FAIL: DB Fetch failed: {e}")
        return

    # Check 3: Write Real Data
    print("\n[Test 3] Write Real Data...")
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Bicycle Sheet
            if b_len > 0:
                print("  Writing Bicycle sheet (English name)...")
                df_bicycle.to_excel(writer, sheet_name='Bicycle', index=False)
            else:
                print("  Writing Empty Bicycle sheet (English name)...")
                pd.DataFrame({'Info': ['No Bicycle Data']}).to_excel(writer, sheet_name='Bicycle', index=False)

            # Overtake Sheet
            if o_len > 0:
                print("  Writing Overtake sheet (English name)...")
                df_overtake.to_excel(writer, sheet_name='Overtake', index=False)
            else:
                print("  Writing Empty Overtake sheet (English name)...")
                pd.DataFrame({'Info': ['No Overtake Data']}).to_excel(writer, sheet_name='Overtake', index=False)
        
        output.seek(0)
        print(f"  SUCCESS: Export generated. Size: {len(output.read())} bytes")
        
        with open("test_export_final.xlsx", "wb") as f:
            f.write(output.getbuffer())
        print("  Saved to test_export_final.xlsx")

    except Exception as e:
        print(f"  FAIL: Real Data Write failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_export()
