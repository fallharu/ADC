with open('Source_code/routes/manual.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find all occurrences of "def manual_overtake_events_api"
import re
matches = list(re.finditer(r'^def manual_overtake_events_api', content, re.MULTILINE))
print(f"Found {len(matches)} occurrences of 'def manual_overtake_events_api'")
for i, match in enumerate(matches):
    line_num = content[:match.start()].count('\n') + 1
    print(f"  Occurrence {i+1} at line {line_num}")

# If there are 2, we need to keep only the second one (from routes_legacy)
# For now, just identify the line numbers
