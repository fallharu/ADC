import sys
import os

# Add Source_code to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'Source_code'))

try:
    from modules import db_manager as dbm
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def inspect_overtake_flags():
    try:
        with dbm.get_db_connection() as conn:
            c = conn.cursor()
            
            print("--- Overtake Flag Stats ---")
            
            total = c.execute("SELECT count(*) FROM Detection").fetchone()[0]
            ot_1 = c.execute("SELECT count(*) FROM Detection WHERE overtake = 1").fetchone()[0]
            ot_by_1 = c.execute("SELECT count(*) FROM Detection WHERE overtake_by = 1").fetchone()[0]
            any_ot = c.execute("SELECT count(*) FROM Detection WHERE overtake = 1 OR overtake_by = 1").fetchone()[0]
            
            print(f"Total Detections: {total}")
            print(f"overtake = 1: {ot_1}")
            print(f"overtake_by = 1: {ot_by_1}")
            print(f"Any Overtake Flag: {any_ot}")
            
            if any_ot > 0:
                print("\n--- Sample Overtake Rows ---")
                rows = c.execute("""
                    SELECT run_id, frame_num, track_id, overtake, overtake_by 
                    FROM Detection 
                    WHERE overtake = 1 OR overtake_by = 1 
                    LIMIT 20
                """).fetchall()
                for r in rows:
                    print(dict(r))
                    
                # Check consistency with OvertakeEvents
                print("\n--- Checking Consistency with OvertakeEvents ---")
                # Get one event
                event = c.execute("SELECT * FROM OvertakeEvents LIMIT 1").fetchone()
                if event:
                    run_id = event['run_id']
                    frame = event['event_frame_num']
                    ot_grp = event['overtaker_group_id']
                    od_grp = event['overtaken_group_id']
                    
                    print(f"Event: Run {run_id}, Frame {frame}, Overtaker {ot_grp}, Overtaken {od_grp}")
                    
                    # Check Detection for this exact frame and groups
                    dets = c.execute("""
                        SELECT run_id, frame_num, group_id, overtake, overtake_by 
                        FROM Detection 
                        WHERE run_id=? AND frame_num=? AND group_id IN (?, ?)
                    """, (run_id, frame, ot_grp, od_grp)).fetchall()
                    for d in dets:
                        print(f"Matching Detection: {dict(d)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    # Redirect stdout to a file for better reading
    with open('inspect_overtake_flags_output.txt', 'w', encoding='utf-8') as f:
        original_stdout = sys.stdout
        sys.stdout = f
        inspect_overtake_flags()
        sys.stdout = original_stdout
        print("Done. Check inspect_overtake_flags_output.txt")
