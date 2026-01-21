
import pandas as pd
import sqlite3
import json
import os
import sys
import numpy as np
import math
from datetime import datetime

# モジュールを見つけるためにパスを調整
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'Source_code'))

from modules.db_manager import MAIN_DB_PATH
from modules.calibration_loader import load_calibration_json


def resolve_overrides_path() -> str:
    config_path = os.path.join(current_dir, "gui_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f) or {}
            data_dir = config.get("data_dir")
            if data_dir:
                return os.path.join(data_dir, "video_calibration_overrides.json")
        except Exception:
            pass
    return os.path.join(current_dir, "video_calibration_overrides.json")


def resolve_output_root() -> str:
    config_path = os.path.join(current_dir, "gui_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f) or {}
            data_dir = config.get("data_dir")
            if data_dir:
                return data_dir
        except Exception:
            pass
    return os.path.join(current_dir, "uploads")


def should_pause(args):
    if "--no-pause" in args:
        return False
    return "--pause" in args

def get_line_x(y, line_def):
    """
    指定されたyにおける線のx座標を計算します。
    line_defの形式:
      - [[x1, y1], [x2, y2]] (単純な線)
      - [[[x1,y1],[x2,y2]], [[x3,y3],[x4,y4]], ...] (分割された線)
    yが範囲外または線が無効な場合はNoneを返します。
    """
    if not line_def:
        return None
    
    # 分割された線（3次元配列）かどうかを確認
    is_segmented = False
    if isinstance(line_def[0][0], list):
        is_segmented = True
    elif isinstance(line_def, list) and len(line_def) > 2:
        # ポリライン -> セグメントに変換
        line_def = polyline_to_segments(line_def)
        is_segmented = True

    if not is_segmented:
        # 単純な線のロジック
        (x1, y1), (x2, y2) = line_def
        if y1 == y2: return None # 水平
        
        # 外挿するか？ 単純な線は概念的に画像全体をカバーすると仮定するか、
        # 単に方程式を許可する。
        # 線形補間: x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        return x1 + (y - y1) * (x2 - x1) / (y2 - y1)
    else:
        # 分割線のロジック
        # yをカバーするセグメントを見つける
        # セグメントをYでソートするか？ 通常は順序付けられている。
        # yがy_startとy_endの間にあるセグメントを見つける
        for seg in line_def:
            (sx1, sy1), (sx2, sy2) = seg
            min_y, max_y = min(sy1, sy2), max(sy1, sy2)
            if min_y <= y <= max_y:
                 if sy1 == sy2: continue
                 return sx1 + (y - sy1) * (sx2 - sx1) / (sy2 - sy1)
        
        # 見つからない場合、最も近いものを見つけるか？ またはNoneを返す。
        return None

def resolve_status(cross_val, dist_val, expected_cross_label, inside_label):
    # cross_valが存在し、かつ0より大きい場合は「越え」
    if cross_val is not None and cross_val > 0:
        return expected_cross_label
    
    # dist_val > 0 -> 内側
    if dist_val is not None and dist_val >= 0:
        return inside_label
        
    return '-'

def polyline_to_segments(points):
    """[x,y]点のリストを[[x1,y1],[x2,y2]]セグメントのリストに変換します。"""
    segments = []
    if not points or len(points) < 2:
        return segments
    for i in range(len(points) - 1):
        segments.append([points[i], points[i+1]])
    return segments

def calc_white_metrics(cx, y, left_line_def, scale):
    if not left_line_def:
        return None, None, "-"
    left_x = get_line_x(y, left_line_def)
    if left_x is None:
        return None, None, "-"
    dist_m = (cx - left_x) * scale
    if dist_m < 0:
        return None, abs(dist_m), "白線越え"
    return dist_m, 0.0, "白線内側"

def calc_center_metrics(x_left, y, center_line_def, scale):
    if x_left is None or not center_line_def:
        return None, "-"
    center_x = get_line_x(y, center_line_def)
    if center_x is None:
        return None, "-"
    dist_m = (x_left - center_x) * scale
    if dist_m < 0:
        return abs(dist_m), "中央線越え"
    return 0.0, "中央線内側"

def pick_line(lines_raw, keys):
    if not isinstance(lines_raw, dict):
        return None
    lookup = {str(k).lower(): k for k in lines_raw.keys()}
    for key in keys:
        k_low = str(key).lower()
        if k_low in lookup:
            return lines_raw[lookup[k_low]]
    return None

def is_vehicle(cls_name):
    if not cls_name:
        return False
    return str(cls_name).lower() in {"car", "truck", "bus", "van"}

def is_bicycle(cls_name):
    if not cls_name:
        return False
    return str(cls_name).lower() in {"bicycle"}

def is_motorbike(cls_name):
    if not cls_name:
        return False
    return str(cls_name).lower() in {"motorcycle", "motorbike", "bike"}

def two_wheeler_type(cls_name):
    if is_bicycle(cls_name):
        return "自転車"
    if is_motorbike(cls_name):
        return "バイク"
    return None

def get_profile_from_db(run_id):
    """DBからRunに紐づくキャリブレーションプロファイル名を取得する"""
    if not os.path.exists(MAIN_DB_PATH):
        return None
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT calibration_profile FROM ProcessLog WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]
    except Exception as e:
        print(f"DB Lookup Failed for Run {run_id}: {e}")
    return None

def main():
    input_csv_path = os.path.join(current_dir, '前回データ処理.csv') 
    if not os.path.exists(input_csv_path):
        print(f"Error: Input file not found at {input_csv_path}")
        return

    print(f"Reading CSV: {input_csv_path}")
    df = pd.read_csv(input_csv_path)

    output_rows = []
    
    # ライン指標のヘルパー
    def calculate_line_metrics(vx1, vx2, vy2, direction, lines_segments, scale):
             # 最も近い線を見つける
            valid_xs = []
            
            # 解析されたlines_segmentsを使用
            for seg_list in lines_segments:
                lx = get_line_x(vy2, seg_list)
                if lx is not None: valid_xs.append(lx)

            # 'lane_marks'が存在する場合もチェック（古い形式？）
            if 'lane_marks' in calib:
                 # セグメントと仮定
                 for lm in calib['lane_marks']:
                      lx = get_line_x(vy2, lm) # lmがセグメントの場合
                      if lx is not None: valid_xs.append(lx)
            
            valid_xs = sorted(list(set(valid_xs)))
            
            if not valid_xs:
                return None, None, None, None, '-', '-'
            
            vcx = (vx1 + vx2)/2
            
            left_candidates = [x for x in valid_xs if x < vcx]
            right_candidates = [x for x in valid_xs if x > vcx]
            
            screen_l_x = max(left_candidates) if left_candidates else None
            screen_r_x = min(right_candidates) if right_candidates else None
            
            s_l_dist_m = (vx1 - screen_l_x) * scale if screen_l_x is not None else None
            s_r_dist_m = (screen_r_x - vx2) * scale if screen_r_x is not None else None
            
            is_fwd = (direction == 'F')
            
            if is_fwd:
                white_dist = s_l_dist_m
                center_dist = s_r_dist_m
            else: 
                center_dist = s_l_dist_m
                white_dist = s_r_dist_m
            
            def get_cross_val(dist):
                if dist is None: return None
                return abs(dist) if dist < 0 else None
                
            odc_c = get_cross_val(center_dist)
            odw_c = get_cross_val(white_dist)
            
            od_c_stat = resolve_status(odc_c, center_dist, '中央線越え', '中央線内側')
            od_w_stat = resolve_status(odw_c, white_dist, '白線越え', '白線内側')
            
            return center_dist, white_dist, odc_c, odw_c, od_c_stat, od_w_stat

    # Run/Videoでグループ化
    video_groups = df.groupby(['Run', '動画名'])
    
    # キャリブレーションキャッシュをプリロード (Run ID -> Calibration Data)
    # Run IDに基づいてロードします
    video_cache = {} # filename -> {calib: {}, path: opt_path}

    print(f"Processing {len(video_groups)} video groups...")
    
    # --- モード選択 ---
    mode_input = None
    args = sys.argv[1:]
    for arg in args:
        if arg in ("1", "2", "3"):
            mode_input = arg
            break
    if mode_input:
        print(f"Mode provided via CLI: {mode_input}")
    else:
        print("\nSelect Output Mode:")
        print("1. Overtake Flag Only (追い越し・追い越されフラグのみ)")
        print("2. All Rows (すべてを出力)")
        print("3. All Rows for Overtake Groups (追い越し・追い越されグループ全ての行)")
        mode_input = input("Enter mode (1/2/3) [Default: 1]: ").strip()
        
    pause_on_exit = should_pause(args)

    if mode_input == '2':
        output_mode = 'ALL'
    elif mode_input == '3':
        output_mode = 'GROUP'
    else:
        output_mode = 'FLAG'
        
    print(f"Selected Mode: {output_mode}")

    output_root = resolve_output_root()
    print(f"出力先フォルダ: {output_root}")
    exported_csv_paths = []

    for (run_val, video_filename), group in video_groups:
        # キャッシュを確認
        if video_filename not in video_cache:
            # Run IDをパース
            try:
                run_id = int(run_val)
            except:
                run_id = None
            
            # キャリブレーションをロード
            calib_data = None
            path = None
            
            # --- 0. 上書き（動画ごと）を試行 ---
            override_profile = None
            overrides_path = resolve_overrides_path()
            if os.path.exists(overrides_path):
                try:
                    with open(overrides_path, 'r', encoding='utf-8') as f:
                        overrides = json.load(f)
                        override_profile = overrides.get(video_filename)
                except Exception as e:
                    print(f"Error loading overrides: {e}")

            if override_profile:
                 print(f"Video '{video_filename}': Using Override Profile '{override_profile}'")
                 try:
                     calib_data, path = load_calibration_json(run_id, override_profile)
                 except Exception:
                     print(f"Override profile '{override_profile}' not found, falling back...")
            
            # --- 1. DBプロファイルを試行（上書きがない場合、または失敗した場合） ---
            if not calib_data and run_id:
                # 1. まずDBプロファイルを試行
                profile_name = get_profile_from_db(run_id)
                if profile_name:
                    print(f"Run {run_id}: Using DB Profile '{profile_name}'")
                
                try:
                    calib_data, path = load_calibration_json(run_id, profile_name)
                except Exception as e:
                    # 特定のプロファイルが失敗した場合、None（自動検索 calibration_XX.json）にフォールバック
                    if profile_name:
                        print(f"Run {run_id}: Profile '{profile_name}' not found, trying default...")
                        try:
                            calib_data, path = load_calibration_json(run_id, None)
                        except:
                            path = None
                    else:
                        path = None
            
            # まだNoneの場合は、run_idに基づいてデフォルトを試行（まだ試していない場合）
            if not calib_data and run_id and not path:
                 try:
                      calib_data, path = load_calibration_json(run_id, None)
                 except:
                      pass

            # --- 3. 日付マッチング（フォールバック）を試行 ---
            if not calib_data:
                # 日付抽出ヘルパー
                def extract_date(text):
                    match8 = re.search(r'(20[0-9]{2})(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])', text)
                    if match8: return match8.group(0), 'YYYYMMDD'
                    match6 = re.search(r'(2[3-9]|[3-9][0-9])(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])', text)
                    if match6: return match6.group(0), 'YYMMDD'
                    return None, None
                
                v_date, v_fmt = extract_date(video_filename)
                if v_date:
                    target_tags = {v_date}
                    if v_fmt == 'YYMMDD': target_tags.add("20" + v_date)
                    elif v_fmt == 'YYYYMMDD': target_tags.add(v_date[2:])
                    
                    # output/calibrations内のキャリブレーションファイルを検索
                    calib_dir = os.path.join(current_dir, 'output', 'calibrations')
                    if os.path.exists(calib_dir):
                        c_files = glob.glob(os.path.join(calib_dir, "*.json"))
                        for cf in c_files:
                            c_name = os.path.splitext(os.path.basename(cf))[0]
                            for tag in target_tags:
                                if tag in c_name:
                                    print(f"Video '{video_filename}': Using Date-Matched Profile '{c_name}'")
                                    try:
                                        with open(cf, 'r', encoding='utf-8') as f:
                                            calib_data = json.load(f)
                                        path = cf
                                    except: pass
                                    break
                            if calib_data: break

            # キャッシュに保存
            video_cache[video_filename] = {
                'calib': calib_data if calib_data else {},
                'path': path if 'path' in locals() and path else None
            }
            
        cache = video_cache[video_filename]
        calib = cache['calib'] or {}
        
        # スケールの処理
        raw_scale = calib.get('scale', 0.005)
        if isinstance(raw_scale, dict):
            scale = raw_scale.get('m_per_px', 0.005)
        else:
            scale = raw_scale
            
        # ラインの処理（セグメントに変換）
        lines_segments = []
        raw_lines = calib.get('lines', {})
        if raw_lines:
            if isinstance(raw_lines, dict):
                for poly in raw_lines.values():
                    lines_segments.append(polyline_to_segments(poly))
            elif isinstance(raw_lines, list):
                # ラインのリストの場合
                for poly in raw_lines:
                    lines_segments.append(polyline_to_segments(poly))

        center_line_def = pick_line(raw_lines, ["center_line", "center", "中央線"])
        left_white_line_def = pick_line(raw_lines, ["left_white_line", "left_white", "left_line", "左白線", "left white line"])
        
        calib_path = cache.get('path', None)
        calib_filename_only = os.path.basename(calib_path) if calib_path else "なし"

        # このグループのすべての行を処理
        for idx, row in group.iterrows():

            overtaker_group = row['追い越し側Group']
            overtaker_x1 = row['追い越し側BBOX x1']
            overtaker_y1 = row['追い越し側BBOX y1']
            overtaker_x2 = row['追い越し側BBOX x2']
            overtaker_y2 = row['追い越し側BBOX y2']
            overtaker_class = row['追い越し側クラス']

            overtaken_group = row['追い越され側Group']
            overtaken_x1 = row['追い越され側BBOX x1']
            overtaken_y1 = row['追い越され側BBOX y1']
            overtaken_x2 = row['追い越され側BBOX x2']
            overtaken_y2 = row['追い越され側BBOX y2']
            overtaken_class = row['追い越され側クラス']
            
            frame_num = row['動画フレーム']
            
            # DBから方向を取得
            t_direction = 'F' # デフォルト
            run_id = None
            try:
                run_id = int(row['Run'])
            except:
                pass

            if run_id:
                try:
                    with sqlite3.connect(MAIN_DB_PATH) as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT travel_direction FROM Detection 
                            WHERE run_id=? AND frame_num=? AND group_id=?
                            LIMIT 1
                        """, (run_id, frame_num, overtaker_group))
                        d_res = cursor.fetchone()
                        if d_res and d_res[0]:
                            t_direction = d_res[0]
                except Exception:
                    pass
            
            # --- 2. 距離の再計算 ---
            
            p1_cx = (overtaker_x1 + overtaker_x2) / 2
            p2_cx = (overtaken_x1 + overtaken_x2) / 2
            
            p1_vx = p1_cx
            p1_vy = overtaker_y2 # 距離のための下部中央
            p2_vx = p2_cx
            p2_vy = overtaken_y2

            # 側面ごとのレーン距離（カスタムルール）
            ot_white_dist, ot_white_cross, ot_white_stat = calc_white_metrics(
                p1_cx, overtaker_y2, left_white_line_def, scale
            )
            ov_white_dist, ov_white_cross, ov_white_stat = calc_white_metrics(
                p2_cx, overtaken_y2, left_white_line_def, scale
            )

            ot_center_cross, ot_center_stat = (None, "-")
            ov_center_cross, ov_center_stat = (None, "-")
            if is_vehicle(overtaker_class):
                ot_center_cross, ot_center_stat = calc_center_metrics(
                    overtaker_x1, overtaker_y2, center_line_def, scale
                )
            if is_vehicle(overtaken_class):
                ov_center_cross, ov_center_stat = calc_center_metrics(
                    overtaken_x1, overtaken_y2, center_line_def, scale
                )

            # 離隔距離（車両の左下から自転車の下部中央）
            vehicle_x = None
            vehicle_y = None
            bike_x = None
            bike_y = None
            if is_vehicle(overtaker_class):
                vehicle_x = overtaker_x1
                vehicle_y = overtaker_y2
            elif is_vehicle(overtaken_class):
                vehicle_x = overtaken_x1
                vehicle_y = overtaken_y2

            if is_bicycle(overtaker_class) or is_motorbike(overtaker_class):
                bike_x = (overtaker_x1 + overtaker_x2) / 2
                bike_y = overtaker_y2
            elif is_bicycle(overtaken_class) or is_motorbike(overtaken_class):
                bike_x = (overtaken_x1 + overtaken_x2) / 2
                bike_y = overtaken_y2

            if vehicle_x is not None and bike_x is not None:
                clearance_m = math.hypot(bike_x - vehicle_x, bike_y - vehicle_y) * scale
            else:
                clearance_px = abs(p1_cx - p2_cx)
                clearance_m = clearance_px * scale
            
            # 行の更新
            new_row = row.copy()
            new_row['離隔距離(m)'] = round(clearance_m, 2)
            new_row['離隔距離(cm)'] = round(clearance_m * 100, 1)
            
            # 追い越し側のライン
            new_row['追い越し側 白線距離(m)'] = round(ot_white_dist, 2) if ot_white_dist is not None else None
            new_row['追い越し側 白線越え(m)'] = round(ot_white_cross, 2) if ot_white_cross is not None else None
            new_row['追い越し側 白線越え'] = ot_white_stat
            new_row['追い越し側 中央線越え(m)'] = round(ot_center_cross, 2) if ot_center_cross is not None else None
            new_row['追い越し側 中央線越え'] = ot_center_stat

            new_row['追い越され側 白線距離(m)'] = round(ov_white_dist, 2) if ov_white_dist is not None else None
            new_row['追い越され側 白線越え(m)'] = round(ov_white_cross, 2) if ov_white_cross is not None else None
            new_row['追い越され側 白線越え'] = ov_white_stat
            new_row['追い越され側 中央線越え(m)'] = round(ov_center_cross, 2) if ov_center_cross is not None else None
            new_row['追い越され側 中央線越え'] = ov_center_stat
            
            new_row['キャリブレーションファイル'] = calib_filename_only
            
            output_rows.append(new_row)

    # DataFrame作成
    final_df = pd.DataFrame(output_rows)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # --- 4. 単一CSVの保存 ---
    filtered_df = final_df
    if output_mode == 'FLAG':
        if 'オフセットフレーム' in final_df.columns:
            filtered_df = final_df[final_df['オフセットフレーム'] == 0]
        elif '追い越しフラグ' in final_df.columns:
            filtered_df = final_df[final_df['追い越しフラグ'] == 1]
    elif output_mode == 'GROUP':
        if 'オフセットフレーム' in final_df.columns:
            relevant_df = final_df[final_df['オフセットフレーム'] == 0]
        elif '追い越しフラグ' in final_df.columns:
            relevant_df = final_df[final_df['追い越しフラグ'] == 1]
        else:
            relevant_df = final_df.iloc[0:0]
        relevant_groups = set()
        if not relevant_df.empty:
            relevant_groups.update(relevant_df['追い越し側Group'].dropna().unique())
            relevant_groups.update(relevant_df['追い越され側Group'].dropna().unique())
        if relevant_groups:
            cond = final_df['追い越し側Group'].isin(relevant_groups) | final_df['追い越され側Group'].isin(relevant_groups)
            filtered_df = final_df[cond]
        else:
            filtered_df = final_df.iloc[0:0]

    if filtered_df.empty:
        print(f"Skip (empty after filter): mode={output_mode}, rows={len(final_df)}")
    else:
        if 'オフセットフレーム' in filtered_df.columns:
            overtake_flag = (filtered_df['オフセットフレーム'] == 0).astype(int)
        elif '追い越しフラグ' in filtered_df.columns:
            overtake_flag = (filtered_df['追い越しフラグ'] == 1).astype(int)
        else:
            overtake_flag = pd.Series([0] * len(filtered_df), index=filtered_df.index)

        if '接近距離(m)' in filtered_df.columns:
            approach_dist = filtered_df['接近距離(m)']
        else:
            approach_dist = filtered_df.get('離隔距離(m)')

        output_rows = []
        for _, row in filtered_df.iterrows():
            run_id = row.get('Run')
            video_name = row.get('動画名', row.get('動画ファイル'))
            frame = row.get('動画フレーム')
            overtaker_class = row.get('追い越し側クラス')
            overtaken_class = row.get('追い越され側クラス')

            if row.get('オフセットフレーム') == 0:
                overtake_flag = 1
            elif row.get('追い越しフラグ') == 1:
                overtake_flag = 1
            else:
                overtake_flag = 0

            approach_dist = row.get('接近距離(m)', row.get('離隔距離(m)'))

            def add_row(self_side, other_side):
                output_rows.append({
                    'Run ID': run_id,
                    '動画ファイル': video_name,
                    'フレーム': frame,
                    '自グループID': row.get(f'{self_side}Group'),
                    '自クラス': row.get(f'{self_side}クラス'),
                    '相手グループID': row.get(f'{other_side}Group'),
                    '離隔距離(m)': row.get('離隔距離(m)'),
                    '離隔距離(cm)': row.get('離隔距離(cm)'),
                    '接近距離(m)': approach_dist,
                    '追い越しフラグ': overtake_flag,
                    '白線距離(m)': row.get(f'{self_side} 白線距離(m)'),
                    '中央線越え(m)': row.get(f'{self_side} 中央線越え(m)'),
                    '白線越え(m)': row.get(f'{self_side} 白線越え(m)'),
                    '中央線越え': row.get(f'{self_side} 中央線越え'),
                    '白線越え': row.get(f'{self_side} 白線越え'),
                })

            bike_side = None
            motor_side = None
            vehicle_side = None
            if is_bicycle(overtaker_class):
                bike_side = '追い越し側'
            elif is_bicycle(overtaken_class):
                bike_side = '追い越され側'

            if is_motorbike(overtaker_class):
                motor_side = '追い越し側'
            elif is_motorbike(overtaken_class):
                motor_side = '追い越され側'

            if is_vehicle(overtaker_class):
                vehicle_side = '追い越し側'
            elif is_vehicle(overtaken_class):
                vehicle_side = '追い越され側'

            if bike_side:
                add_row(bike_side, '追い越され側' if bike_side == '追い越し側' else '追い越し側')
            if motor_side and motor_side != bike_side:
                add_row(motor_side, '追い越され側' if motor_side == '追い越し側' else '追い越し側')
            if vehicle_side:
                add_row(vehicle_side, '追い越され側' if vehicle_side == '追い越し側' else '追い越し側')

        output_df = pd.DataFrame(output_rows, columns=[
            'Run ID',
            '動画ファイル',
            'フレーム',
            '自グループID',
            '自クラス',
            '相手グループID',
            '離隔距離(m)',
            '離隔距離(cm)',
            '接近距離(m)',
            '追い越しフラグ',
            '白線距離(m)',
            '中央線越え(m)',
            '白線越え(m)',
            '中央線越え',
            '白線越え',
        ])

        mode_suffix = ""
        if output_mode == 'ALL':
            mode_suffix = "_ALL"
        elif output_mode == 'GROUP':
            mode_suffix = "_GROUP"
        elif output_mode == 'FLAG':
            mode_suffix = "_FLAG"

        output_dir = output_root
        os.makedirs(output_dir, exist_ok=True)
        print(f"出力フォルダ作成: {output_dir}")
        csv_name = f"recalc_pair_summary_{timestamp}{mode_suffix}.csv"
        sub_csv_path = os.path.join(output_dir, csv_name)
        try:
            output_df.to_csv(sub_csv_path, index=False, encoding='utf-8-sig')
            print(f"CSV出力: {sub_csv_path}")
            exported_csv_paths.append(sub_csv_path)
        except Exception as e:
            print(f"CSV出力失敗: {sub_csv_path} ({e})")

    if exported_csv_paths:
        print(f"CSV出力件数: {len(exported_csv_paths)}")
        print(f"最新CSV: {exported_csv_paths[-1]}")
    else:
        print("CSV出力なし")
    print("Done.")
    if pause_on_exit:
        input("Enterで閉じる...")

if __name__ == "__main__":
    main()
