# Find and remove ALL duplicate route definitions
import re

with open('Source_code/routes/manual.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find all function definitions
func_defs = {}
for i, line in enumerate(lines):
    match = re.match(r'^def\s+(\w+)\s*\(', line)
    if match:
        func_name = match.group(1)
        if func_name not in func_defs:
            func_defs[func_name] = []
        func_defs[func_name].append(i)

# Find duplicates
duplicates = {name: indices for name, indices in func_defs.items() if len(indices) > 1}

print(f"Found {len(duplicates)} functions with duplicates:")
for name, indices in sorted(duplicates.items()):
    print(f"  {name}: lines {[i+1 for i in indices]}")

# For now, let's just remove the stub manual_overtake_scale_preview_image if it exists
# Keep the one from routes_legacy (should be later in the file)
if 'manual_overtake_scale_preview_image' in duplicates:
    indices = duplicates['manual_overtake_scale_preview_image']
    # Remove the first occurrence (stub)
    lines_to_remove = [indices[0]]
    print(f"\nRemoving stub manual_overtake_scale_preview_image at line {indices[0]+1}")
else:
    lines_to_remove = []

# Actually remove them (go backwards so indices stay valid)
for idx in sorted(lines_to_remove, reverse=True):
    # Find the end of this function (next function def or end of file)
    end_idx = idx + 1
    while end_idx < len(lines) and not lines[end_idx].startswith('def ') and not lines[end_idx].startswith('@'):
        end_idx += 1
    print(f"Removing lines {idx+1} to {end_idx}")
    del lines[idx:end_idx]

with open('Source_code/routes/manual.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"\nTotal lines now: {len(lines)}")
