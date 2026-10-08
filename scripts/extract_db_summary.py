import sqlite3
import os

# プロファイルのデータベースを確認
db_path = r'C:\Users\kurok\Downloads\G_ADC\ADC_08\db\profiles\default\my_app_data.db'

if not os.path.exists(db_path):
    print(f"Database not found: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("=== DATABASE SUMMARY ===\n")

# Video files
cursor.execute("SELECT COUNT(*) FROM video_files;")
video_count = cursor.fetchone()[0]
print(f"Total videos: {video_count}")

# Detections by class
print("\n=== DETECTIONS BY CLASS ===")
cursor.execute("""
    SELECT class_name, COUNT(*) as count 
    FROM detections 
    GROUP BY class_name
    ORDER BY count DESC;
""")
for row in cursor.fetchall():
    print(f"{row[0]}: {row[1]}")

# Bicycle count (class='bicycle')
cursor.execute("SELECT COUNT(DISTINCT track_id) FROM detections WHERE class_name='bicycle';")
bicycle_tracks = cursor.fetchone()[0]
print(f"\nUnique bicycle tracks: {bicycle_tracks}")

# Overtakes statistics
print("\n=== OVERTAKES STATISTICS ===")
cursor.execute("SELECT COUNT(*) FROM overtakes;")
overtake_count = cursor.fetchone()[0]
print(f"Total overtakes: {overtake_count}")

if overtake_count > 0:
    # Average clearance distance
    cursor.execute("""
        SELECT 
            AVG(clearance_distance) as avg_lc,
            MIN(clearance_distance) as min_lc,
            MAX(clearance_distance) as max_lc,
            AVG(overtake_speed) as avg_speed
        FROM overtakes 
        WHERE clearance_distance IS NOT NULL;
    """)
    stats = cursor.fetchone()
    print(f"Average LC: {stats[0]:.1f} cm")
    print(f"Min LC: {stats[1]:.1f} cm")
    print(f"Max LC: {stats[2]:.1f} cm")
    print(f"Average Speed: {stats[3]:.1f} km/h")
    
    # Overtakes by location/video
    print("\n=== OVERTAKES BY VIDEO ===")
    cursor.execute("""
        SELECT vf.filename, COUNT(o.id) as overtake_count
        FROM overtakes o
        JOIN video_files vf ON o.video_id = vf.id
        GROUP BY vf.filename
        ORDER BY overtake_count DESC;
    """)
    for row in cursor.fetchall():
        print(f"{row[0]}: {row[1]} overtakes")

conn.close()
