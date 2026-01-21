import re

with open('templates/detections.html', 'r', encoding='utf-8') as f:
    content = f.read()
    lines = content.split('\n')

# Find all script blocks
script_pattern = r'<script[^>]*>(.*?)</script>'
scripts = list(re.finditer(script_pattern, content, re.DOTALL))

print(f"Found {len(scripts)} script blocks\n")

for i, match in enumerate(scripts):
    start_line = content[:match.start()].count('\n') + 1
    end_line = content[:match.end()].count('\n') + 1
    script_content = match.group(1)
    
    print(f"Script Block {i+1}: Lines {start_line}-{end_line}")
    
    # Check for brace balance
    open_braces = script_content.count('{')
    close_braces = script_content.count('}')
    
    if open_braces != close_braces:
        print(f"  WARNING: Unbalanced braces! {{ = {open_braces}, }} = {close_braces}")
    else:
        print(f"  Braces balanced: {open_braces} pairs")
    
    # Check for common issues
    if 'initializeTableSort' in script_content:
        print(f"  WARNING: Found initializeTableSort (should be removed)")
    if 'getCellValue' in script_content:
        print(f"  WARNING: Found getCellValue (should be removed)")
    if 'sortTableMulti' in script_content:
        print(f"  WARNING: Found sortTableMulti (should be removed)")
    
    print()

print("\nChecking for duplicate function definitions...")
functions_found = {}
for i, match in enumerate(scripts):
    script_content = match.group(1)
    func_pattern = r'function\s+(\w+)\s*\('
    for func_match in re.finditer(func_pattern, script_content):
        func_name = func_match.group(1)
        if func_name in functions_found:
            print(f"DUPLICATE: {func_name} found in blocks {functions_found[func_name]} and {i+1}")
        else:
            functions_found[func_name] = i+1
