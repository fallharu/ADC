def get_run_ids_by_condition(road_type=None, process_year=None):
    """条件に一致するRun IDのリストを取得する"""
    with get_db_connection() as conn:
        c = conn.cursor()
        query = """
        SELECT p.run_id 
        FROM ProcessLog p
        LEFT JOIN Video v ON p.video_id = v.video_id
        WHERE 1=1
        """
        params = []
        if road_type:
            # road_type が 'undefined' の場合は NULL または空文字を検索
            if road_type == 'undefined':
                 query += " AND (v.road_type IS NULL OR v.road_type = '')"
            elif road_type == 'all':
                 pass # 全ての場合はフィルタしない
            else:
                 query += " AND v.road_type = ?"
                 params.append(road_type)
        
        if process_year:
            if process_year == 'all':
                pass
            else:
                query += " AND v.collection_year = ?"
                params.append(int(process_year))
            
        query += " ORDER BY p.run_id"
        
        rows = c.execute(query, params).fetchall()
        return [r[0] for r in rows]
