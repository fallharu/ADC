import sqlite3

db_path = r'C:\Users\kurok\Downloads\G_ADC\ADC_08\db\profiles\default\my_app_data.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get actual schema directly from SQLite
print("=== ACTUAL DATABASE SCHEMA ===\n")

cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='Video';")
video_schema = cursor.fetchone()
if video_schema:
    print("Video table:")
    print(video_schema[0])
    print()

cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='Detection';")
det_schema = cursor.fetchone()
if det_schema:
    print("Detection table:")
    print(det_schema[0][:500])  # First 500 chars
    print()

cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='Overtake';")
ov_schema = cursor.fetchone()
if ov_schema:
    print("Overtake table:")
    print(ov_schema[0][:500])
    print()

# Get some stats
print("\n=== DATA STATISTICS ===\n")

# Videos
cursor.execute("SELECT COUNT(*) FROM Video;")
print(f"Total Videos: {cursor.fetchone()[0]}")

# Detections by class
cursor.execute("""
    SELECT c.class_name, COUNT(*) as cnt
    FROM Detection d
    JOIN Class c ON d.class_id = c.class_id
    GROUP BY c.class_name
    ORDER BY cnt DESC
    LIMIT 10;
""")
print("\nDetections by class:")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]}")

# Overtake stats
cursor.execute("SELECT COUNT(*) FROM Overtake;")
ov_count = cursor.fetchone()[0]
print(f"\nTotal Overtakes: {ov_count}")

if ov_count > 0:
    cursor.execute("""
        SELECT 
            AVG(clearance_distance_cm),
            AVG(overtaker_speed_kmh)
        FROM Overtake
        WHERE clearance_distance_cm IS NOT NULL;
    """)
    stats = cursor.fetchone()
    if stats[0]:
        print(f"Average Clearance: {stats[0]:.1f} cm")
    if stats[1]:
        print(f"Average Speed: {stats[1]:.1f} km/h")

conn.close()
