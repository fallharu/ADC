import requests
import pandas as pd
import io
import time

# ADC_08 usually runs on port 5001 (based on context, user mentioned it)
# usage: python verify_export_adc08.py

BASE_URL = "http://localhost:5001"
EXPORT_ENDPOINT = "/api/export/overtake_tracks"

def test_export():
    print(f"Testing Export API at: {BASE_URL}{EXPORT_ENDPOINT}")
    
    try:
        start_time = time.time()
        response = requests.get(f"{BASE_URL}{EXPORT_ENDPOINT}", timeout=30)
        elapsed = time.time() - start_time
        
        print(f"Status Code: {response.status_code}")
        print(f"Time Taken: {elapsed:.2f}s")
        
        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', '')
            print(f"Content-Type: {content_type}")
            
            # Parse CSV
            csv_data = io.StringIO(response.content.decode('utf-8-sig'))
            df = pd.read_csv(csv_data)
            
            print(f"\n--- CSV Info ---")
            print(f"Rows: {len(df)}")
            print(f"Columns: {list(df.columns)}")
            
            # Check for critical columns
            required_cols = ["イベントID", "Run", "白線距離(m)", "離隔距離(m)", "Group ID", "動画名"]
            missing = [c for c in required_cols if c not in df.columns]
            
            if missing:
                print(f"❌ Missing columns: {missing}")
            else:
                print(f"✅ All required columns present.")
                
                # Check data quality
                print("\nSample Data (First 3 rows):")
                print(df.head(3).to_string(index=False))
                
                # Check metrics (simple check if they are all 0 or empty)
                dist_col = "白線距離(m)"
                if dist_col in df.columns:
                    non_zero = df[df[dist_col] != 0]
                    not_na = df[df[dist_col].notna()]
                    print(f"\nMetric '{dist_col}':")
                    print(f"  Total Rows: {len(df)}")
                    print(f"  Non-Zero Rows: {len(non_zero)}")
                    print(f"  Non-NA Rows: {len(not_na)}")
                    if len(non_zero) == 0:
                         print("⚠️ WARNING: All values for '白線距離(m)' are 0. Logic might be missing.")
                    else:
                         print("✅ Metric data looks populated.")

        else:
            print(f"❌ Failed to get export. Response: {response.text}")
            
    except Exception as e:
        print(f"❌ Exception during verification: {e}")

if __name__ == "__main__":
    test_export()
