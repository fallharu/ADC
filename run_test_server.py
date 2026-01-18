from Source_code.app import app

if __name__ == '__main__':
    print("Starting Test Server on port 5001...")
    app.run(port=5001, debug=False)
