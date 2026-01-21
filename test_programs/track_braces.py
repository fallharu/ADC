with open('templates/detections.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

start_line = 1462
end_line = 1522
function_lines = lines[start_line:end_line]

print("=== Line-by-line brace tracking ===\n")

depth = 0
for i, line in enumerate(function_lines, start_line+1):
    stripped = line.strip()
    
    # Count braces in this line
    open_in_line = line.count('{')
    close_in_line = line.count('}')
    
    depth_before = depth
    depth += open_in_line - close_in_line
   
    if open_in_line > 0 or close_in_line > 0:
        print(f"{i:4}: depth {depth_before:2} -> {depth:2}  ({'+' if open_in_line > 0 else ''}{open_in_line if open_in_line > 0 else ''}{'-' if close_in_line > 0 else ''}{close_in_line if close_in_line > 0 else ''})  {stripped[:80]}")
    
    if depth < 0:
        print(f"\n*** ERROR: Depth went negative at line {i} ***")
        break

print(f"\nFinal depth: {depth}")
if depth != 0:
    print(f"Missing {depth} opening brace(s)" if depth < 0 else f"Missing {depth} closing brace(s)")
