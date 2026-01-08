def get_detection_search_fields():
    """Return list of fields available for search."""
    return [
        {"key": "run_id", "label": "Run ID", "type": "number", "coerce": "int"},
        {"key": "class_name", "label": "クラス名", "type": "text"},
        {"key": "confidence", "label": "信頼度", "type": "number", "coerce": "float"},
        {"key": "distance_m", "label": "車間距離(m)", "type": "number", "coerce": "float"},
        {"key": "ttc_s", "label": "TTC(s)", "type": "number", "coerce": "float"},
    ]
