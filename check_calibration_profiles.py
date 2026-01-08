"""
ProcessLogテーブルのcalibration_profileを確認するスクリプト
"""
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("MAIN_DB", "./database/main.db")

def check_profiles():
    """calibration_profileの設定状況を確認"""
    if not os.path.exists(DB_PATH):
        print(f"❌ データベースが見つかりません: {DB_PATH}")
        return
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        print("=" * 80)
        print("ProcessLog - Calibration Profile 確認")
        print("=" * 80)
        
        # プロファイル設定状況のサマリ
        c.execute("""
            SELECT 
                calibration_profile,
                COUNT(*) as count
            FROM ProcessLog
            GROUP BY calibration_profile
            ORDER BY count DESC
        """)
        
        print("\n【プロファイル設定状況のサマリ】")
        print(f"{'プロファイル名':<30} {'Run数':>10}")
        print("-" * 42)
        
        for row in c.fetchall():
            profile = row['calibration_profile'] or '(未設定)'
            count = row['count']
            print(f"{profile:<30} {count:>10}")
        
        # フォルダ別のプロファイル設定状況
        c.execute("""
            SELECT 
                folder_alias,
                calibration_profile,
                COUNT(*) as count
            FROM ProcessLog
            WHERE folder_alias IS NOT NULL
            GROUP BY folder_alias, calibration_profile
            ORDER BY folder_alias, count DESC
        """)
        
        print("\n【フォルダ別プロファイル設定状況】")
        print(f"{'フォルダ':<30} {'プロファイル名':<30} {'Run数':>10}")
        print("-" * 72)
        
        for row in c.fetchall():
            folder = row['folder_alias'] or '(不明)'
            profile = row['calibration_profile'] or '(未設定)'
            count = row['count']
            print(f"{folder:<30} {profile:<30} {count:>10}")
        
        # 最近のRun（最新10件）
        c.execute("""
            SELECT 
                run_id,
                folder_alias,
                calibration_profile,
                status,
                process_start
            FROM ProcessLog
            ORDER BY run_id DESC
            LIMIT 10
        """)
        
        print("\n【最新のRun（10件）】")
        print(f"{'Run ID':<10} {'フォルダ':<20} {'プロファイル':<25} {'状態':<15} {'処理開始日時':<20}")
        print("-" * 92)
        
        for row in c.fetchall():
            run_id = row['run_id']
            folder = row['folder_alias'] or '(不明)'
            profile = row['calibration_profile'] or '(未設定)'
            status = row['status'] or '-'
            proc_start = row['process_start'] or '-'
            print(f"{run_id:<10} {folder:<20} {profile:<25} {status:<15} {proc_start:<20}")
        
        print("\n" + "=" * 80)

if __name__ == "__main__":
    check_profiles()
