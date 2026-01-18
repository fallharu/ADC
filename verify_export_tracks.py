import requests
import pandas as pd
import io
import traceback
import sys

URL = 'http://127.0.0.1:5001/export_tracks'

def verify():
    print(f"Requesting {URL}...")
    try:
        # Increase timeout for large data
        resp = requests.get(URL, timeout=300)
        
        print(f"Status: {resp.status_code}")
        print(f"Headers: {resp.headers}")
        
        if resp.status_code != 200:
            print(f"FAILED: Status code is {resp.status_code}")
            with open('error_response.html', 'w', encoding='utf-8') as f:
                f.write(resp.text)
            print("Saved error response to error_response.html")
            return False
            
        content_type = resp.headers.get('Content-Type', '')
        if 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' not in content_type:
             print(f"FAILED: Content-Type is not Excel. Got: {content_type}")
             return False
             
        print("Content-Type check passed.")
        
        # Verify content with pandas
        try:
            bio = io.BytesIO(resp.content)
            # Just check if we can read the '自転車' sheet
            df = pd.read_excel(bio, sheet_name='自転車')
            print("Excel loaded successfully.")
            print("Bicycle sheet columns:", list(df.columns))
            print("Row count:", len(df))
            
            # Verify specific column existence
            required_columns = ['イベントID', 'Run', '動画名', '役割', 'BBOX x1', '離隔距離(m)']
            missing = [c for c in required_columns if c not in df.columns]
            if missing:
                print(f"FAILED: Missing columns: {missing}")
                return False
                
            print("Validation passed!")
            return True
            
        except Exception as e:
             print(f"FAILED: Could not parse Excel: {e}")
             traceback.print_exc()
             return False
             
    except Exception as e:
        print(f"FAILED: Request error: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = verify()
    if not success:
        sys.exit(1)
