import sqlite3
import os

DB_PATH = r"C:\Users\kurok\Downloads\G_ADC\ADC_08\old\my_app_data.db"
REPORT_PATH = "db_inspection_report.txt"

def inspect_db():
    if not os.path.exists(DB_PATH):
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write(f"DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        try:
            f.write("--- Table Counts ---\n")
            tables = ["Video", "ProcessLog", "OvertakeEvents", "ManualOvertakeEvents", "Detection"]
            for t in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {t}")
                    count = cursor.fetchone()[0]
                    f.write(f"{t}: {count}\n")
                except Exception as e:
                    f.write(f"{t}: Error - {e}\n")

            f.write("\n--- OvertakeEvents Linkage Check ---\n")
            query_linked = """
            SELECT COUNT(*) 
            FROM OvertakeEvents e
            JOIN ProcessLog p ON e.run_id = p.run_id
            JOIN Video v ON p.video_id = v.video_id
            """
            cursor.execute(query_linked)
            linked_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM OvertakeEvents")
            total_events = cursor.fetchone()[0]
            
            f.write(f"Total OvertakeEvents: {total_events}\n")
            f.write(f"Linked OvertakeEvents (Joined with ProcessLog & Video): {linked_count}\n")
            f.write(f"Unlinked/Orphaned Events: {total_events - linked_count}\n")

            f.write("\n--- Video Metadata Check (All Videos) ---\n")
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN road_type IS NULL THEN 1 ELSE 0 END) as null_road,
                    SUM(CASE WHEN collection_year IS NULL THEN 1 ELSE 0 END) as null_year
                FROM Video
            """)
            v_res = cursor.fetchone()
            f.write(f"Total Videos: {v_res['total']}\n")
            f.write(f"  Road Type NULL: {v_res['null_road']}\n")
            f.write(f"  Collection Year NULL: {v_res['null_year']}\n")

            f.write("\n--- Null Field Analysis (Linked Events) ---\n")
            query_nulls = """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN v.road_type IS NULL THEN 1 ELSE 0 END) as null_road,
                SUM(CASE WHEN v.collection_year IS NULL THEN 1 ELSE 0 END) as null_year
            FROM OvertakeEvents e
            JOIN ProcessLog p ON e.run_id = p.run_id
            JOIN Video v ON p.video_id = v.video_id
            """
            cursor.execute(query_nulls)
            res = cursor.fetchone()
            f.write(f"Linked Events: {res['total']}\n")
            f.write(f"  Road Type NULL: {res['null_road']}\n")
            f.write(f"  Collection Year NULL: {res['null_year']}\n")
            
            if res['null_road'] > 0 or res['null_year'] > 0:
                f.write("\n--- Sample Missing Attributes ---\n")
                cursor.execute("""
                    SELECT v.video_id, v.filename, v.road_type, v.collection_year, COUNT(e.overtake_event_id) as event_count
                    FROM OvertakeEvents e
                    JOIN ProcessLog p ON e.run_id = p.run_id
                    JOIN Video v ON p.video_id = v.video_id
                    WHERE v.road_type IS NULL OR v.collection_year IS NULL
                    GROUP BY v.video_id
                    LIMIT 10
                """)
                for row in cursor.fetchall():
                    f.write(f"{dict(row)}\n")

        finally:
            conn.close()

if __name__ == "__main__":
    inspect_db()
