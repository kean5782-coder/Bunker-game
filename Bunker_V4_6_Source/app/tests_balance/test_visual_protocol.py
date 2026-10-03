"""Visual V1 protocol regressions: private vote receipt and authoritative ACK.
The visual update must not change vote eligibility or private-card visibility.
"""
from contextlib import ExitStack
from fastapi.testclient import TestClient
from server import app as api
from server.game_engine import BunkerGameRoom


def make_room():
    r=BunkerGameRoom('VUI1','host','Host')
    for i in range(3):r.add_player(f'p{i}',f'Player{i}')
    r.start_game(capacity=2,enable_events=False,skip_prologue=True)
    for p in r.players.values():p.connected=True
    r.start_voting();r.host_pause_timer(True)
    return r


def until(ws, kind):
    for _ in range(20):
        data=ws.receive_json()
        if data.get('type')==kind:return data
    raise AssertionError('Missing '+kind)


def test_receipt_belongs_only_to_viewer():
    r=make_room();r.cast_vote('host','p0');r.cast_vote('p0','p1')
    assert r.get_state('host')['voting_status']['my_vote']=='p0'
    assert r.get_state('p0')['voting_status']['my_vote']=='p1'
    assert r.get_state('p1')['voting_status']['my_vote'] is None
    assert r.get_state('observer')['voting_status']['my_vote'] is None
    assert r.get_state(None)['voting_status']['my_vote'] is None


def test_private_receipt_does_not_expose_other_votes():
    r=make_room();r.cast_vote('host','p0')
    view=r.get_state('p1')['voting_status']
    assert view['votes_cast']==1
    assert view['my_vote'] is None
    assert not any(k in view for k in ['votes','targets','voters','tally'])


def test_quarantine_target_remains_legal():
    r=make_room();r.players['p0'].is_quarantined=True
    r.cast_vote('host','p0')
    assert r.votes['host']=='p0'


def test_hidden_cards_still_filtered_for_other_viewer():
    r=make_room()
    own=r.get_state('host');other=r.get_state('p0')
    own_host=next(p for p in own['players'] if p['id']=='host')
    other_host=next(p for p in other['players'] if p['id']=='host')
    assert own_host['cards']['health']['value']==r.players['host'].cards['health']['value']
    assert other_host['cards']['health'].get('value')!=r.players['host'].cards['health']['value']
    assert not other_host['cards']['health']['revealed']


def test_asgi_ack_errors_and_reconnect(monkeypatch):
    monkeypatch.setattr(api,'get_external_ip',lambda:None)
    monkeypatch.setattr(api,'get_local_ip',lambda:'127.0.0.1')
    monkeypatch.setattr(api,'generate_qr_data_url',lambda url:'data:image/png;base64,')
    r=make_room();api.rooms[r.room_code]=r
    client=TestClient(api.app)
    try:
        with ExitStack() as stack:
            sockets={pid:stack.enter_context(client.websocket_connect(f'/ws/{r.room_code}/{pid}')) for pid in r.players}
            for ws in sockets.values():until(ws,'STATE_UPDATE')
            sockets['host'].send_json({'action':'CAST_VOTE','payload':{'target_id':'p0'}})
            ack=until(sockets['host'],'ACTION_OK')
            assert ack['action']=='CAST_VOTE' and ack['target_id']=='p0'
            state=until(sockets['host'],'STATE_UPDATE')['state']
            assert state['voting_status']['my_vote']=='p0'
            sockets['p1'].send_json({'action':'CAST_VOTE','payload':{'target_id':'nonexistent'}})
            assert until(sockets['p1'],'ERROR')
            assert 'p1' not in r.votes
        with client.websocket_connect(f'/ws/{r.room_code}/host') as reconnected:
            state=until(reconnected,'STATE_UPDATE')['state']
            assert state['voting_status']['my_vote']=='p0'
    finally:
        api.rooms.pop(r.room_code,None);api.connections.pop(r.room_code,None);client.close()


def test_new_interface_assets_served():
    with ExitStack() as cleanup:
        client=TestClient(api.app);cleanup.callback(client.close)
        # No app lifespan, external IP calls or background timer needed for static assets.
        for path in ['/','/static/css/style.css?v=visual1','/static/css/dashboard.css?v=visual1','/static/css/animations.css?v=visual1','/static/js/dashboard.js?v=visual1']:
            assert client.get(path).status_code==200
        text=client.get('/').text
        assert 'finalFullText' in text
        assert 'fonts.googleapis.com' not in text
