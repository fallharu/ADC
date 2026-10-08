import sqlite3

db_path = 'db/my_app_data.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print('=== Test with Class Table ===')

# Get a test run_id
run_id_result = cursor.execute('SELECT run_id FROM ProcessLog ORDER BY run_id DESC LIMIT 1').fetchone()
if not run_id_result:
    print('No runs found in database')
    exit()

run_id = run_id_result[0]
print(f'Testing with run_id: {run_id}')

# Test the modified query using Class table
test_query = """
SELECT d.auto_id, d.frame_num, d.class_id, c.class_name, d.track_id, d.group_id
FROM Detection d
LEFT JOIN Class c ON d.class_id = c.class_id
WHERE d.run_id = ?
ORDER BY d.frame_num, d.auto_id
LIMIT 20
"""

print('\n=== Query Results ===')
results = cursor.execute(test_query, (run_id,)).fetchall()
print(f'Found {len(results)} rows')

for row in results:
    print(f'auto_id: {row[0]}, frame: {row[1]}, class_id: {row[2]}, class_name: {row[3]}, track_id: {row[4]}, group_id: {row[5]}')

# Check if any class_name is NULL
null_class_names = [r for r in results if r[3] is None]
if null_class_names:
    print(f'\n⚠️ WARNING: {len(null_class_names)} rows still have NULL class_name')
    for row in null_class_names[:10]:
        print(f'  auto_id: {row[0]}, class_id: {row[2]}, class_name: {row[3]}')
else:
    print('\n✓ All rows have valid class_name')

# Show unique classes in the sample
unique_classes = set(r[3] for r in results if r[3] is not None)
print(f'\n=== Unique classes found: {unique_classes} ===')

conn.close()
print('\n✓ Test completed - Class table should work correctly')
