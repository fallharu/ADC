
# Source_code/modules/lane_distance.py
import sqlite3
import pandas as pd
import numpy as np
import json
import os
from .db_manager import MAIN_DB_PATH

def get_distance_point_to_line_segment(point, line_start, line_end):
    """
    点と線分との最短距離を計算する関数
    :param point: 座標 (x, y)
    :param line_start: 線分の始点 (x, y)
    :param line_end: 線分の終点 (x, y)
    :return: 最短距離
    """
    point = np.array(point)
    line_start = np.array(line_start)
    line_end = np.array(line_end)

    # 線分のベクトルと、始点から点へのベクトルを計算
    line_vec = line_end - line_start
    point_vec = point - line_start

    # 線分の長さを計算
    line_len_sq = np.dot(line_vec, line_vec)
    if line_len_sq == 0.0:
        return np.linalg.norm(point - line_start)

    # 点を線分に射影したときの位置を計算 (0から1の間にあれば線分上)
    t = max(0, min(1, np.dot(point_vec, line_vec) / line_len_sq))

    # 線分上で最も点に近い座標を計算
    projection = line_start + t * line_vec

    # 点とその射影点との距離を計算
    distance = np.linalg.norm(point - projection)
    return distance

def assign_lane_distance(run_id: int):
    """
    line_points.jsonを読み込み、各オブジェクトから最も近い白線までの距離を計算する
    """
    # --- JSONファイルのパスを指定 ---
    # ご提示のスクリプトに基づきパスを設定
    # 注意: このパスは環境に依存するため、.envファイルで管理するのが望ましい
    json_path = os.path.join("Y:", os.sep, "Git_Repository", "RTIAT", "tmp", "json", "line", "line_points.json")

    if not os.path.exists(json_path):
        raise FileNotFoundError(f"基準線ファイルが見つかりません: {json_path}\n先に白線描画スクリプトを実行してください。")

    with open(json_path, 'r') as f:
        lines_data = json.load(f)

    if not lines_data:
        raise ValueError("基準線ファイルにデータがありません。")

    # DBから検出データを取得
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        df = pd.read_sql_query(f"SELECT detection_id, x1, y1, x2, y2 FROM Detection WHERE run_id = {run_id}", conn)
    
    if df.empty:
        print(f"Run ID {run_id} には検出データがありません。")
        return

    # 各検出オブジェクトについて、最短距離を計算
    min_distances = []
    for _, row in df.iterrows():
        # オブジェクトの底辺中央を基準点とする
        object_point = ((row['x1'] + row['x2']) / 2, row['y2'])
        
        # 全ての基準線との距離を計算
        distances_to_all_lines = []
        for line in lines_data:
            dist = get_distance_point_to_line_segment(object_point, line["start"], line["end"])
            distances_to_all_lines.append(dist)
        
        # 最も短い距離を選択
        min_dist = min(distances_to_all_lines) if distances_to_all_lines else float('inf')
        min_distances.append(min_dist)

    df['lane_distance'] = min_distances

    # DBを更新
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        c = conn.cursor()
        updates = df[['lane_distance', 'detection_id']].values.tolist()
        c.executemany("UPDATE Detection SET lane_distance = ? WHERE detection_id = ?", updates)
        conn.commit()