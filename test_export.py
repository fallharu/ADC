import requests

resp = requests.get('http://127.0.0.1:5001/api/manual_overtake/export?format=csv')
print(f'Status: {resp.status_code}')
print(f'Content-Type: {resp.headers.get("Content-Type", "None")}')
if resp.status_code == 200:
    print(f'Content preview: {resp.text[:200]}')
else:
    print(f'Error: {resp.text[:500]}')
