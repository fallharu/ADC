from ultralytics import YOLO
import sys
import os

model_path = r"c:\Users\kurok\Downloads\G_ADC\ADC_08\models\best.pt"
if not os.path.exists(model_path):
    print(f"File not found: {model_path}")
    sys.exit(1)

try:
    model = YOLO(model_path)
    print("Classes found in best.pt:")
    for id, name in model.names.items():
        print(f"{id}: {name}")
except Exception as e:
    print(f"Error loading model: {e}")
