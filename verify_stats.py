
import sys
import os
import json
from Source_code.app import app

def verify_stats_api():
    print("Starting verification of Global Stats API...")
    
    with app.test_client() as client:
        response = client.get('/api/global_stats')
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.get_json()
            print("Response Data:")
            print(json.dumps(data, indent=2))
            
            if "error" in data:
                print("FAILURE: API returned error message.")
            else:
                print("SUCCESS: Stats API verified.")
        else:
            print("FAILURE: API Request failed.")
            print(response.data.decode('utf-8'))

if __name__ == "__main__":
    verify_stats_api()
