
import sqlite3
import os

DB_PATH = os.path.join("db", "my_app_data.db")

def check_data():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check ProcessLog content
    cursor.execute("SELECT COUNT(*) FROM ProcessLog")
    count = cursor.fetchone()[0]
    print(f"ProcessLog count: {count}")

    # Check distinct folder aliases
    cursor.execute("SELECT DISTINCT folder_alias FROM ProcessLog")
    aliases = cursor.fetchall()
    print("Folder Aliases:")
    for row in aliases:
        print(f" - '{row['folder_alias']}'")

    # Pick one alias and check runs
    target_alias = None
    for row in aliases:
        if row['folder_alias']:
            target_alias = row['folder_alias']
            break
            
    if target_alias:
        print(f"\nChecking runs for alias: '{target_alias}'")
        cursor.execute("SELECT run_id, video_id, folder_alias FROM ProcessLog WHERE folder_alias = ?", (target_alias,))
        runs = cursor.fetchall()
        for run in runs:
            print(f" Run ID: {run['run_id']}, Video ID: {run['video_id']}")
            # Check video existence
            cursor.execute("SELECT * FROM Video WHERE video_id = ?", (run['video_id'],))
            video = cursor.fetchone()
            if video:
                print(f"  -> Video Found: {video['filename']}")
                # Check columns existence in row
                print(f"  -> Video Keys: {video.keys()}")
            else:
                print(f"  -> Video NOT Found for ID {run['video_id']}")
    else:
        print("No folder alias found.")

    conn.close()

if __name__ == "__main__":
    check_data()
