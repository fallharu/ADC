import sys
import os
import json
import logging

# Check current directory
print(f"Current Working Directory: {os.getcwd()}")
sys.path.append(os.getcwd())

from Source_code.app import app
from Source_code.modules.manual_logic import _compute_manual_overtake_event_data, ManualOvertakeComputationError

# Configure logger to print to stderr
logging.basicConfig(level=logging.DEBUG)

with app.app_context():
    try:
        print("Running manual overtake computation...")
        
        result = _compute_manual_overtake_event_data(
            run_id=100160,
            frame_num=1000,
            overtaker_group_id=86,
            overtaken_group_id=44,
            compute_lane_metrics=True,
            group_presence_context=True,
        )
        print("--- Computation Result ---")
        # Ensure UTF-8 output
        payload_str = json.dumps(result.payload, indent=2, default=str, ensure_ascii=False)
        # Use sys.stdout.buffer to write utf-8 bytes directly to avoid encoding issues
        sys.stdout.buffer.write(payload_str.encode('utf-8'))
        sys.stdout.buffer.write(b"\n")
        
        if result.notices:
            print("--- Notices ---")
            for n in result.notices:
                print(n)
        
        # Check computed values specifically
        print("\n--- Specific Checks ---")
        p = result.payload
        print(f"Clearance Distance: {p.get('clearance_distance_m')}")
        print(f"Overtaker Line Dist: {p.get('overtaker_line_distance_m')}")
        print(f"Overtaken Line Dist: {p.get('overtaken_line_distance_m')}")

    except ManualOvertakeComputationError as e:
        print(f"Computation Error: {e}")
    except Exception as e:
        print(f"Unexpected Error: {e}")
        import traceback
        with open('error_trace.txt', 'w') as f:
            traceback.print_exc(file=f)
        traceback.print_exc()
