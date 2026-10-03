#!/usr/bin/env python3
"""Age V4 real HTTP/WebSocket integration: three users and actual local bots.
Uses an isolated Uvicorn child on an ephemeral port; never edits host networking.
External IP/QR lookup and clock ticks are disabled in the child for determinism.
Browser tests live in verify_lobby_ui.py and are a separate, offline harness.
"""
from __future__ import annotations
import asyncio, json, os, socket, subprocess, sys, time, traceback
from pathlib import Path
import httpx
import websockets
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server.bot_turns import plan_turn
from server.bot_client import CARD_CATEGORIES
from server import balance as current
from server.age_balance import age_from_cards
OUT=ROOT/'age_results'; OUT.mkdir(exist_ok=True)
CHECKS=[]
def check(condition, name):
    if not condition: raise AssertionError(name)
    CHECKS.append(name)
async def receive(ws, predicate):
    for _ in range(150):
        message=json.loads(await asyncio.wait_for(ws.recv(),timeout=7))
        if predicate(message): return message
    raise AssertionError('Expected protocol response not received')
async def send(ws, action, **payload):
    await ws.send(json.dumps({'action':action,'payload':payload}))
async def state(ws, predicate=lambda g:True):
    return (await receive(ws,lambda m:m.get('type')=='STATE_UPDATE' and predicate(m['state'])))['state']
async def ack(ws, action):return await receive(ws,lambda m:m.get('type')=='ACTION_OK' and m.get('action')==action)
async def error(ws, action):return await receive(ws,lambda m:m.get('type')=='ERROR' and m.get('action')==action)
async def edit(ws, g, **settings):
    await send(ws,'UPDATE_LOBBY_SETTINGS',settings=settings,expected_revision=g['lobby']['revision'])
    a=await ack(ws,'UPDATE_LOBBY_SETTINGS')
    return await state(ws,lambda s:s.get('lobby',{}).get('revision')==a['revision'])
