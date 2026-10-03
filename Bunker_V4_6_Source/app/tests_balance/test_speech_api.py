"""Real WebSocket routing for speech options, ACKs and prompter words."""
from contextlib import ExitStack
from fastapi.testclient import TestClient
from server import app as api, special_cards as sc


def until(ws, kind):
    for _ in range(30):
        message=ws.receive_json()
        if message.get('type')==kind:return message
    raise AssertionError('No '+kind)


def give(r, player, key):
    r.players[player].cards['special']={'category':'special','card_id':key,'value':sc.TITLES[key],'used':False,'revealed':False}


def test_options_and_live_prompter_protocol(monkeypatch):
    monkeypatch.setattr(api,'get_external_ip',lambda:None)
    monkeypatch.setattr(api,'get_local_ip',lambda:'127.0.0.1')
    monkeypatch.setattr(api,'generate_qr_data_url',lambda url:'')
    with TestClient(api.app) as client:
        created=client.post('/api/room/create',json={'host_name':'Алекс'}).json()
        code,host=created['room_code'],created['host_id']
        guests=[client.post('/api/room/join',json={'room_code':code,'player_name':f'Участник {i}'}).json()['player_id'] for i in range(3)]
        try:
            with ExitStack() as stack:
                guest_sockets=[stack.enter_context(client.websocket_connect(f'/ws/{code}/{pid}')) for pid in guests]
                ws=stack.enter_context(client.websocket_connect(f'/ws/{code}/{host}'))
                until(ws,'STATE_UPDATE')
                r=api.rooms[code];r.start_game(capacity=2,enable_events=False,skip_prologue=True)
                r.timer_is_paused=True
                give(r,host,'speech_word')
                ws.send_json({'action':'USE_SPECIAL_CARD','payload':{'target_player_id':guests[0],'option_text':'два слова'}})
                assert until(ws,'ERROR')
                assert not r.players[host].cards['special']['used']
                ws.send_json({'action':'USE_SPECIAL_CARD','payload':{'target_player_id':guests[0],'option_text':'Кабачок','expected_turn_id':r.turn_id}})
                assert until(ws,'ACTION_OK')['action']=='USE_SPECIAL_CARD'
                state=until(ws,'STATE_UPDATE')['state']
                assert 'Кабачок' in state['speech_effects'][0]['instruction']
                give(r,host,'speech_prompter')
                ws.send_json({'action':'USE_SPECIAL_CARD','payload':{'target_player_id':guests[1]}})
                until(ws,'ACTION_OK');until(ws,'STATE_UPDATE')
                r.start_speech_phase();r.host_grant_speech_speaker(guests[1])
                effect=r.speech_effects[guests[1]]
                payload={'target_id':guests[1],'effect_id':effect['id'],'index':0,'word':'Пельмень'}
                guest_sockets[0].send_json({'action':'SPEECH_PROMPT','payload':payload})
                until(guest_sockets[0],'ERROR')
                assert effect['prompts']==[]
                ws.send_json({'action':'SPEECH_PROMPT','payload':payload})
                assert until(ws,'ACTION_OK')['action']=='SPEECH_PROMPT'
                state=until(ws,'STATE_UPDATE')['state']
                assert next(e for e in state['speech_effects'] if e['target_id']==guests[1])['prompts']==['Пельмень']
                ws.send_json({'action':'SPEECH_PROMPT','payload':payload})
                until(ws,'ERROR');assert effect['prompts']==['Пельмень']
                r.next_speaker()
                ws.send_json({'action':'SPEECH_PROMPT','payload':{**payload,'index':1}})
                until(ws,'ERROR')
                assert guests[1] not in r.speech_effects
                give(r,host,'speech_questions')
                ws.send_json({'action':'USE_SPECIAL_CARD','payload':{'target_player_id':guests[2],'expected_turn_id':r.turn_id-1}})
                until(ws,'ERROR');assert not r.players[host].cards['special']['used']
        finally:
            api.rooms.pop(code,None);api.connections.pop(code,None)
