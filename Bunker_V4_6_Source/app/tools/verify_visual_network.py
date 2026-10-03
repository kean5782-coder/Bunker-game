#!/usr/bin/env python3
"""Real loopback HTTP and WebSocket smoke test with three Python clients.
No browser automation, no firewall/policy edits, no outside network needed.
The child server uses the real app, with external-IP/QR discovery disabled only
inside that test process. A production server and its storage are not touched.
"""
import asyncio, json, os, socket, subprocess, sys, time
from pathlib import Path
import httpx
import websockets

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'visual_results';OUT.mkdir(exist_ok=True)
CHECKS=[]

async def receive(ws, predicate):
    for _ in range(80):
        msg=json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if predicate(msg):return msg
    raise AssertionError('Expected response was not received')

async def send(ws, action, **payload):
    await ws.send(json.dumps({'action':action,'payload':payload}))

async def scenario(base, code, host, guests):
    uri=base.replace('http://','ws://')
    async with websockets.connect(f'{uri}/ws/{code}/{host}') as a, websockets.connect(f'{uri}/ws/{code}/{guests[0]}') as b, websockets.connect(f'{uri}/ws/{code}/{guests[1]}') as c:
        for ws in (a,b,c):await receive(ws,lambda m:m.get('type')=='STATE_UPDATE')
        CHECKS.append('Three independent clients connected over real loopback WebSockets')
        await send(a,'START_GAME',capacity=1,enable_events=False,enable_traitor=False,speech_duration=60,debate_duration=30,voting_duration=15)
        await receive(a,lambda m:m.get('type')=='STATE_UPDATE' and m['state']['phase']=='PROLOGUE')
        await send(a,'ENTER_BUNKER')
        await receive(a,lambda m:m.get('type')=='STATE_UPDATE' and m['state']['phase']=='REVEAL')
        CHECKS.append('Create/join/start/prologue/speech work through the actual protocol')
        await send(a,'HOST_PAUSE_TIMER',is_paused=True)
        await send(a,'START_VOTING')
        await receive(a,lambda m:m.get('type')=='STATE_UPDATE' and m['state']['phase']=='VOTING')
        await send(a,'CAST_VOTE',target_id=guests[0])
        ack=await receive(a,lambda m:m.get('type')=='ACTION_OK' and m.get('action')=='CAST_VOTE')
        assert ack['target_id']==guests[0]
        own=await receive(a,lambda m:m.get('type')=='STATE_UPDATE' and m['state']['voting_status'].get('my_vote')==guests[0])
        other=await receive(b,lambda m:m.get('type')=='STATE_UPDATE' and m['state']['voting_status'].get('votes_cast')==1)
        assert other['state']['voting_status']['my_vote'] is None
        CHECKS.append('Authoritative vote ACK and private own-vote receipt; other client sees only progress')
        await send(b,'CAST_VOTE',target_id='INVALID_TARGET')
        await receive(b,lambda m:m.get('type')=='ERROR')
        CHECKS.append('Invalid vote returns server error instead of false success')
        await send(b,'CAST_VOTE',target_id=host)
        await receive(b,lambda m:m.get('type')=='ACTION_OK' and m.get('action')=='CAST_VOTE')
        await send(a,'HOST_SET_PHASE',new_phase='FINAL')
        final=await receive(a,lambda m:m.get('type')=='STATE_UPDATE' and m['state']['phase']=='FINAL')
        assert final['state']['final_evaluation']['score_kind']=='rating'
        assert len(final['state']['final_evaluation']['breakdown']['needs'])==5
        CHECKS.append('Real server final retains Balance V2 rating and all five needs')
    async with websockets.connect(f'{uri}/ws/{code}/{host}') as a:
        back=await receive(a,lambda m:m.get('type')=='STATE_UPDATE')
        assert back['state']['phase']=='FINAL'
        CHECKS.append('Reconnect retrieves the authoritative final state')


def main():
    s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close()
    base=f'http://127.0.0.1:{port}'
    code=f"import uvicorn;from server import app as a;a.get_external_ip=lambda:None;a.get_local_ip=lambda:'127.0.0.1';a.generate_qr_data_url=lambda url:'';uvicorn.run(a.app,host='127.0.0.1',port={port},lifespan='off',log_level='warning')"
    error=None
    with (OUT/'network_server.log').open('w',encoding='utf8') as log:
        process=subprocess.Popen([sys.executable,'-c',code],cwd=ROOT,stdout=log,stderr=log,env={**os.environ,'BUNKER_MANAGE_FIREWALL':'0'})
        try:
            with httpx.Client(base_url=base,timeout=5) as client:
                for _ in range(80):
                    try:
                        if client.get('/').status_code==200:break
                    except httpx.TransportError:pass
                    time.sleep(.1)
                else:raise AssertionError('Test server did not start')
                for asset in ['/static/css/dashboard.css?v=visual1','/static/js/dashboard.js?v=visual1']:
                    assert client.get(asset).status_code==200
                CHECKS.append('Actual HTTP serves the new page and versioned assets')
                made=client.post('/api/room/create',json={'host_name':'Wire host','enable_events':False}).json()
                room=made['room_code'];host=made['host_id'];guests=[]
                for name in ['Wire guest A','Wire guest B']:
                    response=client.post('/api/room/join',json={'room_code':room,'player_name':name});response.raise_for_status();guests.append(response.json()['player_id'])
                asyncio.run(scenario(base,room,host,guests))
        except Exception as exc:error=f'{type(exc).__name__}: {exc}'
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    report={'passed':error is None,'mode':'Actual loopback HTTP/WebSockets, three Python clients; not a browser match','checks':CHECKS,'failure':error}
    (OUT/'network_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if error:raise SystemExit(1)

if __name__=='__main__':main()
