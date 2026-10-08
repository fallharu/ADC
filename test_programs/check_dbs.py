import sqlite3

# 現在のDB
print('=== 現在のDB (my_app_data.db) ===')
conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print(f'Tables: {tables}')
for t in tables[:8]:
    try:
        c.execute(f'SELECT COUNT(*) FROM "{t}"')
        print(f'  {t}: {c.fetchone()[0]} rows')
    except:
        pass
conn.close()

# バックアップDB  
print()
print('=== バックアップDB (backup_20260117_102900) ===')
conn2 = sqlite3.connect('db/my_app_data.db.backup_20260117_102900')
c2 = conn2.cursor()
c2.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables2 = [r[0] for r in c2.fetchall()]
print(f'Tables: {tables2}')
for t in tables2[:8]:
    try:
        c2.execute(f'SELECT COUNT(*) FROM "{t}"')
        print(f'  {t}: {c2.fetchone()[0]} rows')
    except:
        pass
conn2.close()
