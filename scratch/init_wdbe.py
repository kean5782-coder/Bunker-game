import urllib.request
import json
import time

create_data = json.dumps({
    "host_name": "Ведущий",
    "room_code": "WDBE",
    "enable_traitor": False,
    "enable_events": True
}).encode('utf-8')

req = urllib.request.Request(
    "http://127.0.0.1:64738/api/room/create",
    data=create_data,
    headers={"Content-Type": "application/json"}
)

try:
    with urllib.request.urlopen(req) as resp:
        print("Room created:", resp.read().decode('utf-8'))
except Exception as e:
    print("Room creation response/error:", e)

# Check room
time.sleep(1)
with urllib.request.urlopen("http://127.0.0.1:64738/api/room/WDBE") as resp:
    print("Room WDBE status:", resp.read().decode('utf-8'))
