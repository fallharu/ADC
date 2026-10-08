import os
import re

path = 'Source_code/routes/index.py'
try:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"Read {len(content)} bytes.")

    # Regex to find the import block
    # from ..modules.db_manager import ( ... )
    pattern = re.compile(r'(from \.\.modules\.db_manager import \s*\()(?P<inner>.*?)(\))', re.DOTALL)
    
    match = pattern.search(content)
    if match:
        full_block = match.group(0)
        inner = match.group('inner')
        print("Found import block:")
        print(full_block)
        
        if 'get_all_runs_with_stats' in inner:
            print("Found target string in import block. Removing...")
            # Remove the line containing the string
            new_inner = re.sub(r'\s*get_all_runs_with_stats,?', '', inner)
            # Remove empty lines if any created
            new_inner = re.sub(r'\n\s*\n', '\n', new_inner)
            
            new_block = match.group(1) + new_inner + match.group(3)
            
            new_content = content.replace(full_block, new_block)
            
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print("File updated successfully.")
        else:
            print("Target string 'get_all_runs_with_stats' NOT found in import block.")
    else:
        print("Import block pattern not found.")

except Exception as e:
    print(f"Error: {e}")
