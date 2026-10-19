"""Direct REST API check to compare with MCP result."""
import json
import urllib.request

url = "http://127.0.0.1:8080/api/v1/pets?pageSize=1"
with urllib.request.urlopen(url, timeout=10) as resp:
    data = json.loads(resp.read().decode())
print("REST API direct result:")
print("total:", data.get("data", {}).get("total"))
print("page:", data.get("data", {}).get("page"))
print("pageSize:", data.get("data", {}).get("pageSize"))
print("totalPages:", data.get("data", {}).get("totalPages"))
print("totalCost:", data.get("data", {}).get("totalCost"))
print("items count on this page:", len(data.get("data", {}).get("items", [])))
