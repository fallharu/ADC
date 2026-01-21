
import sys
import os

# Add Source_code to path
sys.path.append(os.path.abspath("Source_code"))

try:
    from modules import db_manager as dbm
    print("Import successful")
    
    if hasattr(dbm, 'list_runs_for_manual_tool'):
        print("list_runs_for_manual_tool exists")
    else:
        print("list_runs_for_manual_tool MISSING")
        
    if hasattr(dbm, 'list_manual_overtake_events'):
        print("list_manual_overtake_events exists")
    else:
        print("list_manual_overtake_events MISSING")
    
    if hasattr(dbm, 'MANUAL_OVERTAKE_CONTEXT_COLUMNS'):
        print("MANUAL_OVERTAKE_CONTEXT_COLUMNS exists")
        print(f"Columns count: {len(dbm.MANUAL_OVERTAKE_CONTEXT_COLUMNS)}")
    else:
        print("MANUAL_OVERTAKE_CONTEXT_COLUMNS MISSING")

except Exception as e:
    print(f"Error: {e}")
