import json
import os

# Check if JSON file exists and can be loaded
config_dir = os.path.join(os.path.dirname(__file__), 'config')
best_classes_path = os.path.join(config_dir, 'best_model_classes.json')

print(f'JSON file path: {best_classes_path}')
print(f'File exists: {os.path.exists(best_classes_path)}')

if os.path.exists(best_classes_path):
    with open(best_classes_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f'JSON content: {data}')
    print(f'Type: {type(data)}')
    
    # Test mapping
    class_names_list = [data.get(str(i), f'Unknown_{i}') for i in range(len(data))]
    print(f'class_names_list: {class_names_list}')
    
    # Simulate mapping
    test_class_ids = [0, 2, 15]
    sorted_ids = sorted(test_class_ids)
    mapping = {cid: idx for idx, cid in enumerate(sorted_ids)}
    
    print(f'\nTest with class_ids: {test_class_ids}')
    print(f'Sorted: {sorted_ids}')
    print(f'Mapping: {mapping}')
    
    for cid in test_class_ids:
        idx = mapping.get(cid)
        if idx is not None and idx < 3:
            name = class_names_list[idx] if idx < len(class_names_list) else None
            print(f'  class_id {cid} -> index {idx} -> {name}')
        else:
            print(f'  class_id {cid} -> index {idx} -> NULL')
