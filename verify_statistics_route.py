import sys
import os

# Adjust path to import Source_code
sys.path.append(os.path.join(os.getcwd(), "."))

from Source_code.app import app
from Source_code.modules.db_manager import list_detection_runs

# app = create_app() 
client = app.test_client()

with open("verify_result.txt", "w", encoding="utf-8") as f:
    print("Testing GET /statistics...", file=f)
    try:
        resp = client.get("/statistics")
        print(f"Status Code: {resp.status_code}", file=f)
        content = resp.data.decode('utf-8')
        
        # Check key phrases
        if "集計対象となるRunがまだ登録されていません" in content:
            # Check if we actually have runs
            runs = list_detection_runs()
            if not runs:
                print("INFO: 'No Run registered' message found, but DB has no runs, so this is expected.", file=f)
            else:
                print("FAILED: 'No Run registered' message found, despite having runs in DB.", file=f)
        else:
            print("SUCCESS: 'No Run registered' message NOT found.", file=f)
            if '<select id="stats_run_ids"' in content:
                print("SUCCESS: Run selection list found.", file=f)

        # Test POST if runs exist
        runs = list_detection_runs()
        if runs:
            run_id = runs[0]['run_id']
            print(f"Testing POST /statistics with run_id={run_id}...", file=f)
            resp = client.post("/statistics", data={
                "stats_run_ids": [str(run_id)],
                "stats_mode": "lane"
            })
            print(f"Status Code: {resp.status_code}", file=f)
            content = resp.data.decode('utf-8')
            if "集計概要" in content:
                    print("SUCCESS: Preview section found.", file=f)
            else:
                    print("FAILED: Preview section NOT found.", file=f)
        else:
            print("SKIPPING POST TEST: No runs found in DB.", file=f)

    except Exception as e:
        import traceback
        traceback.print_exc(file=f)
