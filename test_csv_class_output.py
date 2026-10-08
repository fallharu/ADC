"""
トラックデータCSV出力のクラス名修正テスト
all_save.pyのcreate_all_save関数を直接呼び出してCSV出力をテスト
"""
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Source_code.modules.all_save import create_all_save
import sqlite3

db_path = 'db/my_app_data.db'

print('=== Testing create_all_save function ===')

# Get the latest run_id
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
run_id_result = cursor.execute('SELECT run_id FROM ProcessLog ORDER BY run_id DESC LIMIT 1').fetchone()
conn.close()

if not run_id_result:
    print('❌ No runs found in database')
    sys.exit(1)

run_id = run_id_result[0]
print(f'Testing with run_id: {run_id}')

try:
    csv_path = create_all_save(run_id)
    print(f'\n✓ CSV created successfully: {csv_path}')
    
    # Check the CSV header and first few rows
    if os.path.exists(csv_path):
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()
            print(f'\n=== CSV Header ===')
            header = lines[0].strip().split(',')
            
            # Check if class_name is in header
            if 'class_name' in header:
                class_name_index = header.index('class_name')
                print(f'✓ class_name column found at index {class_name_index}')
                
                # Show first 5 data rows
                print(f'\n=== First 5 Data Rows (class_name only) ===')
                for i, line in enumerate(lines[1:6], 1):
                    values = line.strip().split(',')
                    if len(values) > class_name_index:
                        print(f'Row {i}: class_name = {values[class_name_index]}')
                    else:
                        print(f'Row {i}: ⚠️ Not enough columns')
            else:
                print(f'❌ class_name column NOT found in header')
                print(f'Header columns: {header[:10]}...')
    else:
        print(f'❌ CSV file not found: {csv_path}')
        
except Exception as e:
    print(f'❌ Error: {e}')
    import traceback
    traceback.print_exc()
