
import sys
import os

# sys.path.append(os.path.abspath("Source_code")) # Not needed if CWD is root

try:
    import Source_code.modules.manual_logic as ml
    print("Import successful")
    
    # Mock event
    event = {
        "overtaker_class_name": "car",
        "overtaker_left_line_distance_m": 1.5,
        "overtaker_right_line_distance_m": 2.5,
        "overtaken_class_name": "bicycle",
        "overtaken_left_line_distance_m": 0.5,
        "overtaken_right_line_distance_m": 0.3,
        "context_frames": []
    }
    
    # Run preparation
    ml._prepare_manual_events([event])
    
    print("--- Enriched Event ---")
    print(f"Overtaker (Car):")
    print(f"  Left (m): {event.get('overtaker_left_line_distance_m')}")
    print(f"  Right (m): {event.get('overtaker_right_line_distance_m')}")
    print(f"  White Dist (m): {event.get('overtaker_white_line_distance_m')} (Should be None for Car)")
    print(f"  Center Dist (m): {event.get('overtaker_center_line_distance_m')} (Should be 1.5)")
    
    print(f"Overtaken (Bike):")
    print(f"  Left (m): {event.get('overtaken_left_line_distance_m')}")
    print(f"  Right (m): {event.get('overtaken_right_line_distance_m')}")
    print(f"  White Dist (m): {event.get('overtaken_white_line_distance_m')} (Should be 0.3)")
    print(f"  Center Dist (m): {event.get('overtaken_center_line_distance_m')} (Should be None)")
    
    # Check if columns exist in EXPORT_COLUMNS
    if "overtaker_white_line_distance_m" in ml.MANUAL_OVERTAKE_EXPORT_COLUMNS:
        print("Columns present in export list: OK")
    else:
        print("Columns MISSING from export list")

except Exception as e:
    print(f"Error: {e}")
