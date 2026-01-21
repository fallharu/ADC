from Source_code.app import app

with app.app_context():
    with open("routes_v2.txt", "w", encoding="utf-8") as f:
        f.write("Dumping all routes:\n")
        for rule in app.url_map.iter_rules():
            if "manual_overtake" in rule.rule:
                f.write(f"{rule.rule} -> {rule.endpoint}\n")
