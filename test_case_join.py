import sqlite3

db_path = 'db/my_app_data.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

print('=== Test CASE query with class_name JOIN ===')
test_query = """
SELECT d.model_name, d.class_id, c.class_name as c_name, cm.class_name as cm_name,
    CASE 
        WHEN LOWER(d.model_name) = 'best' THEN cm.class_name
        ELSE c.class_name
    END as final_class_name
FROM Detection d
LEFT JOIN Class c ON d.class_id = c.class_id
LEFT JOIN ClassMaster cm ON LOWER(c.class_name) = LOWER(cm.class_name)
WHERE LOWER(d.model_name) = 'best'
LIMIT 10
"""
test_data = c.execute(test_query).fetchall()
print('Model | ClassID | Class.name | ClassMaster.name | Final')
for row in test_data:
    print(f'{row[0]:10} | {row[1]:7} | {str(row[2]):15} | {str(row[3]):20} | {row[4]}')

print('\n=== Test with yolo model ===')
test_query2 = """
SELECT d.model_name, d.class_id, c.class_name as c_name, cm.class_name as cm_name,
    CASE 
        WHEN LOWER(d.model_name) = 'best' THEN cm.class_name
        ELSE c.class_name
    END as final_class_name
FROM Detection d
LEFT JOIN Class c ON d.class_id = c.class_id
LEFT JOIN ClassMaster cm ON LOWER(c.class_name) = LOWER(cm.class_name)
WHERE LOWER(d.model_name) LIKE 'yolo%'
LIMIT 10
"""
test_data2 = c.execute(test_query2).fetchall()
print('Model | ClassID | Class.name | ClassMaster.name | Final')
for row in test_data2:
    print(f'{row[0]:10} | {row[1]:7} | {str(row[2]):15} | {str(row[3]):20} | {row[4]}')

conn.close()
print('\n✓ Test completed')
