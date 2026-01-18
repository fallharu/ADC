import requests
import sqlite3
import os
import sys
from dotenv import load_dotenv

# Add current directory to path to allow imports if needed, though we will use requests
sys.path.append(os.getcwd())

load_dotenv()

# We need to know the port. run_test_server.py usually runs on 5000 or 5001.
# checking run_test_server.py content would confirm, assuming 5000.
BASE_URL = "http://127.0.0.1:5001"

def get_first_run_id():
    # Try to fetch runs from API to be safe
    try:
        resp = requests.get(f"{BASE_URL}/api/runs") # Assuming this exists or similar
        # If not, try manual_overtake run options route which was:
        # manual_overtake view renders HTML, but we might have a JSON list endpoint?
        # Routes/manual.py has: @main.route("/api/manual_overtake/<int:run_id>/events")
        # But we need a run_id first.
        # Let's try to query DB directly if we know the path, OR just try run_id=1.
        pass
    except Exception:
        pass
    
    # Fallback: check DB directly
    db_path = os.getenv("MAIN_DB_PATH", "ADC.db")
    # If .env variable expansion in code, it might be different.
    # Let's try importing db_manager logic or just guessing 'ADC.db' or 'db/my_app_data.db'
    
    # Actually, simpler: create a dummy run using an API if possible, or just assume run_id=1 exists if the server has data.
    # But "run_test_server.py" might have initialized a test DB.
    
    # Let's try accessing the main page or similar to see if we get a run.
    # Or just use run_id=1 and see if it 404s.
    return 1

def verify_manual_tagging():
    run_id = 1 # heuristic
    
    print(f"Testing with Run ID: {run_id}")
    
    # 1. Create a Manual Overtake Event
    endpoint = f"{BASE_URL}/api/manual_overtake/{run_id}/events"
    payload = {
        "frame_num": 100,
        "overtaker_group_id": 10,
        "overtaken_group_id": 20,
        "notes": "Verification Test Auto-Generated",
        "lane_width_m": 3.5
    }
    
    print(f"Sending POST to {endpoint} with payload: {payload}")
    try:
        resp = requests.post(endpoint, json=payload)
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to server. Is run_test_server.py running?")
        return

    if resp.status_code == 404:
        print("Run ID 1 not found. Trying to find valid run...")
        # Try to find a valid run if 1 failed?
        # Maybe accessing /manual_overtake page html to parse run_ids?
        # Too complex for now.
        pass
    
    print(f"Response Status: {resp.status_code}")
    try:
        print(f"Response Content: {resp.text}")
    except Exception:
        print("Could not print response text")

    if resp.status_code in (200, 201):
        data = resp.json()
        if data.get("database_verified"):
            print("SUCCESS: Event created and verified in DB.")
        else:
            print("WARNING: Event created but DB link not verified in response.")
            
        event_id = data.get("event_id")
        if event_id:
            print(f"Event ID: {event_id}")
            
            # 2. Verify deletion (cleanup)
            delete_endpoint = f"{BASE_URL}/api/manual_overtake/events/{event_id}"
            print(f"Cleaning up... DELETE {delete_endpoint}")
            del_resp = requests.delete(delete_endpoint)
            print(f"Delete Status: {del_resp.status_code}")
            if del_resp.status_code == 200:
                print("Cleanup SUCCESS.")
            else:
                print("Cleanup FAILED.")
    else:
        print("FAILED to create event.")

if __name__ == "__main__":
    verify_manual_tagging()
