with open('templates/detections.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Focus on the handleBatchUpdate function area (lines 1463-1520)
start_line = 1462  # 0-indexed
end_line = 1521
function_lines = lines[start_line:end_line]
function_text = ''.join(function_lines)

print("=== Analyzing handleBatchUpdate function ===")
print(f"Lines {start_line+1}-{end_line}")
print(f"\nFirst 10 lines:")
for i, line in enumerate(function_lines[:10], start_line+1):
    print(f"{i}: {line.rstrip()}")

print(f"\nLast 10 lines:")
for i,line in enumerate(function_lines[-10:], end_line-9):
    print(f"{i}: {line.rstrip()}")

# Count braces
open_braces = function_text.count('{')
close_braces = function_text.count('}')
open_parens = function_text.count('(')
close_parens = function_text.count(')')

print(f"\nBrace count:")
print(f"  {{ : {open_braces}")
print(f"  }} : {close_braces}")
print(f"  Difference: {open_braces - close_braces}")

print(f"\nParenthesis count:")
print(f"  ( : {open_parens}")
print(f"  ) : {close_parens}")
print(f"  Difference: {open_parens - close_parens}")
