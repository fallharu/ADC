import os

path = 'Source_code/modules/db_manager.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace \"\"\" with """
# Also check for single \" if present, but triple is the main issue
new_content = content.replace('\\"\\"\\"', '"""')
# Just in case it was \"
new_content = new_content.replace('\\"', '"')

with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Fixed syntax in db_manager.py")
