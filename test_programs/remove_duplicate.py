with open('Source_code/routes/manual.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Remove duplicate endpoints: manual_overtake_events_status (lines 550-566)
# Keep only the version from routes_legacy.py (later in the file)
new_lines = lines[:549] + lines[567:]

with open('Source_code/routes/manual.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Removed duplicate manual_overtake_events_status. Total lines: {len(new_lines)}")
