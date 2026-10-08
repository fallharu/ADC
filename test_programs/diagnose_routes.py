from Source_code.app import app

print("\n--- Registered Routes ---")
for rule in app.url_map.iter_rules():
    print(f"{rule.endpoint}: {rule.rule}")
print("--- End Routes ---\n")
