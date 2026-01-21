from Source_code.app import app

with app.app_context():
    print("Dumping all routes:")
    for rule in app.url_map.iter_rules():
        if "manual_overtake" in rule.rule:
            print(f"{rule.rule} -> {rule.endpoint}")
