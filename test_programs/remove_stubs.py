with open('Source_code/routes/manual.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Remove lines 527-548 (stub manual_overtake_events_api and manual_overtake_events_status)
# Line numbers are 0-indexed, so 527 is index 526, 548 is index 547
new_lines = lines[:527] + lines[549:]

with open('Source_code/routes/manual.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Removed stub endpoints at lines 527-548. Total lines now: {len(new_lines)}")
