import sqlite3

db_path = 'db/my_app_data.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

print('=== Best model class_ids in Detection table ===')
result = c.execute('SELECT DISTINCT class_id FROM Detection WHERE LOWER(model_name) = "best" ORDER BY class_id').fetchall()
class_ids = [r[0] for r in result]
print(f'Unique class_ids: {class_ids}')

print('\n=== Sample data ===')
sample = c.execute('SELECT model_name, class_id FROM Detection WHERE LOWER(model_name) = "best" LIMIT 10').fetchall()
for row in sample:
    print(f'model: {row[0]}, class_id: {row[1]} (type: {type(row[1])})')

conn.close()
