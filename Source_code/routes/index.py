from flask import render_template, request, jsonify, redirect, url_for, flash, current_app, send_file, Response
from typing import Optional, Any
import os

from . import main
from .inference import yolo_progress, batch_status
from .post_process import post_process_progress
from ..modules import db_manager as dbm
# Imports removed to avoid Import Error
# Used via dbm.* prefix derived from: from ..modules import db_manager as dbm

from ..modules.manual_logic import _prepare_manual_events
from ..modules.utils import _to_positive_float
from ..modules.folder_utils import _gather_folder_summaries
from flask import current_app

def _get_run_summary():
    runs = dbm.list_detection_runs()
    summary = {
        "total": len(runs),
        "completed": 0,
        "processing": 0,
        "errors": 0,
        "waiting": 0
    }
    for run in runs:
        status = (run.get("status") or "").lower()
        if status == "completed":
            summary["completed"] += 1
        elif status == "processing":
            summary["processing"] += 1
        elif status == "error":
            summary["errors"] += 1
        else:
            summary["waiting"] += 1
    return summary

@main.route("/")
@main.route("/index")
def index():
    """"Main Dashboard"""
    # Simply render index or redirect to detections/manual
    # Based on legacy app, likely index.html
    
    # 1. Run Summary
    run_summary = _get_run_summary()

    # 2. Recent Runs (Limit 5)
    recent_runs_data, _ = dbm.show_recent_detections(page=1, per_page=5)

    # 3. Folder Summaries
    upload_folder = current_app.config['UPLOAD_FOLDER']
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder, exist_ok=True)
        
    # Get available folders from fs
    try:
        available_folders = sorted([
            name for name in os.listdir(upload_folder) 
            if os.path.isdir(os.path.join(upload_folder, name))
        ])
    except OSError:
        available_folders = []

    folder_summaries = _gather_folder_summaries(upload_folder, available_folders)

    return render_template(
        "index.html", 
        title="ADC System",
        run_summary=run_summary,
        recent_runs=recent_runs_data,
        yolo_progress=yolo_progress,
        post_process_progress=post_process_progress,
        batch_status=batch_status,
        folder_summaries=folder_summaries
    )