async def scenario(base, code, host, guests, catalog):
    uri=base.replace('http://','ws://');clients=[]
    try:
        for pid in [host,*guests]:
            ws=await websockets.connect(f'{uri}/ws/{code}/{pid}');clients.append(ws)
            await state(ws)
        a,b,c=clients
        await send(a,'PING');await receive(a,lambda m:m.get('type')=='PONG')
        # First state includes all three HTTP-created users. Fresh snapshot after ACK.
        await send(a,'UPDATE_LOBBY_SETTINGS',settings={'require_ready':True,'max_players':6})
        changed=await ack(a,'UPDATE_LOBBY_SETTINGS');g=await state(a,lambda s:s['lobby']['revision']==changed['revision'])
        check(g['total_players']==3,'Three independent Python clients connected to actual room')
        gg=await state(b,lambda s:s['lobby']['settings']['require_ready'])
        check(gg['lobby']['settings']==g['lobby']['settings'],'Authoritative settings broadcast to a different client')
        for action,payload in [('UPDATE_LOBBY_SETTINGS',{'settings':{'speech_duration':120}}),('ADD_BOTS',{'count':1}),('REMOVE_BOTS',{}),('START_GAME',{})]:
            await send(b,action,**payload);e=await error(b,action)
            check(bool(e['message']),f'Guest cannot execute host command {action}')
        await send(a,'START_GAME',expected_revision=g['lobby']['revision']);await error(a,'START_GAME')
        check(True,'Readiness gate enforced on actual server start')
        for ws in (b,c):
            await send(ws,'SET_LOBBY_READY',ready=True,expected_revision=g['lobby']['revision']);await ack(ws,'SET_LOBBY_READY')
        g=await state(a,lambda s:s['lobby']['ready_count']==3)
        check(g['lobby']['can_start'],'Ready confirmations arrive from separate clients')
        oldrev=g['lobby']['revision'];g=await edit(a,g,speech_duration=120,voting_duration=40)
        check(not g['lobby']['ready'][guests[0]] and not g['lobby']['can_start'],'Changing settings resets confirmations for all guests')
        await send(a,'UPDATE_LOBBY_SETTINGS',settings={'voting_duration':50},expected_revision=oldrev)
        await error(a,'UPDATE_LOBBY_SETTINGS')
        await send(a,'UPDATE_LOBBY_SETTINGS',settings={'speech_duration':5,'voting_duration':60},expected_revision=g['lobby']['revision'])
        await error(a,'UPDATE_LOBBY_SETTINGS');same=await state(a,lambda s:s['lobby']['revision']==g['lobby']['revision'])
        check(same['lobby']['settings']['voting_duration']==40,'Stale and invalid edits fail atomically')
        g=await edit(a,g,room_locked=True)
        async with httpx.AsyncClient(base_url=base) as http:
            response=await http.post('/api/room/join',json={'room_code':code,'player_name':'Closed guest'})
            check(response.status_code==400,'Closed room rejects HTTP admission')
        async with websockets.connect(f'{uri}/ws/{code}/watcher') as spectator:
            await state(spectator);await send(spectator,'JOIN_LOBBY',name='Spectator admission')
            await error(spectator,'JOIN_LOBBY');check(True,'Closed room rejects spectator JOIN_LOBBY admission')
        g=await edit(a,g,room_locked=False)
        await send(a,'ADD_BOTS',count=4);await error(a,'ADD_BOTS')
        unchanged=await state(a,lambda s:s['total_players']==3)
        check(unchanged['total_players']==3,'Too-large bot batch rejected before partial insertion')
        await send(a,'ADD_BOTS',count=2);result=await ack(a,'ADD_BOTS')
        g=await state(a,lambda s:s['total_players']==5 and all(p['connected'] for p in s['players']))
        bot_ids=[p['id'] for p in g['players'] if p['id'].startswith('bot_')]
        check(result['added']==2 and len(bot_ids)==2 and all(g['lobby']['ready'][i] for i in bot_ids),'Two real BunkerBot tasks connect and report ready only when connected')
        await send(a,'REMOVE_BOTS');result=await ack(a,'REMOVE_BOTS');g=await state(a,lambda s:s['total_players']==3)
        check(result['removed']==2 and not any(p['id'].startswith('bot_') for p in g['players']),'Remove-bots closes actual bot sockets and restores roster')
        await send(b,'SET_LOBBY_READY',ready=True,expected_revision=g['lobby']['revision']);await ack(b,'SET_LOBBY_READY')
        await b.close()
        g=await state(a,lambda s:any(p['id']==guests[0] and not p['connected'] for p in s['players']))
        check(not g['lobby']['ready'][guests[0]] and not g['lobby']['can_start'],'Disconnect clears readiness and blocks start')
        b=await websockets.connect(f'{uri}/ws/{code}/{guests[0]}');clients.append(b);back=await state(b)
        check(back['lobby']['settings']['speech_duration']==120 and not back['lobby']['ready'][guests[0]],'Reconnect retains settings but requires renewed ready confirmation')
        g=await state(a,lambda s:all(p['connected'] for p in s['players']))
        await send(a,'ADD_BOTS',count=2);await ack(a,'ADD_BOTS')
        g=await state(a,lambda s:s['total_players']==5 and all(p['connected'] for p in s['players']))
        g=await edit(a,g,catastrophe_id=catalog['catastrophes'][0]['id'],bunker_id='bunker_00',event_difficulty='hard',capacity_mode='manual',capacity=2,enable_special_cards=False,show_prologue=False,initial_reveal='profession',speaker_order='random',justification_duration=50,revote_duration=35,last_word_duration=25)
        for ws in (b,c):
            await send(ws,'SET_LOBBY_READY',ready=True,expected_revision=g['lobby']['revision']);await ack(ws,'SET_LOBBY_READY')
        g=await state(a,lambda s:s['lobby']['can_start'])
        await send(a,'START_GAME',expected_revision=g['lobby']['revision'])
        started=await state(a,lambda s:s['phase']=='REVEAL');await ack(a,'START_GAME')
        check(started['catastrophe']['id']==catalog['catastrophes'][0]['id'] and started['bunker']['name']==catalog['bunkers'][0]['name'],'Actual server deal uses selected catastrophe and bunker')
        frozen=started['match_settings']
        check(started['bunker_capacity']==2 and frozen['speech_duration']==120 and frozen['voting_duration']==40,'Capacity and timers survive launch in frozen settings snapshot')
        check(started['lobby'] is None and frozen['event_difficulty']=='hard','Lobby is frozen and difficulty selection retained after launch')
        own=next(p for p in started['players'] if p['id']==host)
        check(started['balance_version']==current.VERSION, 'Actual server advertises Balance 2.1')
        check('age' in own['cards']['gender'] and 'нагрузка ухода' in own['cards']['gender']['mechanics_text'], 'Owner receives current age rules through real WebSocket')
        check(all('age' not in p['cards']['gender'] and 'mechanics_text' not in p['cards']['gender'] for p in started['players'] if p['id']!=host), 'Real WebSocket hides other age and mechanic data before reveal')
        check('special' not in own['cards'] and all(p['cards']['profession']['revealed'] for p in started['players']),'No special cards and public professions follow configured deal')
        await send(a,'START_GAME');await error(a,'START_GAME');await send(a,'UPDATE_LOBBY_SETTINGS',settings={'speech_duration':60});await error(a,'UPDATE_LOBBY_SETTINGS')
        check(True,'Duplicate start and lobby edits rejected after launch')
        await send(c,'CLAIM_HOST',name='Other');await error(c,'CLAIM_HOST')
        check(True,'Connected host cannot be displaced through CLAIM_HOST')
        # Full reveal circle with actual guest clients and the two actual bot tasks.
        actors = {host: a, guests[0]: b, guests[1]: c}
        g = started
        reveal_turns = []
        opening_card_counts = {}
        while g['phase'] == 'REVEAL':
            pid = g['current_speaker']['id']; token = g['turn_id']
            reveal_turns.append(pid)
            check(g['timer']['seconds_left'] == 60, f'Real reveal turn gets 60 seconds: {pid}')
            if pid.startswith('bot_'):
                g = await state(a, lambda v: v['turn_id'] != token)
            else:
                ws = actors[pid]
                while not g['reveal_status']['can_proceed']:
                    # Observer state hides other hands, but the categories available to
                    # reveal are public. Only the actor sends a card command.
                    local = dict(g)
                    command = plan_turn(local, pid, CARD_CATEGORIES)
                    await send(ws, command['action'], **command['payload'])
                    opened = g['reveal_status']['revealed_count']
                    g = await state(a, lambda v: v['turn_id'] == token and v['reveal_status']['revealed_count'] > opened)
                opening_card_counts[pid] = g['reveal_status']['revealed_count']
                await send(ws, 'NEXT_REVEAL', expected_turn_id=token)
                g = await state(a, lambda v: v['turn_id'] != token)
        check(len(reveal_turns) == started['total_players'] and len(set(reveal_turns)) == len(reveal_turns), 'Each human and bot receives one reveal turn before any speech')
        check(g['phase'] == 'SPEECH' and g['timer']['seconds_left'] == 120, 'First full speech circle starts only after all reveal turns, using 120s custom timer')
        before = {p['id']: sum(c.get('revealed',False) for c in p['cards'].values()) for p in g['players']}
        await send(c, 'REVEAL_CARD', category='fact');await error(c, 'REVEAL_CARD')
        check(True, 'Actual WebSocket rejects ordinary reveal during Speech 1')
        speech_turns = []
        while g['phase'] == 'SPEECH':
            pid = g['current_speaker']['id']; token = g['turn_id'];speech_turns.append(pid)
            if pid in actors: await send(actors[pid], 'NEXT_SPEAKER', expected_turn_id=token)
            g = await state(a, lambda v: v['turn_id'] != token)
        check(speech_turns == reveal_turns, 'Full Speech 1 circle uses the same order, including autonomous bots')
        after = {p['id']: sum(c.get('revealed',False) for c in p['cards'].values()) for p in g['players']}
        check(before == after, 'No extra automatic reveals during any real-network first speech')
        check(g['phase'] == 'ACCUSATION' and g['timer']['seconds_left'] == 60, 'Second speech remains half duration after the independent opening circle')
        await send(a,'HOST_SET_PHASE',new_phase='FINAL')
        final=await state(a,lambda s:s['phase']=='FINAL')
        ev=final['final_evaluation'];care=ev['breakdown']['age_care']
        alive=[p for p in final['players'] if p['is_alive']]
        expected=current.evaluate_survival(alive,final['catastrophe'],final['bunker'],resolved_events_history=[])
        check(ev['survival_score']==expected['survival_score'], 'Actual network final rating equals independent recalculation')
        check(care==expected['breakdown']['age_care'], 'Entire age breakdown transported without losing fields')
        check(care['population']==len(alive) and care['known_age_count']==len(alive), 'Actual final counts each survivor age once')
        check(0<=care['penalty']<=12 and abs(sum(p['penalty'] for p in care['rows'])-care['penalty'])<.001, 'Live final age penalty is bounded and personal shares add up')
        other=await state(c,lambda s:s['phase']=='FINAL')
        check(other['final_evaluation']==ev, 'Other client receives identical final age evaluation')


    finally:
        for ws in clients:
            await ws.close()
