import sqlite3

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== Check Class vs ClassMaster ===')
tables = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%Class%')").fetchall()
print('Tables:', [t[0] for t in tables])

print('\n=== ClassMaster Data ===')
class_data = c.execute('SELECT * FROM ClassMaster').fetchall()
for row in class_data:
    print(row)

print('\n=== Sample Detection with ClassMaster JOIN ===')
try:
    sample = c.execute('''
        SELECT d.auto_id, d.class_id, cm.class_name, d.track_id, d.group_id
        FROM Detection d 
        LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id 
        WHERE d.run_id = (SELECT MAX(run_id) FROM Detection)
        LIMIT 10
    ''').fetchall()
    for row in sample:
        print(row)
except Exception as e:
    print('Error:', e)

print('\n=== Check all_save.py query ===')
print('all_save.py does NOT join with ClassMaster - only exports column names')

print('\n=== Check summary_csv_export.py query ===')
try:
    cursor = c.execute('''
        SELECT d.class_id, c.class_name
        FROM Detection d
        LEFT JOIN Class c ON d.class_id = c.class_id
        LIMIT 5
    ''')
    print('Using "Class" table:', cursor.fetchall())
except Exception as e:
    print('Error with Class table:', e)

conn.close()
