"""Real FastAPI/WebSocket protocol: chosen categories, server errors and ACK."""
import pytest
from contextlib import ExitStack
from fastapi.testclient import TestClient
from server import app as api
from server import deck_data as d
from server.balance import VERSION


def until(ws, kind):
    for _ in range(20):
        msg=ws.receive_json()
        if msg.get('type')==kind:return msg
    raise AssertionError('Response not received: '+kind)


def test_api_create_join_start_special_and_final(monkeypatch):
    monkeypatch.setattr(api,'get_external_ip',lambda:None)
    monkeypatch.setattr(api,'get_local_ip',lambda:'127.0.0.1')
    monkeypatch.setattr(api,'generate_qr_data_url',lambda url:'data:image/png;base64,')
    client=TestClient(api.app)
    created=client.post('/api/room/create',json={'host_name':'Balance API','enable_events':False}).json()
    code=created['room_code'];host=created['host_id']
    try:
        guests=[]
        for i in range(3):
            response=client.post('/api/room/join',json={'room_code':code,'player_name':f'Test{i}'})
            assert response.status_code==200;guests.append(response.json()['player_id'])
        # Lobby V2 distinguishes an HTTP reservation from a real connected user.
        with ExitStack() as sockets:
            for pid in guests:sockets.enter_context(client.websocket_connect(f'/ws/{code}/{pid}'))
            ws=sockets.enter_context(client.websocket_connect(f'/ws/{code}/{host}'))
            assert until(ws,'STATE_UPDATE')['state']['phase']=='LOBBY'
            ws.send_json({'action':'START_GAME','payload':{'capacity':2,'enable_events':False}})
            game=until(ws,'STATE_UPDATE')['state'];assert game['information_mode']=='immersion'
            assert api.rooms[code].bunker['balance_version']==VERSION
            r=api.rooms[code];r.enter_bunker(host);p=r.players[host]
            src=next(c for c in d.SPECIAL_CARDS if c['id']=='reroll_dossier_card')
            p.cards['special']={'card_id':src['id'],'value':src['title'],'details':src['desc'],'used':False,'revealed':False}
            old=p.cards['hobby']['value']
            ws.send_json({'action':'USE_SPECIAL_CARD','payload':{'categories':['special']}})
            until(ws,'ERROR');assert not p.cards['special']['used']
            ws.send_json({'action':'USE_SPECIAL_CARD','payload':{'categories':['hobby']}})
            assert until(ws,'ACTION_OK')['action']=='USE_SPECIAL_CARD'
            game=until(ws,'STATE_UPDATE')['state']
            assert p.cards['hobby']['value']!=old and not p.cards['hobby']['revealed']
            ws.send_json({'action':'HOST_SET_PHASE','payload':{'new_phase':'FINAL'}})
            game=until(ws,'STATE_UPDATE')['state']
            while game['phase']!='FINAL':game=until(ws,'STATE_UPDATE')['state']
            assert 'survival_score' not in game['final_evaluation']
            assert r.final_evaluation['score_kind']=='rating'
            assert len(game['final_evaluation']['breakdown']['needs'])==5
            assert 'age_care' not in game['final_evaluation']['breakdown']
            age=r.final_evaluation['breakdown']['age_care']
            assert age['population']==4 and age['known_age_count']==4
            assert sum(row['penalty'] for row in age['rows'])==pytest.approx(age['penalty'])
            assert r.final_evaluation['breakdown']['score_components']['age_care']==-age['penalty']
        assert client.get('/').status_code==200
        for asset in ['/static/js/app.js','/static/js/dashboard.js','/static/css/dashboard.css']:
            assert client.get(asset).status_code==200
    finally:
        api.rooms.pop(code,None);api.connections.pop(code,None);client.close()
