import sqlite3

db_path = 'db/my_app_data.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

print('=== ClassMaster contents ===')
cm_data = c.execute('SELECT * FROM ClassMaster').fetchall()
for row in cm_data:
    print(row)

print('\n=== Class contents (first 20) ===')
class_data = c.execute('SELECT * FROM Class LIMIT 20').fetchall()
for row in class_data:
    print(row)

print('\n=== Detection sample with best model ===')
best_data = c.execute('SELECT model_name, class_id FROM Detection WHERE LOWER(model_name) = "best" LIMIT 5').fetchall()
for row in best_data:
    print(row)

print('\n=== Test JOIN with best model ===')
test_query = """
SELECT d.model_name, d.class_id, c.class_name as class_name, cm.class_name as cm_name
FROM Detection d
LEFT JOIN Class c ON d.class_id = c.class_id
LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
WHERE LOWER(d.model_name) = 'best'
LIMIT 5
"""
test_data = c.execute(test_query).fetchall()
for row in test_data:
    print(row)

conn.close()