@main.route("/detections")
def detections():
    try:
        print("DEBUG: Detections route called")
        view_mode = (request.args.get('mode') or 'auto').lower()
        if view_mode not in {'auto', 'manual', 'runs'}:
            view_mode = 'auto'

        run_options = dbm.list_detection_runs()
        
        # Prepare road_types
        db_road_types = dbm.get_all_road_types()
        
        # プリセット定義: value=DB値, label=表示名
        preset_map = {
            "widened": "拡幅",
            "non_widened": "未拡幅"
        }
        
        # 結果リストの構築
        road_types = []
        
        # 1. まずプリセットを追加
        for key, label in preset_map.items():
            road_types.append({"value": key, "label": label})
            
        # 2. DBにあるその他の値をマージ（重複回避）
        preset_keys = set(preset_map.keys())
        preset_labels = set(preset_map.values()) # 日本語ラベル"拡幅"なども既存DB値として入っている可能性があるため
        
        for val in sorted(list(set(db_road_types))):
            # valueがプリセットキーになく、かつ labelがプリセットラベルにもない場合のみ追加
            # これにより "拡幅" (labelにある) が "拡幅" (valueとして追加) されるのを防ぐ
            if val not in preset_keys and val not in preset_labels:
                road_types.append({"value": val, "label": val})

        if view_mode == 'runs':
            # Run螻樊ｧ邱ｨ髮・Δ繝ｼ繝・
            run_list = dbm.get_all_runs_with_stats()
            
            return render_template(
                "detections.html",
                view_mode=view_mode,
                run_list=run_list,
                run_options=run_options,
                detections=[],
                page=1,
                per_page=50,
                total=0,
                total_pages=1,
                selected_run_id=None,
                search_fields=[],
                selected_search_field=None,
                search_values={},
                manual_events=[],
                manual_limit=None,
                road_types=road_types,
            )

        if view_mode == 'manual':
            selected_run_id = request.args.get('run_id', type=int)
            limit_value = request.args.get('limit', type=int)

            if limit_value is None or limit_value <= 0:
                limit_value = 500
            try:
                manual_events = dbm.list_manual_overtake_events(
                    run_id=selected_run_id,
                    limit=limit_value,
                )
                _prepare_manual_events(manual_events)
            except Exception as exc:
                current_app.logger.exception("Failed to load manual overtake events for DB view")
                flash(f"謇句虚霑ｽ縺・ｶ翫＠繧､繝吶Φ繝医・蜿門ｾ励↓螟ｱ謨励＠縺ｾ縺励◆: {exc}", "danger")
                manual_events = []

            empty_search_values = {
                'field': '',
                'text': '',
                'option': '',
                'min': '',
                'max': '',
                'value': '',
            }

            return render_template(
                "detections.html",
                view_mode=view_mode,
                detections=[],
                page=1,
                per_page=limit_value,
                total=len(manual_events),
                total_pages=1,
                run_options=run_options,
                selected_run_id=selected_run_id,
                search_fields=[],
                selected_search_field=None,
                search_values=empty_search_values,
                manual_events=manual_events,
                manual_limit=limit_value,
                road_types=road_types,
            )

        page = max(request.args.get('page', 1, type=int), 1)
        per_page = request.args.get('per_page', 50, type=int)
        per_page = max(10, min(per_page, 20000))
        run_id = request.args.get('run_id', type=int)

        search_field_key = (request.args.get('search_field') or '').strip()
        search_fields = dbm.get_detection_search_fields()
        selected_search_field = next(
            (field for field in search_fields if field['key'] == search_field_key),
            None,
        )

        search_filters: Optional[dict[str, Any]] = None
        search_values: dict[str, Any] = {
            'field': search_field_key,
            'text': request.args.get('search_text', ''),
            'option': request.args.get('search_option', ''),
            'min': request.args.get('search_min', ''),
            'max': request.args.get('search_max', ''),
            'value': request.args.get('search_value', ''),
        }

        if selected_search_field:
            search_filters = {'field': selected_search_field['key']}
            field_type = selected_search_field.get('type', 'text')
            if field_type == 'text':
                keyword = search_values['text'].strip()
                if keyword:
                    search_filters['value'] = keyword
            elif field_type == 'enum':
                option = search_values['option']
                if option:
                    search_filters['value'] = option
            elif field_type == 'presence':
                option = search_values['option'] or search_values['value']
                if option in {'has', 'missing'}:
                    search_filters['value'] = option
            elif field_type == 'number':
                coerce_type = selected_search_field.get('coerce')

                def _convert(raw: str) -> Optional[Any]:
                    if raw in (None, ''):
                        return None
                    try:
                        if coerce_type == 'int':
                            return int(raw)
                        if coerce_type == 'float':
                            return float(raw)
                        return float(raw)
                    except (TypeError, ValueError):
                        return None

                min_value = _convert(search_values['min'])
                max_value = _convert(search_values['max'])
                exact_value = _convert(search_values['value'])
                if min_value is not None:
                    search_filters['min'] = min_value
                if max_value is not None:
                    search_filters['max'] = max_value
                if exact_value is not None and min_value is None and max_value is None:
                    search_filters['value'] = exact_value
        else:
            search_filters = None

        # Extract sort parameters
        sort_by = request.args.get('sort_by', '')
        sort_order = request.args.get('sort_order', 'asc')

        data, total = dbm.show_recent_detections(
            page=page,
            per_page=per_page,
            run_id=run_id,
            search=search_filters,
            sort_by=sort_by if sort_by else None,
            sort_order=sort_order,
        )
        
        # Terminal logging for update tracking
        current_app.logger.info(f"=== 検出結果更新 ===")
        current_app.logger.info(f"取得件数: {len(data)} 件 (全体: {total} 件)")
        current_app.logger.info(f"Run ID: {run_id if run_id else '全て'}")
        current_app.logger.info(f"ページ: {page}/{max((total + per_page - 1) // per_page, 1)}")
        if search_filters:
            current_app.logger.info(f"検索条件: {search_filters}")
        if sort_by:
            current_app.logger.info(f"ソート: {sort_by} ({sort_order})")
        current_app.logger.info(f"==================")
        
        total_pages = max((total + per_page - 1) // per_page, 1)
        if page > total_pages and total > 0:
            return redirect(
                url_for(
                    "main.detections",
                    page=total_pages,
                    run_id=run_id,
                    per_page=per_page,
                    search_field=search_field_key,
                    search_text=search_values['text'],
                    search_option=search_values['option'],
                    search_min=search_values['min'],
                    search_max=search_values['max'],
                    search_value=search_values['value'],
                    sort_by=sort_by,
                    sort_order=sort_order,
                    mode=view_mode,
                )
            )
        return render_template(
            "detections.html",
            view_mode=view_mode,
            detections=data,
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
            run_options=run_options,
            selected_run_id=run_id,
            search_fields=search_fields,
            selected_search_field=selected_search_field,
            search_values=search_values,
            manual_events=[],
            manual_limit=None,
            road_types=road_types,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except Exception as e:
        flash(f"讀懷・邨先棡陦ｨ遉ｺ繧ｨ繝ｩ繝ｼ: {e}", "danger")
        return f"ERROR: {e}", 500


@main.route('/api/batch_update_runs', methods=['POST'])
def batch_update_runs():
    """複数のRunの属性を一括更新"""
    try:
        data = request.get_json()
        run_ids = data.get('run_ids', [])
        collection_year = data.get('collection_year')
        road_type = data.get('road_type')
        
        if not run_ids:
            return jsonify({'success': False, 'error': 'Run ID縺梧欠螳壹＆繧後※縺・∪縺帙ｓ'}), 400
        
        if not collection_year and not road_type:
            return jsonify({'success': False, 'error': '譖ｴ譁ｰ縺吶ｋ蛟､縺梧欠螳壹＆繧後※縺・∪縺帙ｓ'}), 400
        
        # 譁・ｭ怜・  int縺ｫ螟画鋤
        if isinstance(collection_year, str):
            try:
                collection_year = int(collection_year) if collection_year else None
            except ValueError:
                return jsonify({'success': False, 'error': '蜿朱寔蟷ｴ縺ｯ謨ｰ蛟､縺ｧ謖・ｮ壹＠縺ｦ縺上□縺輔＞'}), 400
        
        # db_manager繧剃ｽｿ縺｣縺ｦ譖ｴ譁ｰ
        updated_count = dbm.batch_update_run_attributes(
            run_ids=[int(rid) for rid in run_ids],
            collection_year=collection_year,
            road_type=road_type
        )
        
        return jsonify({'success': True, 'updated': updated_count})
    except Exception as e:
        current_app.logger.exception('Batch update runs failed')
        return jsonify({'success': False, 'error': str(e)}), 500


@main.route('/export_all_detections')
def export_all_detections():
    """Export all detection data as CSV or Excel."""
    import io
    import sqlite3
    import pandas as pd
    from flask import Response
    from datetime import datetime
    
    file_format = request.args.get('format', 'csv').lower()
    filter_type = request.args.get('filter', 'all')
    run_id = request.args.get('run_id', type=int)
    
    try:
        conn = sqlite3.connect(dbm.MAIN_DB_PATH)
        conn.text_factory = lambda b: b.decode("utf-8", "replace") if isinstance(b, (bytes, bytearray)) else b
        
        # Base Query
        if filter_type == 'bicycle_overtake_b':
            query = """
            SELECT 
                d.auto_id as detection_id,
                d.run_id,
                d.frame_num,
                cm.class_name,
                d.confidence,
                d.speed_km_h,
                d.line_distance_m,
                d.ttc_s,
                d.lane_position_flag,
                d.travel_direction,
                d.overtake,
                d.overtake_by,
                d.group_id,
                v.filename as video_name,
                v.collection_year,
                v.road_type,
                CASE 
                    WHEN cm.class_name = 'bicycle' THEN 'Bicycle'
                    WHEN oe.overtaken_auto_id IS NOT NULL THEN 'Overtaken Car'
                    ELSE 'Linked Frame'
                END as target_type
            FROM Detection d
            JOIN ProcessLog p ON d.run_id = p.run_id
            JOIN Video v ON p.video_id = v.video_id
            LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
            LEFT JOIN OvertakeEvents oe ON d.run_id = oe.run_id 
                AND d.frame_num = oe.event_frame_num 
                AND d.auto_id = oe.overtaken_auto_id
            JOIN (
                SELECT DISTINCT d2.run_id, d2.group_id
                FROM Detection d2
                LEFT JOIN ClassMaster cm2 ON d2.class_id = cm2.class_id
                LEFT JOIN OvertakeEvents oe2 ON d2.run_id = oe2.run_id 
                    AND d2.frame_num = oe2.event_frame_num 
                    AND d2.auto_id = oe2.overtaken_auto_id
                WHERE 
                    d2.travel_direction = 'B'
                    AND (
                        (cm2.class_name = 'bicycle') 
                        OR 
                        (oe2.overtaken_auto_id IS NOT NULL)
                    )
                    AND d2.group_id IS NOT NULL
            ) tgt ON d.run_id = tgt.run_id AND d.group_id = tgt.group_id
            """
            order_cols = ["d.run_id", "d.frame_num"]
        else:
            cursor = conn.cursor()

            def _columns(column_names, alias_prefix="", table_alias=""):
                return [
                    f"{table_alias}.{col} AS {alias_prefix}{col}" if alias_prefix or table_alias else col
                    for col in column_names
                ]

            detection_cols = [row[1] for row in cursor.execute("PRAGMA table_info(Detection)")]
            processlog_cols = [row[1] for row in cursor.execute("PRAGMA table_info(ProcessLog)")]
            video_cols = [row[1] for row in cursor.execute("PRAGMA table_info(Video)")]

            class_cols = [row[1] for row in cursor.execute("PRAGMA table_info(ClassMaster)")]
            has_class_master = bool(class_cols)

            select_cols = []
            for col in detection_cols:
                if col == "class_name":
                    continue
                select_cols.append(f"d.{col} AS {col}")
                if col == "class_id":
                    if "class_name" in detection_cols and has_class_master:
                        select_cols.append("COALESCE(NULLIF(d.class_name, ''), cm.class_name) AS class_name")
                    elif "class_name" in detection_cols:
                        select_cols.append("d.class_name AS class_name")
                    elif has_class_master:
                        select_cols.append("cm.class_name AS class_name")

            if "class_id" not in detection_cols:
                if "class_name" in detection_cols:
                    select_cols.append("d.class_name AS class_name")
                elif has_class_master:
                    select_cols.append("cm.class_name AS class_name")

            select_cols.extend(_columns(processlog_cols, alias_prefix="p_", table_alias="p"))
            select_cols.extend(_columns(video_cols, alias_prefix="v_", table_alias="v"))

            query = f"""
            SELECT
                {", ".join(select_cols)}
            FROM Detection d
            JOIN ProcessLog p ON d.run_id = p.run_id
            JOIN Video v ON p.video_id = v.video_id
            { "LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id" if has_class_master else "" }
            WHERE 1=1
            """
            order_cols = ["d.run_id", "d.frame_num"]
            if "auto_id" in detection_cols:
                order_cols.append("d.auto_id")
      
        params = []
        if run_id:
            query += " AND d.run_id = ?"
            params.append(run_id)
            
        query += f" ORDER BY {', '.join(order_cols)}"
      
        df = pd.read_sql_query(query, conn, params=params)
        if filter_type != 'bicycle_overtake_b':
            expected_cols = []
            for col in detection_cols:
                if col == "class_name":
                    continue
                expected_cols.append(col)
                if col == "class_id":
                    if "class_name" in detection_cols or has_class_master:
                        expected_cols.append("class_name")
            if "class_id" not in detection_cols:
                if "class_name" in detection_cols or has_class_master:
                    expected_cols.append("class_name")

            expected_cols.extend([f"p_{col}" for col in processlog_cols])
            expected_cols.extend([f"v_{col}" for col in video_cols])

            missing_cols = [col for col in expected_cols if col not in df.columns]
            for col in missing_cols:
                df[col] = None

            extra_cols = [col for col in df.columns if col not in expected_cols]
            if extra_cols:
                df = df.drop(columns=extra_cols)

            # Decode bytes BEFORE empty check to prevent UnicodeDecodeError
            if not df.empty:
                def _decode_bytes(value):
                    if isinstance(value, memoryview):
                        value = value.tobytes()
                    if isinstance(value, (bytes, bytearray)):
                        return value.decode("utf-8", "replace")
                    return value

                object_cols = df.select_dtypes(include=["object"]).columns
                for col in object_cols:
                    df[col] = df[col].map(_decode_bytes)

            empty_cols = []
            for col in df.columns:
                series = df[col]
                if series.dtype == object:
                    non_null = series.dropna()
                    if non_null.empty:
                        empty_cols.append(col)
                        continue
                    if non_null.astype(str).str.strip().eq("").all():
                        empty_cols.append(col)
                        continue
                else:
                    if not series.notna().any():
                        empty_cols.append(col)

            if empty_cols:
                df = df.drop(columns=empty_cols)

            ordered_cols = [col for col in expected_cols if col in df.columns]
            if ordered_cols:
                df = df[ordered_cols]

            if missing_cols:
                current_app.logger.info("export_all_detections: added_missing_columns=%s", missing_cols)
            if extra_cols:
                current_app.logger.info("export_all_detections: dropped_extra_columns=%s", extra_cols)
            if empty_cols:
                current_app.logger.info("export_all_detections: dropped_empty_columns=%s", empty_cols)

        conn.close()
        
        # Prepare Output directory
        output_dir = os.path.join(current_app.root_path, '..', 'OutPut')
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if run_id:
            base_filename = f"detections_run{run_id}_{timestamp}"
        else:
            base_filename = f"all_detections_{timestamp}"
            
        output = io.BytesIO()
        
        if file_format == 'xlsx':
            # Check for size and split if necessary
            MAX_ROWS = 1000000
            total_rows = len(df)
            
            if total_rows > MAX_ROWS:
                current_app.logger.info(f"Data too large for single Excel file ({total_rows} rows). Splitting by Run ID...")
                import zipfile
                import math
                
                # Get unique runs and their row counts
                run_counts = df['run_id'].value_counts()
                all_runs = run_counts.index.tolist()
                
                # Determine how to split
                # Simple greedy assignment or just chunking. 
                # Let's try to bundle runs until we hit the limit.
                chunks = []
                current_chunk = []
                current_count = 0
                
                for rid in all_runs:
                    count = run_counts[rid]
                    if current_count + count > MAX_ROWS and current_chunk:
                        # Finalize current chunk
                        chunks.append(current_chunk)
                        current_chunk = []
                        current_count = 0
                    
                    current_chunk.append(rid)
                    current_count += count
                    
                if current_chunk:
                    chunks.append(current_chunk)
                    
                current_app.logger.info(f"Split into {len(chunks)} files.")
                
                # Create ZIP output
                zip_output = io.BytesIO()
                with zipfile.ZipFile(zip_output, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for i, chunk_runs in enumerate(chunks):
                        part_num = i + 1
                        part_filename = f"{base_filename}_part{part_num}.xlsx"
                        part_filepath = os.path.join(output_dir, part_filename)
                        
                        # Filter DF
                        chunk_df = df[df['run_id'].isin(chunk_runs)]
                        
                        # Write to Excel in memory first
                        part_excel_io = io.BytesIO()
                        with pd.ExcelWriter(part_excel_io, engine='openpyxl') as writer:
                            chunk_df.to_excel(writer, index=False, sheet_name='Detections')
                        
                        # Save to OutPut
                        with open(part_filepath, 'wb') as f:
                            f.write(part_excel_io.getvalue())
                            
                        # Add to ZIP
                        part_excel_io.seek(0)
                        zf.writestr(part_filename, part_excel_io.getvalue())
                        
                        current_app.logger.info(f"Saved part {part_num}: {part_filepath} ({len(chunk_df)} rows)")
                
                zip_output.seek(0)
                zip_filename = f"{base_filename}.zip"
                zip_filepath = os.path.join(output_dir, zip_filename)
                
                # Save ZIP to OutPut
                with open(zip_filepath, 'wb') as f:
                    f.write(zip_output.getvalue())
                current_app.logger.info(f"Export saved to: {zip_filepath}")
                
                zip_output.seek(0)
                return Response(
                    zip_output.getvalue(),
                    mimetype='application/zip',
                    headers={'Content-Disposition': f'attachment; filename={zip_filename}'}
                )
            else:
                # Normal small enough file
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False)
                
                output.seek(0)
                file_path = os.path.join(output_dir, f"{base_filename}.xlsx")
                with open(file_path, 'wb') as f:
                    f.write(output.getvalue())
                current_app.logger.info(f"Export saved to: {file_path}")
                
                output.seek(0)
                return Response(
                    output.getvalue(),
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f'attachment; filename={base_filename}.xlsx'}
                )
    
        else:
            # CSV
            df.to_csv(output, index=False, encoding='utf-8-sig')
            output.seek(0)
            
            file_path = os.path.join(output_dir, f"{base_filename}.csv")
            with open(file_path, 'wb') as f:
                f.write(output.getvalue())
            current_app.logger.info(f"Export saved to: {file_path}")
            
            output.seek(0)
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename={base_filename}.csv'}
            )
            
    except Exception as e:
        current_app.logger.error(f"Export error: {e}")
        return str(e), 500

