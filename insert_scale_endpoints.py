with open('Source_code/routes/manual.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('missing_scale_endpoints.py', 'r', encoding='utf-8') as f:
    scale_endpoints = f.read()

# Insert the scale preview endpoints before manual_overtake_metadata (around line 815)
# Find the line with "def manual_overtake_metadata"
for i, line in enumerate(lines):
    if 'def manual_overtake_metadata' in line:
        insert_pos = i
        print(f"Found manual_overtake_metadata at line {i+1}")
        break
else:
    print("manual_overtake_metadata not found!")
    insert_pos = 815

# Insert the scale endpoints
lines.insert(insert_pos, '\n' + scale_endpoints + '\n')

with open('Source_code/routes/manual.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"Inserted scale preview endpoints at line {insert_pos+1}")
print(f"Total lines now: {len(lines)}")
