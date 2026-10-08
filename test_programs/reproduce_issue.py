import requests
import sys

BASE_URL = "http://127.0.0.1:5000"

def test_metadata(run_id):
    url = f"{BASE_URL}/api/manual_overtake/{run_id}/metadata"
    print(f"Testing {url}...")
    try:
        resp = requests.get(url)
        print(f"Status: {resp.status_code}")
        if resp.status_code != 200:
            print(f"Content: {resp.text[:2000]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_id = 1
    if len(sys.argv) > 1:
        run_id = sys.argv[1]
    test_metadata(run_id)
