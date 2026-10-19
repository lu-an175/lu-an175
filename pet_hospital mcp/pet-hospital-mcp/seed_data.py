"""Seed 1000 mock pet records into the Go backend."""
import json
import urllib.request

url = "http://127.0.0.1:8080/api/v1/admin/seed?force=true&count=1000"
req = urllib.request.Request(url, method="POST")
with urllib.request.urlopen(req, timeout=60) as resp:
    body = resp.read().decode()
    data = json.loads(body)
print("Seed response:")
print(json.dumps(data, ensure_ascii=False, indent=2))
