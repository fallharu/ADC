from flask import render_template, request, jsonify, redirect, url_for, flash, current_app
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
