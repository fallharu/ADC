import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime

# Source_codeからモジュールをインポートするためのパス設定
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    from Source_code.modules.db_manager import MAIN_DB_PATH
except ImportError:
    # Source_codeがパスにない場合、または別の場所から実行している場合のフォールバック
    sys.path.append(os.path.join(current_dir, 'Source_code'))
    from modules.db_manager import MAIN_DB_PATH

def generate_pair_summary_csv(db_path=MAIN_DB_PATH):
    """
    追い越しペアサマリーCSV（1イベントにつき2行）を生成します。
    ユーザーのリクエストに合わせたカラム構成です。
    """
    
    # 1. 接続とクエリ実行
    # 追い越し側と追い越され側の両方について、'event_frame_num'に対応するDetection行を取得します。
    # Detectionテーブルを(RunID, Frame)で結合し、GroupIDが(追い越し側, 追い越され側)に含まれるものをフィルタリングすることで実現できます。
    
    query = """
    SELECT DISTINCT
        e.overtake_event_id,
        e.run_id,
        v.filename as video_filename,
        e.event_frame_num as frame_num,
        d.group_id,
        c.class_name,
        CASE 
            WHEN d.group_id = e.overtaker_group_id THEN e.overtaken_group_id 
            ELSE e.overtaker_group_id 
        END as approach_partner_group_id,
        d.clearance_distance_m,
        d.clearance_distance_m * 100 as clearance_distance_cm, -- cm換算
        d.approach_distance_m,
        d.overtake,
        d.line_distance,
        d.l_line_cross_m,
        d.r_line_cross_m,
        d.l_line_distance_m,
        d.r_line_distance_m,
        d.travel_direction
    FROM OvertakeEvents e
    JOIN Detection d ON e.run_id = d.run_id 
        AND e.event_frame_num = d.frame_num
    JOIN Video v ON d.video_id = v.video_id
    LEFT JOIN Class c ON d.class_id = c.class_id
    WHERE
        -- 関与するグループに対応する行のみを選択
        (d.group_id = e.overtaker_group_id OR d.group_id = e.overtaken_group_id)
    GROUP BY
        e.run_id,
        e.event_frame_num,
        e.overtaker_group_id,
        e.overtaken_group_id,
        d.group_id
    ORDER BY
        e.run_id,
        e.event_frame_num, 
        e.overtake_event_id,
        d.group_id
    """
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # 追加カラムが存在するか確認
            cursor.execute("PRAGMA table_info(Detection)")
            detection_columns = {row[1] for row in cursor.fetchall()}

            extra_cols = []
            if "center_line_overtake_status" in detection_columns:
                extra_cols.append("d.center_line_overtake_status")
            if "white_line_overtake_status" in detection_columns:
                extra_cols.append("d.white_line_overtake_status")

            if extra_cols:
                query = query.replace("d.travel_direction", "d.travel_direction,\n        " + ",\n        ".join(extra_cols))

            df = pd.read_sql_query(query, conn)
            
        if df.empty:
             print("No records found.")
             return

        # フォーマット処理
        df['overtake_flag'] = df['overtake'].fillna(0).astype(int).apply(lambda x: 'あり' if x == 1 else '-')
        
        # 指標のフォーマット
        if 'clearance_distance_m' in df.columns:
            df['clearance_distance_m'] = df['clearance_distance_m'].round(4)
        if 'clearance_distance_cm' in df.columns:
            df['clearance_distance_cm'] = df['clearance_distance_cm'].round(2)
        if 'approach_distance_m' in df.columns:
            df['approach_distance_m'] = df['approach_distance_m'].round(4)
        if 'line_distance' in df.columns:
            df['line_distance'] = df['line_distance'].round(4)

        # 方向と距離に基づいて、ライン越えカラムを計算
        def get_cross_info(row):
            direction = str(row.get('travel_direction', '')).strip().upper()
            l_cross = row.get('l_line_cross_m')
            r_cross = row.get('r_line_cross_m')
            l_dist = row.get('l_line_distance_m')
            r_dist = row.get('r_line_distance_m')
            
            # フィルタリングのためのクラス確認
            class_name = str(row.get('class_name', '')).lower()
            is_bike = any(x in class_name for x in ['bicycle', 'bike', 'cyclist'])
            
            center_val = None
            white_val = None
            center_dist = None
            white_dist = None
            
            # F（順方向）: 左=白線, 右=中央線
            # B（逆方向）: 左=中央線, 右=白線
            if direction == 'F':
                white_val = l_cross
                center_val = r_cross
                white_dist = l_dist
                center_dist = r_dist
            else:
                center_val = l_cross
                white_val = r_cross
                center_dist = l_dist
                white_dist = r_dist
            
            # 厳密なフィルタリングを適用:
            # 白線越え -> バイク/自転車の場合のみ出力
            if not is_bike:
                white_val = None
                white_dist = None # ステータス情報のため距離も抑制
            
            # 中央線越え -> バイク/自転車以外（つまり車）の場合のみ出力
            if is_bike:
                center_val = None
                center_dist = None
            
            # ステータス計算用に距離を含むSeriesを返す
            return pd.Series([center_val, white_val, center_dist, white_dist], 
                             index=['中央線越え(m)', '白線越え(m)', 'center_dist', 'white_dist'])

        cross_info_df = df.apply(get_cross_info, axis=1)
        df = pd.concat([df, cross_info_df], axis=1)

        # ライン越え値を丸める
        df['中央線越え(m)'] = pd.to_numeric(df['中央線越え(m)'], errors='coerce').round(4)
        df['白線越え(m)'] = pd.to_numeric(df['白線越え(m)'], errors='coerce').round(4)

        def _resolve_status(status_value, cross_value, dist_value, expected_cross_label, inside_label):
            # 1. DBのステータスがあり、具体的であれば優先する
            if status_value is not None:
                status_text = str(status_value).strip()
                if status_text == expected_cross_label:
                    return expected_cross_label
                elif status_text == inside_label:
                    return inside_label
            
            # 2. ライン越え値を確認
            if pd.notnull(cross_value):
                # ライン越え値がNoneでない場合、それを信頼する。
                # 通常、正の値は越えていること、負の値は内側を意味する（ただし、内側の場合はカラムがNoneの場合もある）。
                # ロジックが負の値でもcross_valueに入れている場合は:
                if cross_value > 0:
                    return expected_cross_label
                else:
                    return inside_label
            
            # 3. 距離値にフォールバック
            if pd.notnull(dist_value):
                # 距離はあるがライン越え値がない場合、おそらく内側
                # 距離は通常、レーン内側のときに正の値となる（ラインからの距離）。
                return inside_label
                
            return '-'

        center_status_col = "center_line_overtake_status" if "center_line_overtake_status" in df.columns else None
        white_status_col = "white_line_overtake_status" if "white_line_overtake_status" in df.columns else None

        df['中央線越え'] = df.apply(
            lambda row: _resolve_status(
                (row.get(center_status_col) if center_status_col else None),
                row.get('中央線越え(m)'),
                row.get('center_dist'),
                '中央線越え',
                '中央線内側'
            ),
            axis=1,
        )
        df['白線越え'] = df.apply(
            lambda row: _resolve_status(
                (row.get(white_status_col) if white_status_col else None),
                row.get('白線越え(m)'),
                row.get('white_dist'),
                '白線越え',
                '白線内側'
            ),
            axis=1,
        )

        # 3. カラム名の変更と選択
        # ターゲット: Run ID, 動画ファイル, フレーム, 自グループID, 自クラス, 相手グループID, 
        #         離隔距離(m), 離隔距離(cm), 接近距離(m), 追い越しフラグ, 白線距離(m), 
        #         中央線越え(m), 白線越え(m), 中央線越え, 白線越え
        
        column_map = {
            'run_id': 'Run ID',
            'video_filename': '動画ファイル',
            'frame_num': 'フレーム',
            'group_id': '自グループID',
            'class_name': '自クラス',
            'approach_partner_group_id': '相手グループID',
            'clearance_distance_m': '離隔距離(m)',
            'clearance_distance_cm': '離隔距離(cm)',
            'approach_distance_m': '接近距離(m)',
            'overtake_flag': '追い越しフラグ',
            'line_distance': '白線距離(m)'
            # 計算済みカラムはすでに日本語名を持っている:
            # '中央線越え(m)', '白線越え(m)', '中央線越え', '白線越え'
        }
        
        final_df = df.rename(columns=column_map)
        
        # カラム順序を強制
        cols_ordered = [
            'Run ID', '動画ファイル', 'フレーム', '自グループID', '自クラス', '相手グループID',
            '離隔距離(m)', '離隔距離(cm)', '接近距離(m)', '追い越しフラグ', '白線距離(m)',
            '中央線越え(m)', '白線越え(m)', '中央線越え', '白線越え'
        ]
        
        # 最終的なカラムをフィルタリング
        final_df = final_df[cols_ordered]
        
        # 4. エクスポート
        tstr = datetime.now().strftime('%Y%m%d_%H%M%S')
        out_name = f'overtake_pair_summary_{tstr}.csv'
        out_dir = os.path.join(current_dir, 'output', 'exports')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, out_name)
        
        final_df.to_csv(out_path, index=False, encoding='utf-8-sig')
        
        print(f"Export successful!")
        print(out_path)

    except Exception as e:
        print(f"Error generating CSV: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("Generating Overtake Pair Summary CSV...")
    generate_pair_summary_csv()
