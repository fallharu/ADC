with open('templates/detections.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find all script blocks
import re
content = ''.join(lines)
blocks = list(re.finditer(r'<script[^>]*>(.*?)</script>', content, re.DOTALL))

print("=== COMPREHENSIVE BRACE ANALYSIS ===\n")

for idx, match in enumerate(blocks):
    start_line = content[:match.start()].count('\n') + 1
    end_line = content[:match.end()].count('\n') + 1
    script_content = match.group(1)
    
    print(f"Block {idx+1}: Lines {start_line}-{end_line}")
    
    # Detailed brace tracking
    depth = 0
    max_depth = 0
    problem_found = False
    
    for i, char in enumerate(script_content):
        if char == '{':
            depth += 1
            max_depth = max(max_depth, depth)
        elif char == '}':
            depth -= 1
            if depth < 0 and not problem_found:
                line_in_script = script_content[:i].count('\n') + 1
                actual_line = start_line + line_in_script - 1
                # Get surrounding lines
                lines_before = script_content[:i].split('\n')[-5:]
                lines_after = script_content[i:].split('\n')[:5]
                
                print(f"  ERROR: Unmatched closing brace at line {actual_line}")
                print(f"  Context (5 lines before and after):")
                for j, line in enumerate(lines_before[-5:], len(lines_before)-4):
                    print(f"    {actual_line-5+j}: {line}")
                print(f"    >>> {actual_line}: [CLOSING BRACE HERE]")
                for j, line in enumerate(lines_after[:5], 1):
                    print(f"    {actual_line+j}: {line}")
                problem_found = True
                break
    
    open_count = script_content.count('{')
    close_count = script_content.count('}')
    
    print(f"  Open braces: {open_count}")
    print(f"  Close braces: {close_count}")
    print(f"  Max nesting depth: {max_depth}")
    print(f"  Final depth: {depth}")
    
    if depth != 0:
        print(f"  STATUS: ❌ UNBALANCED (diff={depth})")
    else:
        print(f"  STATUS: ✓ Balanced")
    print()
