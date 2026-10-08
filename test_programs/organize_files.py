import os
import shutil
import glob

# Define the destination directory
dest_dir = "test_programs"
if not os.path.exists(dest_dir):
    os.makedirs(dest_dir)

# Define patterns to move
patterns = [
    "analyze_*.py",
    "check_*.py",
    "compare_*.py",
    "count_*.py",
    "debug_*.py",
    "diagnose_*.py",
    "dump_*.py",
    "find_*.py",
    "fix_*.py",
    "init_*.py",
    "insert_*.py",
    "inspect_*.py",
    "list_*.py",
    "migrate_*.py",
    "missing_*.py",
    "read_*.py",
    "recreate_*.py",
    "remove_*.py",
    "reproduce_*.py",
    "restore_*.py",
    "temp_*.py",
    "swap_*.py",
    "track_*.py",
    "test_*.py",
    "verify_*.py",
    # Specific ones that look like one-off scripts
    "add_coco_classes.py",
    "copy_class_table.py",
    "detect_calibrated.py", # Looks like a test script for detection
    "generate_cleanup_report.py",
    "repro_import.py",
]

# Patterns to explicitly exclude (just in case they match above, or to be safe)
excludes = [
    "test_programs",
    "organize_files.py",
    "calibration_gui.py",
    "reprocess_csv_cui.py", 
    "export_overtake_pair_cui.py",
    "export_overtake_summary_cui.py", # Keep this too?
    "recalc_distances_cui.py",
    "helper_functions.py",
    "more_helpers.py",
    "test_server.py", # Maybe keep this if it's the main test server? But pattern catches it. It's likely a test script.
]

# Files to keep in root or specific handling
# We are moving python files mostly.

moved_count = 0

for pattern in patterns:
    files = glob.glob(pattern)
    for file_path in files:
        file_name = os.path.basename(file_path)
        
        if file_name in excludes:
            print(f"Skipping excluded file: {file_name}")
            continue
            
        # Double check it's not a directory
        if os.path.isdir(file_path):
            continue
            
        # Move the file
        dest_path = os.path.join(dest_dir, file_name)
        try:
            shutil.move(file_path, dest_path)
            print(f"Moved: {file_name} -> {dest_dir}/")
            moved_count += 1
        except Exception as e:
            print(f"Error moving {file_name}: {e}")

print(f"Finished. Moved {moved_count} files to {dest_dir}.")
