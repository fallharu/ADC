import sqlite3
import os

output_lines = []

def out(s=""):
    output_lines.append(s)

def dump_schema(db_path, label):
    out(f"\n{'='*60}")
    out(f"{label}: {db_path}")
    out(f"Size: {os.path.getsize(db_path) / 1024:.1f} KB")
    out('='*60)
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Get all tables
    c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = c.fetchall()
    
    out(f"\n--- テーブル一覧 ({len(tables)} tables) ---")
    for name, sql in tables:
        if name.startswith('sqlite_'):
            continue
        # Count rows
        try:
            c.execute(f'SELECT COUNT(*) FROM "{name}"')
            count = c.fetchone()[0]
        except:
            count = "?"
        out(f"\n### {name} ({count} rows)")
        
        # Get columns
        c.execute(f'PRAGMA table_info("{name}")')
        cols = c.fetchall()
        for col in cols:
            cid, col_name, col_type, notnull, default, pk = col
            pk_mark = " [PK]" if pk else ""
            out(f"    {col_name}: {col_type}{pk_mark}")
    
    # Get views
    c.execute("SELECT name, sql FROM sqlite_master WHERE type='view'")
    views = c.fetchall()
    if views:
        out(f"\n--- ビュー ({len(views)} views) ---")
        for name, sql in views:
            out(f"  {name}")
    
    conn.close()

# Current DB
dump_schema('db/my_app_data.db', '現在のDB')

# Backup DB
dump_schema('db/my_app_data.db.backup_20260117_102900', 'バックアップDB')

# Save to file
with open('schema_output.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_lines))
print("Saved to schema_output.txt")