def main():
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();base=f'http://127.0.0.1:{port}'
    child=f"import uvicorn;from server import app as a;a.PORT={port};a.get_external_ip=lambda:None;a.get_local_ip=lambda:'127.0.0.1';a.generate_qr_data_url=lambda url:'';uvicorn.run(a.app,host='127.0.0.1',port={port},lifespan='off',log_level='warning')"
    failure=None
    with (OUT/'age_network_server.log').open('w',encoding='utf8') as log:
        process=subprocess.Popen([sys.executable,'-c',child],cwd=ROOT,stdout=log,stderr=log,env={**os.environ,'BUNKER_MANAGE_FIREWALL':'0'})
        try:
            with httpx.Client(base_url=base,timeout=7) as http:
                for _ in range(80):
                    try:
                        if http.get('/').status_code==200:break
                    except httpx.TransportError:pass
                    time.sleep(.1)
                else:raise AssertionError('Server failed to start')
                page=http.get('/').text
                check('/static/js/lobby.js?v=age-v4' in page,'Actual HTTP page loads Lobby V2 versioned script')
                for asset in ['/static/js/lobby.js?v=age-v4','/static/css/lobby.css?v=age-v4']:
                    check(http.get(asset).status_code==200,f'HTTP serves {asset}')
                catalog=http.get('/api/lobby-options').json()
                check(len(catalog['catastrophes'])==25 and len(catalog['bunkers'])==20,'HTTP catalog supplies all actual scenarios')
                made=http.post('/api/room/create',json={'host_name':'Wire host'});made.raise_for_status();made=made.json()
                code=made['room_code'];host=made['host_id'];guests=[]
                for name in ('Wire guest A','Wire guest B'):
                    response=http.post('/api/room/join',json={'room_code':code,'player_name':name});response.raise_for_status();guests.append(response.json()['player_id'])
                check(http.post(f'/api/room/{code}/add-bots',json={'count':1}).status_code==403,'Legacy HTTP bot insertion requires host token')
                asyncio.run(scenario(base,code,host,guests,catalog))
        except Exception as exc:
            failure=f'{type(exc).__name__}: {exc}';traceback.print_exc()
        finally:
            process.terminate()
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    result={'passed':failure is None,'count':len(CHECKS),'checks':CHECKS,'failure':failure,'transport':'Real loopback HTTP/WebSockets; three independent Python users and two real BunkerBot clients. Not a live browser or human match.'}
    (OUT/'age_network.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False,indent=2))
    if failure:raise SystemExit(1)
if __name__=='__main__':main()
