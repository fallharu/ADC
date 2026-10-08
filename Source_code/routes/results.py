from flask import Blueprint, render_template, current_app
import sqlite3
import pandas as pd
from ..modules.db_manager import MAIN_DB_PATH, get_db_connection

results_bp = Blueprint('results', __name__)

def get_latest_results():
    """
    Get the latest 'completed' run statistics for each video.
    Returns:
        list of dicts: Per-video statistics (filename, road_type, run_id, auto_count, manual_count, total)
        dict: Summary by road_type
    """
    sql = """
    SELECT
        v.video_id,
        v.filename,
        v.road_type,
        p.run_id,
        p.process_end,
        (SELECT COUNT(*) FROM OvertakeEvents o WHERE o.run_id = p.run_id) as auto_count,
        (SELECT COUNT(*) FROM ManualOvertakeEvents m WHERE m.run_id = p.run_id) as manual_count
    FROM Video v
    JOIN ProcessLog p ON v.video_id = p.video_id
    WHERE p.status = 'completed'
    AND p.run_id = (
        SELECT MAX(p2.run_id)
        FROM ProcessLog p2
        WHERE p2.video_id = v.video_id AND p2.status = 'completed'
    )
    ORDER BY v.filename ASC
    """
    
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql).fetchall()
            
            results = []
            road_type_summary = {}
            
            for row in rows:
                r = dict(row)
                r['total'] = r['auto_count'] + r['manual_count']
                
                # Road Type Summary
                rt = r['road_type'] or '未設定'
                if rt not in road_type_summary:
                    road_type_summary[rt] = {'video_count': 0, 'auto_sum': 0, 'manual_sum': 0, 'total_sum': 0}
                
                road_type_summary[rt]['video_count'] += 1
                road_type_summary[rt]['auto_sum'] += r['auto_count']
                road_type_summary[rt]['manual_sum'] += r['manual_count']
                road_type_summary[rt]['total_sum'] += r['total']
                
                results.append(r)
                
            return results, road_type_summary
            
    except Exception as e:
        current_app.logger.error(f"Error fetching results: {e}")
        return [], {}

@results_bp.route('/result_view')
def result_view():
    video_results, summary = get_latest_results()
    
    # Sort summary by road_type for consistent display
    sorted_summary = dict(sorted(summary.items()))
    
    return render_template('result_view.html', 
                         results=video_results, 
                         summary=sorted_summary)
