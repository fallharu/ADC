import requests
import json
import time

BASE_URL = "http://127.0.0.1:5001"

def test_export_csv():
    print("Testing CSV Export...")
    try:
        resp = requests.get(f"{BASE_URL}/api/manual_overtake/export?format=csv")
        if resp.status_code == 200:
            print("  [OK] CSV Export successful")
            print(f"  Content Preview: {resp.text[:100]}...")
        elif resp.status_code == 404:
             print("  [WARN] No data to export (404)")
        else:
            print(f"  [FAIL] CSV Export failed: {resp.status_code} - {resp.text[:100]}")
    except Exception as e:
        print(f"  [FAIL] Exception: {e}")

def test_export_excel():
    print("Testing Excel Export...")
    try:
        resp = requests.get(f"{BASE_URL}/api/manual_overtake/export?format=excel")
        if resp.status_code == 200:
            print(f"  [OK] Excel Export successful (Size: {len(resp.content)} bytes)")
        elif resp.status_code == 404:
             print("  [WARN] No data to export (404)")
        else:
            print(f"  [FAIL] Excel Export failed: {resp.status_code} - {resp.text[:100]}")
    except Exception as e:
        print(f"  [FAIL] Exception: {e}")

def test_process_backlog():
    print("Testing Backlog Processing...")
    try:
        # First ensure we have something in backlog (optional, or just run with empty)
        payload = {"limit": 1}
        resp = requests.post(f"{BASE_URL}/api/manual_overtake/process_backlog", json=payload)
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"  [OK] Processing API call successful")
            print(f"  Result: {json.dumps(data, ensure_ascii=False)}")
        else:
            print(f"  [FAIL] Processing failed: {resp.status_code} - {resp.text[:100]}")
            
    except Exception as e:
        print(f"  [FAIL] Exception: {e}")

if __name__ == "__main__":
    test_export_csv()
    test_export_excel()
    test_process_backlog()
