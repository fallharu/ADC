import sqlite3

db_path = 'db/my_app_data.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print('=== Test Modified Query ===')

# Get a test run_id
run_id_result = cursor.execute('SELECT run_id FROM ProcessLog ORDER BY run_id DESC LIMIT 1').fetchone()
if not run_id_result:
    print('No runs found in database')
    exit()

run_id = run_id_result[0]
print(f'Testing with run_id: {run_id}')

# Test the modified query (simplified version)
test_query = """
SELECT d.auto_id, d.frame_num, d.class_id, cm.class_name, d.track_id, d.group_id
FROM Detection d
LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
WHERE d.run_id = ?
ORDER BY d.frame_num, d.auto_id
LIMIT 10
"""

print('\n=== Query Results ===')
results = cursor.execute(test_query, (run_id,)).fetchall()
print(f'Found {len(results)} rows')

for row in results:
    print(f'auto_id: {row[0]}, frame: {row[1]}, class_id: {row[2]}, class_name: {row[3]}, track_id: {row[4]}, group_id: {row[5]}')

# Check if any class_name is NULL
null_class_names = [r for r in results if r[3] is None]
if null_class_names:
    print(f'\n⚠️ WARNING: {len(null_class_names)} rows have NULL class_name')
    for row in null_class_names[:5]:
        print(f'  auto_id: {row[0]}, class_id: {row[2]}, class_name: {row[3]}')
    
    # Check what class_ids are missing from ClassMaster
    missing_class_ids = set(r[2] for r in null_class_names)
    print(f'\n=== Missing class_ids in ClassMaster: {missing_class_ids} ===')
    
    for class_id in missing_class_ids:
        # Check if it exists in Class table instead
        class_result = cursor.execute('SELECT class_name FROM Class WHERE class_id = ?', (class_id,)).fetchone()
        if class_result:
            print(f'class_id {class_id} found in Class table as: {class_result[0]}')
        else:
            print(f'class_id {class_id} not found in Class or ClassMaster tables')
else:
    print('\n✓ All rows have valid class_name')

conn.close()
