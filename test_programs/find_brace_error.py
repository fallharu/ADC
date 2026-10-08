with open('templates/detections.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Script block 1: lines 692-887 (0-indexed: 691-886)
script_lines = lines[691:887]
script_text = ''.join(script_lines)

depth = 0
for i, char in enumerate(script_text):
    if char == '{':
        depth += 1
    elif char == '}':
        depth -= 1
        if depth < 0:
            # Find line number
            line_in_script = script_text[:i].count('\n')
            actual_line = 692 + line_in_script
            context_start = max(0, i - 100)
            context_end = min(len(script_text), i + 100)
            print(f"PROBLEM: Unmatched closing brace at line {actual_line}")
            print(f"Context:\n...{script_text[context_start:context_end]}...")
            break

if depth != 0:
    print(f"\nFinal brace depth: {depth}")
    if depth < 0:
        print(f"Too many closing braces: {abs(depth)}")
    else:
        print(f"Too many opening braces: {depth}")
else:
    print("All braces balanced!")
