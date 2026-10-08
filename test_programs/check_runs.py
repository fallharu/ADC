from Source_code.app import app
from Source_code.modules import db_manager

with app.app_context():
    runs = db_manager.list_detection_runs()
    print(f"Found {len(runs)} runs.")
    for r in runs:
        print(r)