@main.route('/export_db')
def export_db():
    """Export the current database file with a safe online backup."""
    import sqlite3
    import shutil
    from datetime import datetime
    from flask import send_file
    
    try:
        # Prepare Output directory
        output_dir = os.path.join(current_app.root_path, '..', 'OutPut')
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"backup_{timestamp}.db"
        backup_filepath = os.path.join(output_dir, backup_filename)
        
        # Connect to existing DB
        src_conn = sqlite3.connect(dbm.MAIN_DB_PATH)
        
        # Create new DB file for backup
        dst_conn = sqlite3.connect(backup_filepath)
        
        # Perform backup
        with dst_conn:
            src_conn.backup(dst_conn)
            
        dst_conn.close()
        src_conn.close()
        
        current_app.logger.info(f"Database backup saved to: {backup_filepath}")
        
        return send_file(
            backup_filepath,
            as_attachment=True,
            download_name=backup_filename,
            mimetype='application/x-sqlite3'
        )
        
    except Exception as e:
        current_app.logger.error(f"DB Export error: {e}")
        return str(e), 500

import cv2
import numpy as np
import io
from flask import Response

@main.route("/detections/preview_image/<int:detection_id>")
def detection_preview_image(detection_id: int):
    # 1. DBから情報を取得
    info = dbm.get_detection_preview_info(detection_id)
    if not info:
        return Response("Detection not found", status=404)
        
    video_path = info.get('source_path')
    print(f"DEBUG: Preview Request ID={detection_id}, Path={video_path}")
    
    if not video_path:
        print("DEBUG: Source path is missing in DB info")
        return Response("Video path not found in DB", status=404)
        
    if not os.path.exists(video_path):
         print(f"DEBUG: File does not exist at path: {video_path}")
         return Response(f"Video file not found: {video_path}", status=404)
         
    # 2. 動画フレームを取得
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"DEBUG: Failed to open video with cv2: {video_path}")
        return Response("Failed to open video", status=500)
        
    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        target_frame = info['frame_num']
        print(f"DEBUG: Video opened. Total frames: {total_frames}, Target frame: {target_frame}")
        
        if target_frame >= total_frames:
             print(f"DEBUG: Target frame {target_frame} is out of bounds (Total: {total_frames})")
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()
        if not ret:
             print(f"DEBUG: Failed to read frame {target_frame}")
             return Response("Failed to read frame", status=500)
    finally:
        cap.release()
        
    # 3. 描画
    # Target (Cyan)
    x1, y1 = int(info['x1']), int(info['y1'])
    x2, y2 = int(info['x2']), int(info['y2'])
    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 0), 2)
    label = f"Target: {info.get('class_name', 'Unknown')}"
    cv2.putText(frame, label, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 2)
    
    # Partner (Yellow) if exists
    if info.get('partner_bbox'):
        p = info['partner_bbox']
        px1, py1 = int(p['x1']), int(p['y1'])
        px2, py2 = int(p['x2']), int(p['y2'])
        cv2.rectangle(frame, (px1, py1), (px2, py2), (0, 255, 255), 2)
        p_label = f"Partner: {p.get('class_name', 'Unknown')}"
        cv2.putText(frame, p_label, (px1, py1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
        
    # Overtake Status
    if info.get('overtake'):
         cv2.putText(frame, "OVERTAKE OCCURRING", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
         
    # 4. エンコードして返却
    ret, buffer = cv2.imencode('.jpg', frame)
    if not ret:
        return Response("Failed to encode image", status=500)
    
    resp = Response(io.BytesIO(buffer.tobytes()), mimetype='image/jpeg')
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@main.route('/export_tracks')
def export_tracks():
    try:
        run_id = request.args.get('run_id', type=int)
        file_format = request.args.get('format', 'xlsx').lower()
        
        # Fetch data
        print(f"DEBUG: Starting full track export. RunID={run_id}, Format={file_format}")
        data = dbm.get_track_data_for_export(run_id)
        
        import pandas as pd
        from datetime import datetime
        
        df_bicycle = data.get('bicycle')
        df_overtake = data.get('overtake')
        
        # Debug logging
        with open('debug_export.log', 'w') as f:
            f.write(f"DEBUG: Starting export for run_id={run_id}, format={file_format}\n")
            
            f.write(f"DEBUG: Bicycle DF type: {type(df_bicycle)}\n")
            if df_bicycle is not None:
                f.write(f"DEBUG: Bicycle DF empty: {df_bicycle.empty}, Shape: {df_bicycle.shape}\n")
            else:
                f.write("DEBUG: Bicycle DF is None\n")
                
            f.write(f"DEBUG: Overtake DF type: {type(df_overtake)}\n")
            if df_overtake is not None:
                f.write(f"DEBUG: Overtake DF empty: {df_overtake.empty}, Shape: {df_overtake.shape}\n")
            else:
                f.write("DEBUG: Overtake DF is None\n")
        
        # Truncate if too large (limit approx 1M rows)
        MAX_ROWS = 1000000
        if df_bicycle is not None and len(df_bicycle) > MAX_ROWS:
            with open('debug_export.log', 'a') as f: f.write(f"WARNING: Bicycle DF truncated from {len(df_bicycle)} to {MAX_ROWS}\n")
            df_bicycle = df_bicycle.iloc[:MAX_ROWS]
            
        if df_overtake is not None and len(df_overtake) > MAX_ROWS:
            with open('debug_export.log', 'a') as f: f.write(f"WARNING: Overtake DF truncated from {len(df_overtake)} to {MAX_ROWS}\n")
            df_overtake = df_overtake.iloc[:MAX_ROWS]
        
        # Get filename provided by user
        user_filename = request.args.get('filename')
        save_server = request.args.get('save_server') == 'true'
        
        output_dir = os.path.join(current_app.root_path, '..', 'OutPut')
        if save_server and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Sanitize filename if provided
        if user_filename:
            import re
            # Remove invalid characters
            safe_filename = re.sub(r'[\\/*?:"<>|]', "", user_filename)
            # Ensure it's not empty and no paths
            safe_filename = os.path.basename(safe_filename)
            if not safe_filename:
                safe_filename = f"track_data_export_{timestamp}"
        else:
            safe_filename = f"track_data_export_{timestamp}"

        if file_format == 'csv':
            # CSV形式：ZIPファイルで2つのCSVを出力
            import zipfile
            
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 自転車シート
                bicycle_csv = io.BytesIO()
                if df_bicycle is not None and not df_bicycle.empty:
                    df_bicycle.to_csv(bicycle_csv, index=False, encoding='utf-8-sig')
                else:
                    pd.DataFrame({'Info': ['データがありません']}).to_csv(bicycle_csv, index=False, encoding='utf-8-sig')
                bicycle_csv.seek(0)
                zf.writestr(f'{safe_filename}_bicycle.csv', bicycle_csv.getvalue())
                
                # 追い越しシート
                overtake_csv = io.BytesIO()
                if df_overtake is not None and not df_overtake.empty:
                    df_overtake.to_csv(overtake_csv, index=False, encoding='utf-8-sig')
                else:
                    pd.DataFrame({'Info': ['データがありません']}).to_csv(overtake_csv, index=False, encoding='utf-8-sig')
                overtake_csv.seek(0)
                zf.writestr(f'{safe_filename}_overtake.csv', overtake_csv.getvalue())
            
            output.seek(0)
            final_filename = f"{safe_filename}.zip"
            
            if save_server:
                server_path = os.path.join(output_dir, final_filename)
                with open(server_path, 'wb') as f:
                    f.write(output.getvalue())
                print(f"DEBUG: Saved export to server: {server_path}")
                # Reset buffer position for response
                output.seek(0)
            
            return Response(
                output.getvalue(),
                mimetype='application/zip',
                headers={'Content-Disposition': f'attachment; filename={final_filename}'}
            )
        else:
            # Excel形式（デフォルト）
            output = io.BytesIO()
            
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Bicycle Sheet
                if df_bicycle is not None and not df_bicycle.empty:
                    print("DEBUG: Writing Bicycle sheet (Data)")
                    df_bicycle.to_excel(writer, sheet_name='自転車', index=False)
                else:
                    print("DEBUG: Writing Bicycle sheet (Empty)")
                    pd.DataFrame({'Info': ['データがありません']}).to_excel(writer, sheet_name='自転車', index=False)

                # Overtake Sheet
                if df_overtake is not None and not df_overtake.empty:
                    print("DEBUG: Writing Overtake sheet (Data)")
                    df_overtake.to_excel(writer, sheet_name='追い越し', index=False)
                else:
                    print("DEBUG: Writing Overtake sheet (Empty)")
                    pd.DataFrame({'Info': ['データがありません']}).to_excel(writer, sheet_name='追い越し', index=False)
                
            output.seek(0)
            
            # Use safe_filename for Excel as well
            final_filename = f"{safe_filename}.xlsx"
            
            if save_server:
                server_path = os.path.join(output_dir, final_filename)
                with open(server_path, 'wb') as f:
                    f.write(output.getvalue())
                print(f"DEBUG: Saved export to server: {server_path}")
                # Reset buffer position for response
                output.seek(0)
            
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=final_filename
            )
    except Exception as e:
        print(f"Export Error: {e}")
        import traceback
        traceback.print_exc()
