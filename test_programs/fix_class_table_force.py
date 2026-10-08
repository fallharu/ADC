"""
Classテーブルを COCO 80クラス標準で強力に修正するスクリプト
IntegrityError (UNIQUE constraint failed) を回避するため、2段階で更新する。
"""
import sqlite3

# COCO 80 classes (standard)
COCO_CLASSES = {
    0: 'person', 1: 'bicycle', 2: 'car', 3: 'motorcycle', 4: 'airplane',
    5: 'bus', 6: 'train', 7: 'truck', 8: 'boat', 9: 'traffic light',
    10: 'fire hydrant', 11: 'stop sign', 12: 'parking meter', 13: 'bench',
    14: 'bird', 15: 'cat', 16: 'dog', 17: 'horse', 18: 'sheep', 19: 'cow',
    20: 'elephant', 21: 'bear', 22: 'zebra', 23: 'giraffe', 24: 'backpack',
    25: 'umbrella', 26: 'handbag', 27: 'tie', 28: 'suitcase', 29: 'frisbee',
    30: 'skis', 31: 'snowboard', 32: 'sports ball', 33: 'kite', 34: 'baseball bat',
    35: 'baseball glove', 36: 'skateboard', 37: 'surfboard', 38: 'tennis racket',
    39: 'bottle', 40: 'wine glass', 41: 'cup', 42: 'fork', 43: 'knife',
    44: 'spoon', 45: 'bowl', 46: 'banana', 47: 'apple', 48: 'sandwich',
    49: 'orange', 50: 'broccoli', 51: 'carrot', 52: 'hot dog', 53: 'pizza',
    54: 'donut', 55: 'cake', 56: 'chair', 57: 'couch', 58: 'potted plant',
    59: 'bed', 60: 'dining table', 61: 'toilet', 62: 'tv', 63: 'laptop',
    64: 'mouse', 65: 'remote', 66: 'keyboard', 67: 'cell phone', 68: 'microwave',
    69: 'oven', 70: 'toaster', 71: 'sink', 72: 'refrigerator', 73: 'book',
    74: 'clock', 75: 'vase', 76: 'scissors', 77: 'teddy bear', 78: 'hair drier', 79: 'toothbrush'
}

# カスタムクラス (100番台) - これらは保持
CUSTOM_CLASSES = {
    100: 'tire',
    101: 'number_plate',
    102: 'bicycle_tire'
}

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

print('=== Classテーブル修正開始 ===')

try:
    # 1. まず全てのクラス名を一時的な名前に変更 (重複回避)
    print('Step 1: 全クラス名を一時名に変更中...')
    c.execute("SELECT class_id FROM Class")
    all_ids = [row[0] for row in c.fetchall()]
    
    for cid in all_ids:
        temp_name = f"temp_class_{cid}"
        c.execute("UPDATE Class SET class_name = ? WHERE class_id = ?", (temp_name, cid))
    
    # 2. COCO標準クラスを適用
    print('Step 2: COCO標準定義を適用中...')
    for cid, name in COCO_CLASSES.items():
        if cid in all_ids:
            c.execute("UPDATE Class SET class_name = ? WHERE class_id = ?", (name, cid))
        else:
            c.execute("INSERT INTO Class (class_id, class_name) VALUES (?, ?)", (cid, name))

    # 3. カスタムクラスを適用
    print('Step 3: カスタムクラス定義を適用中...')
    for cid, name in CUSTOM_CLASSES.items():
        if cid in all_ids:
            c.execute("UPDATE Class SET class_name = ? WHERE class_id = ?", (name, cid))
        else:
            c.execute("INSERT INTO Class (class_id, class_name) VALUES (?, ?)", (cid, name))

    conn.commit()
    print('✅ Classテーブルの修正が完了しました。')

except Exception as e:
    conn.rollback()
    print(f'❌ エラーが発生しました: {e}')
    import traceback
    traceback.print_exc()

finally:
    conn.close()
