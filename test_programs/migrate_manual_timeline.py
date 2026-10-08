import sqlite3
import os

DB_PATH = r"c:\Users\kurok\Downloads\G_ADC\ADC_08\db\my_app_data.db"

def migrate_db():
    if not os.path.exists(DB_PATH):
        print(f"DB not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("Migrating ManualOvertakeTimeline...")
    try:
        # Check if column exists
        c.execute("PRAGMA table_info(ManualOvertakeTimeline)")
        rows = c.fetchall()
        column_names = [row[1] for row in rows]
        
        if 'manual_event_id' not in column_names:
            print("Adding manual_event_id column...")
            c.execute("ALTER TABLE ManualOvertakeTimeline ADD COLUMN manual_event_id INTEGER")
            conn.commit()
            print("Column added successfully.")
        else:
            print("Column manual_event_id already exists.")
            
    except Exception as e:
        print(f"Migration failed: {e}")

    conn.close()

if __name__ == "__main__":
    migrate_db()
