import sys
import os
sys.path.append(os.getcwd())

try:
    print("Attempting to import Source_code.routes.index...")
    from Source_code.routes import index
    print("Import successful!")
except Exception:
    import traceback
    traceback.print_exc()
