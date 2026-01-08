# Fix indentation error by removing the extra helper functions we just added
# They are causing conflicts. Let's just remove them for now to get the server running.

with open('Source_code/routes/manual.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and remove the problematic section (the helpers we just added at line 758)
# Look for the marker we added
start_idx = None
for i, line in enumerate(lines):
    if 'def _float_or_none' in line and i < 900:  # The one we just added
        start_idx = i
        break

if start_idx:
    # Find the end - look for the next function definition that's not indented
    end_idx = start_idx + 1
    while end_idx < len(lines):
        line = lines[end_idx]
        # If we find another top-level definition or the helper functions marker, stop
        if (line.startswith('def ') or 
            line.startswith('# Helper functions for manual scale analysis')):
            break
        end_idx += 1
    
    # Remove the problematic section
    new_lines = lines[:start_idx] + lines[end_idx:]
    
    with open('Source_code/routes/manual.py', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    print(f"Removed lines {start_idx+1} to {end_idx} ({end_idx - start_idx} lines)")
    print(f"Total lines now: {len(new_lines)}")
else:
    print("Could not find the problematic section")
