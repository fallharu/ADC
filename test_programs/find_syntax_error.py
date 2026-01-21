import ast
import sys

try:
    with open('Source_code/routes/manual.py', 'r', encoding='utf-8') as f:
        code = f.read()
    ast.parse(code)
    print("No syntax errors found!")
except SyntaxError as e:
    print(f"Syntax Error:")
    print(f"  File: {e.filename}")
    print(f"  Line: {e.lineno}")
    print(f"  Offset: {e.offset}")
    print(f"  Text: {e.text}")
    print(f"  Message: {e.msg}")
    sys.exit(1)
