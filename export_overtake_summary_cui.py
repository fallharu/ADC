import os
import datetime
import sys

# Source_codeからモジュールをインポートできるように、現在のディレクトリをsys.pathに追加
sys.path.append(os.getcwd())

try:
    from Source_code.modules.full_csv_export import generate_full_csv
    from Source_code.modules.db_manager import MAIN_DB_PATH
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Please ensure you are running this script from the project root directory (G_ADC/ADC_08).")
    sys.exit(1)

def main():
    print("Generating Overtake Summary CSV (Full Detailed Version)...")
    
    try:
        csv_bytes = generate_full_csv(MAIN_DB_PATH)
        
        if not csv_bytes:
            print("No data found to export.")
            return

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"overtake_summary_full_{timestamp}.csv"
        
        # エクスポートディレクトリを決定 (project_root/output/exports)
        # スクリプトが実行される場所からの相対パスを使用（プロジェクトルートを想定）
        export_dir = os.path.join("output", "exports")
        os.makedirs(export_dir, exist_ok=True)
        
        filepath = os.path.abspath(os.path.join(export_dir, filename))
        
        with open(filepath, "wb") as f:
            f.write(csv_bytes)
            
        print(f"Export successful!")
        print(filepath) # リクエストに応じて絶対パスを出力

    except Exception as e:
        print(f"An error occurred during export: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
