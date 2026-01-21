import os
import ast
import hashlib
import sys

TARGET_DIR = r"c:\Users\kurok\Downloads\G_ADC\ADC_08\Source_code"

defined_functions = {}  # name -> list of (file, lineno)
calls = set()
function_bodies = {} # hash -> list of (file, lineno, name)
syntax_errors = []

def get_function_body_hash(node):
    # ast.dump with include_attributes=False (default) avoids line numbers
    return hashlib.md5(ast.dump(node).encode('utf-8')).hexdigest()

class CallVisitor(ast.NodeVisitor):
    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            calls.add(node.func.attr)
        self.generic_visit(node)

class DefVisitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename

    def visit_FunctionDef(self, node):
        name = node.name
        if name not in defined_functions:
            defined_functions[name] = []
        defined_functions[name].append((self.filename, node.lineno))
        
        h = get_function_body_hash(node)
        if h not in function_bodies:
            function_bodies[h] = []
        function_bodies[h].append((self.filename, node.lineno, name))
        
        self.generic_visit(node)
        
    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)

def analyze_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(filepath, 'r', encoding='cp932') as f:
                content = f.read()
        except Exception as e:
            # print(f"Skipping {filepath} due to encoding error: {e}")
            return

    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError as e:
        syntax_errors.append((filepath, e.lineno, str(e)))
        return

    DefVisitor(filepath).visit(tree)
    CallVisitor().visit(tree)

def main():
    with open('codebase_report.txt', 'w', encoding='utf-8') as report_file:
        def log(msg):
            print(msg)
            report_file.write(msg + "\n")

        if not os.path.exists(TARGET_DIR):
            log(f"Directory not found: {TARGET_DIR}")
            return

        for root, dirs, files in os.walk(TARGET_DIR):
            for file in files:
                if file.endswith(".py"):
                    analyze_file(os.path.join(root, file))

        log("=== SYNTAX ERRORS ===")
        if not syntax_errors:
            log("None")
        for file, line, msg in syntax_errors:
            log(f"{file}:{line} - {msg}")

        log("\n=== DUPLICATED FUNCTIONS ===")
        duplicates_found = False
        for h, entries in function_bodies.items():
            if len(entries) > 1:
                log(f"Duplicate body found ({len(entries)} occurrences):")
                for file, line, name in entries:
                    log(f"  - {name} at {file}:{line}")
                duplicates_found = True
        if not duplicates_found:
            log("None")

        log("\n=== POTENTIALLY UNUSED FUNCTIONS ===")
        unused = []
        for name, locations in defined_functions.items():
            if name not in calls and not name.startswith("__"):
                # Exclude likely framework hooks or entry points if obvious?
                # For now listing all as requested
                for file, line in locations:
                    unused.append((name, file, line))
        
        if unused:
            # Sort by file then line
            unused.sort(key=lambda x: (x[1], x[2]))
            for name, file, line in unused:
                 log(f"{name} at {file}:{line}")
        else:
            log("None")

if __name__ == "__main__":
    main()
