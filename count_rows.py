import sys
import os

# Add Source_code to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'Source_code'))

try:
    from modules import db_manager as dbm
except ImportError as e:
    print(f"Import Error: {e}")
    # Try different structure if running from root
    sys.path.append(os.path.join(current_dir, 'Source_code', 'modules'))
    try:
        import db_manager as dbm
    except ImportError as e2:
        print(f"Import Error 2: {e2}")
        sys.exit(1)

def count():
    try:
        with dbm.get_db_connection() as conn:
            c = conn.cursor()
            
            # List tables to be sure
            tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            
            n_det = c.execute("SELECT count(*) FROM Detection").fetchone()[0]
            n_evt = c.execute("SELECT count(*) FROM OvertakeEvents").fetchone()[0]
            
            n_det_clr = c.execute("SELECT count(*) FROM Detection WHERE clearance_distance_m IS NOT NULL").fetchone()[0]
            n_evt_clr = c.execute("SELECT count(*) FROM OvertakeEvents WHERE clearance_distance_m IS NOT NULL").fetchone()[0]
            
            output = f"""
Tables: {[t[0] for t in tables]}
Detection Total: {n_det}
Detection with Clearance: {n_det_clr}
OvertakeEvents Total: {n_evt}
OvertakeEvents with Clearance: {n_evt_clr}
"""
            print(output)
            with open('count_output.txt', 'w', encoding='utf-8') as f:
                f.write(output)
            
    except Exception as e:
        print(f"Error: {e}")
        with open('count_output.txt', 'w', encoding='utf-8') as f:
            f.write(f"Error: {e}")

if __name__ == '__main__':
    count()
