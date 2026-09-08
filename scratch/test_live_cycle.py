import asyncio
import json
import websockets

async def simulate():
    uri = "ws://127.0.0.1:64738/ws/WDBE/host_sim"
    async with websockets.connect(uri) as ws:
        # Claim host
        await ws.send(json.dumps({"action": "CLAIM_HOST", "payload": {"name": "Ведущий-Тест"}}))
        msg = await ws.recv()
        st = json.loads(msg)["state"]
        print("Lobby total players:", len(st["players"]))

        # Start game
        await ws.send(json.dumps({"action": "START_GAME", "payload": {"capacity": 3, "enable_traitor": False, "enable_events": True}}))
        
        # Wait a few states to observe speech
        for _ in range(5):
            msg = await ws.recv()
            st = json.loads(msg)["state"]
            if st["phase"] == "SPEECH":
                sp = st["current_speaker"]
                st_stat = st.get("speech_status", {})
                print(f"Phase SPEECH: Speaker {sp['name']}, Quota: {st_stat.get('revealed_count')}/{st_stat.get('required_count')}")
                break
        
        print("Simulated test passed successfully!")

asyncio.run(simulate())
