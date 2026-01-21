
import os
import sqlite3
import pandas as pd
from datetime import datetime
from typing import Optional, Dict

from .db_manager import MAIN_DB_PATH

def generate_ran_report(run_id: int, csv_path: Optional[str], output_dir: str, skip_stats: Optional[list] = None) -> Optional[str]:
    """
    RAN実行完了レポートを生成し、ファイルパスを返す。
    
    Args:
        run_id: 対象のRun ID
        csv_path: 生成されたCSVファイルのパス (Noneの場合はスキップ)
        output_dir: レポート保存先のディレクトリ
        skip_stats: 追い越し判定スキップ理由のリスト (Optional)
    """
    
    report_lines = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_lines.append(f"RAN Execution Report - {timestamp}")
    report_lines.append("=" * 60)
    report_lines.append(f"Run ID: {run_id}")
    if csv_path:
        report_lines.append(f"CSV Path: {os.path.basename(csv_path)}")
    report_lines.append("-" * 60)

    # 1. Error Log Check
    # Check if RAN_error.log has entries for today/recent? 
    # For simplicity, we just check if the file exists and has content, 
    # but ideally we might want to check if any error corresponds to this run.
    # The user asked for "Error log exists" status.
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "log")
    error_log_path = os.path.join(log_dir, "RAN_error.log")
    
    has_error = False
    if os.path.exists(error_log_path) and os.path.getsize(error_log_path) > 0:
        # 簡易チェック: 今日の日付のエラーがあるか？
        # ここでは単純に「エラーログファイルあり」とする
        report_lines.append("【エラー状況】")
        report_lines.append(f"  [WARNING] エラーログが存在します: {error_log_path}")
        report_lines.append("  内容を確認してください。")
        has_error = True
    else:
        report_lines.append("【エラー状況】")
        report_lines.append("  [OK] エラーログは検出されませんでした (RAN_error.log なし/空)")

    report_lines.append("-" * 60)

    # 2. Database Counts (Traffic Count & Track IDs)
    report_lines.append("【カウント情報】")
    
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            # A) Traffic Counts (from TrafficCount table)
            # object_type: '車', '自転車'
            c = conn.cursor()
            c.execute("SELECT object_type, SUM(count) FROM TrafficCount WHERE run_id = ? GROUP BY object_type", (run_id,))
            traffic_counts = dict(c.fetchall())
            
            car_count = traffic_counts.get('車', 0)
            mike_count = traffic_counts.get('自転車', 0)
            
            report_lines.append(f"  交通量カウント (TrafficCount):")
            report_lines.append(f"    車両   : {car_count}")
            report_lines.append(f"    自転車 : {mike_count}")

            # B) Track IDs (Unique Group IDs per class category from Detection)
            # Need strict filtering similar to traffic_counter logic
            # Car: 'car', 'truck', 'bus', 'vehicle'
            # Bike: 'bicycle', 'bike'
            
            # Fetch all distinct (group_id, class_name) pairs
            c.execute("""
                SELECT DISTINCT d.group_id, c.class_name 
                FROM Detection d 
                JOIN Class c ON d.class_id = c.class_id 
                WHERE d.run_id = ? AND d.group_id IS NOT NULL
            """, (run_id,))
            
            rows = c.fetchall()
            unique_cars = set()
            unique_bikes = set()
            
            for gid, cls_name in rows:
                cls_lower = str(cls_name).lower()
                if 'bicycle' in cls_lower or 'bike' in cls_lower:
                    unique_bikes.add(gid)
                elif any(x in cls_lower for x in ['car', 'truck', 'bus', 'vehicle']):
                    unique_cars.add(gid)
            
            report_lines.append(f"  ユニークトラックID数 (Unique Track IDs):")
            report_lines.append(f"    車両   : {len(unique_cars)}")
            report_lines.append(f"    自転車 : {len(unique_bikes)}")

    except Exception as e:
        report_lines.append(f"  [ERROR] DB情報の取得に失敗しました: {e}")

    report_lines.append("-" * 60)

    # 3. Skip Stats (Top 3 Reasons)
    if skip_stats:
        report_lines.append("【追い越し判定スキップ理由 (上位3件)】")
        # Ensure it's a list df construction
        try:
            # reasons: "reason" key
            # count by reason
            from collections import Counter
            reasons = [item.get('reason', 'Unknown') for item in skip_stats]
            counts = Counter(reasons)
            top3 = counts.most_common(3)
            
            for reason, count in top3:
                 report_lines.append(f"  - {reason}: {count}回")
                 
            # Show total skipped pairs
            report_lines.append(f"  (合計スキップ数: {len(skip_stats)}件)")
            
        except Exception as e:
            report_lines.append(f"  [ERROR] スキップ情報の集計に失敗: {e}")
    else:
        report_lines.append("【追い越し判定スキップ理由】")
        report_lines.append("  (スキップされたペアはありません)")

    report_lines.append("-" * 60)

    # 4. CSV Column Statistics
    if csv_path and os.path.exists(csv_path):
        report_lines.append("【CSV出力統計 (カラム別出力率)】")
        try:
            df = pd.read_csv(csv_path)
            total_rows = len(df)
            report_lines.append(f"  総行数: {total_rows}")
            
            if total_rows > 0:
                # Calculate non-null counts and percentages
                stats = []
                for col in df.columns:
                    non_null = df[col].count()
                    percent = (non_null / total_rows) * 100
                    stats.append((col, non_null, percent))
                
                # Format output table
                # Name | Count | %
                max_len = max([len(str(c)) for c in df.columns] + [10])
                header = f"  {'Column Name'.ljust(max_len)} | {'Count'.rjust(8)} | {'%'.rjust(6)}"
                report_lines.append(header)
                report_lines.append("  " + "-" * len(header))
                
                for col, count, pct in stats:
                    line = f"  {str(col).ljust(max_len)} | {str(count).rjust(8)} | {f'{pct:.1f}%'.rjust(6)}"
                    report_lines.append(line)
            else:
                report_lines.append("  [WARNING] CSVに行が含まれていません。")

        except Exception as e:
            report_lines.append(f"  [ERROR] CSVの解析に失敗しました: {e}")
    else:
        report_lines.append("【CSV出力統計】")
        report_lines.append("  CSVファイルが生成されなかったか、パスが無効です。")

    report_lines.append("=" * 60)
    
    # Write to file
    ts_file = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"RAN_report_{ts_file}.txt"
    
    # Use output_dir or log dir? 
    # User said "RAN終了時パスをターミナルに表示するように".
    # Creating it in 'log' folder seems appropriate for a report log.
    log_dir = os.path.join(os.getcwd(), "log") # Force logs dir
    os.makedirs(log_dir, exist_ok=True)
    stats_path = os.path.join(log_dir, report_filename)
    
    try:
        with open(stats_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        return stats_path
    except Exception as e:
        print(f"[RAN Report] Failed to write report: {e}")
        return None
