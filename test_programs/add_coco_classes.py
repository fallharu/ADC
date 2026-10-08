import sqlite3

# COCO class names (80 classes, IDs 0-79)
COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator",
    "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
]

# Custom classes (100+)
CUSTOM_CLASSES = {
    100: "tire",
    101: "number_plate",
    102: "bicycle_tire",
}

conn = sqlite3.connect('db/my_app_data.db')
c = conn.cursor()

# Get existing class_ids and class_names
c.execute("SELECT class_id, class_name FROM Class")
existing = c.fetchall()
existing_ids = set(r[0] for r in existing)
existing_names = set(r[1] for r in existing)
print(f"既存のclass_id: {len(existing_ids)} 件")
print(f"既存のclass_name: {existing_names}")

# Add missing COCO classes (skip if name already exists)
added = 0
for i, name in enumerate(COCO_CLASSES):
    if i not in existing_ids:
        # Modify name if it already exists
        final_name = name
        if name in existing_names:
            final_name = f"{name}_{i}"
        try:
            c.execute("INSERT INTO Class (class_id, class_name) VALUES (?, ?)", (i, final_name))
            added += 1
            print(f"  追加: {i} = {final_name}")
        except Exception as e:
            print(f"  スキップ: {i} = {name} ({e})")

# Add missing custom classes
for class_id, name in CUSTOM_CLASSES.items():
    if class_id not in existing_ids:
        final_name = name
        if name in existing_names:
            final_name = f"{name}_{class_id}"
        try:
            c.execute("INSERT INTO Class (class_id, class_name) VALUES (?, ?)", (class_id, final_name))
            added += 1
            print(f"  追加: {class_id} = {final_name}")
        except Exception as e:
            print(f"  スキップ: {class_id} = {name} ({e})")

conn.commit()
c.execute("SELECT COUNT(*) FROM Class")
print(f"\n完了！ Class テーブル: {c.fetchone()[0]} rows (追加: {added})")
conn.close()
