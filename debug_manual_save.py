import requests
import json

url = "http://127.0.0.1:5001/api/manual_overtake/100160/events"
data = {
    "run_id": 100160,
    "frame_num": 1000,
    "overtaker_group_id": 86,
    "overtaken_group_id": 44,
    "notes": "Debug API Call via script v2"
}

try:
    response = requests.post(url, json=data)
    with open('debug_result.json', 'w', encoding='utf-8') as f:
        json.dump(response.json(), f, indent=2, ensure_ascii=False)
    print("Saved to debug_result.json")
except Exception as e:
    print(f"Request failed: {e}")
