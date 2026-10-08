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
    
    # Detailed brace analysis
    open_braces = []
    close_braces = []
    depth = 0
    
    for pos, char in enumerate(script_content):
        if char == '{':
            depth += 1
            open_braces.append((pos, depth))
        elif char == '}':
            close_braces.append((pos, depth))
            depth -= 1
            if depth < 0:
                line_in_script = script_content[:pos].count('\n') + 1
                print(f"  ERROR: Unmatched closing brace at script line {line_in_script} (template line {start_line + line_in_script})")
                print(f"  Context: ...{script_content[max(0,pos-50):pos+50]}...")
                break
    
    print(f"  Open braces: {len(open_braces)}, Close braces: {len(close_braces)}, Final depth: {depth}")
    
    if depth != 0:
        print(f"  WARNING: Unbalanced! Missing {abs(depth)} {'closing' if depth > 0 else 'opening'} brace(s)")
        # Show where imbalance might be
        if depth > 0:
            # Too many opens, show last few opens
            print(f"  Last 3 opening braces at positions: {[pos for pos, d in open_braces[-3:]]}")
        else:
            # Too many closes
            print(f"  Last 3 closing braces at positions: {[pos for pos, d in close_braces[-3:]]}")
    
    print()
