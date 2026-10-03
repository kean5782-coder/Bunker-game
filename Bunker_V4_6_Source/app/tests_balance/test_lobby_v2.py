"""Lobby V2 rules, launch snapshots, permissions and protocol regressions."""
import copy
import random
from contextlib import ExitStack
import pytest
from fastapi.testclient import TestClient
from server.game_engine import BunkerGameRoom
from server.lobby import DEFAULTS, PRESETS, validate_settings, public_catalog
from server import app as api
from server.balance import CONFIG


def room(n=6):
    r=BunkerGameRoom('LB02','host','Ведущий')
    for i in range(1,n):r.add_player(f'p{i}',f'Участник {i}')
    return r


def edit(r,**patch):return r.update_lobby_settings(r.host_id,patch,r.lobby_revision)

def ready_all(r):
    for p in r.players.values():r.set_lobby_ready(p.id,True,r.lobby_revision)


@pytest.mark.parametrize('key,value',[
    ('max_players',2),('max_players',21),('max_players',True),('max_players',3.5),
    ('capacity',0),('capacity',20),('speech_duration',5),('speech_duration',61),
    ('speech_duration',181),('voting_duration',9),('voting_duration','30'),
    ('justification_duration',121),('revote_duration',0),('last_word_duration',91),
    ('require_ready','true'),('enable_events',1),('show_prologue',None),
    ('preset','GOD_MODE'),('event_difficulty','impossible'),('initial_reveal','all_secret'),
    ('catastrophe_id','missing'),('bunker_id','bunker_99'),('speaker_order',[]),
    ('admin_token','x'),('seed',42)])
def test_invalid_settings_are_atomic(key,value):
    r=room();ready_all(r);before=(copy.deepcopy(r.lobby_settings),set(r.lobby_ready),r.lobby_revision)
    with pytest.raises(ValueError):edit(r,**{key:value})
    assert (r.lobby_settings,r.lobby_ready,r.lobby_revision)==before


@pytest.mark.parametrize('preset',list(PRESETS))
def test_every_preset_starts_actual_deal(preset):
    r=room();r.update_lobby_settings('host',PRESETS[preset]);r.start_configured_game('host',r.lobby_revision)
    assert r.phase=='PROLOGUE' and r.match_settings['preset']==preset
    assert len(r.players)==6 and all(p.cards for p in r.players.values())
    assert r.accusation_duration_sec==r.speech_duration_sec//2
    assert r.discussion_duration_sec==0
    assert r.events_enabled==PRESETS[preset]['enable_events']
    assert all(('special' in p.cards)==PRESETS[preset]['enable_special_cards'] for p in r.players.values())


def test_guest_cannot_edit_or_start():
    r=room()
    with pytest.raises(ValueError):r.update_lobby_settings('p1',{'capacity':2})
    with pytest.raises(ValueError):r.start_configured_game('p1')
    assert r.phase=='LOBBY'


def test_readiness_tracks_real_confirmation_and_resets():
    r=room(3);edit(r,require_ready=True)
    assert not r.lobby_state()['can_start']
    assert r.lobby_state()['ready']['host']
    ready_all(r);assert r.lobby_state()['can_start']
    edit(r,speech_duration=90);assert not r.lobby_ready
    assert not r.lobby_state()['can_start']
    ready_all(r);r.add_player('late','Опоздавший');assert not r.lobby_ready
    ready_all(r);r.remove_player('late');assert not r.lobby_ready


def test_optional_readiness_still_allows_classic_launch():
    r=room();assert not r.lobby_ready and r.lobby_state()['can_start']
    r.start_configured_game('host');assert r.phase=='PROLOGUE'


def test_outdated_start_and_ready_are_rejected():
    r=room();rev=r.lobby_revision;edit(r,speech_duration=90)
    with pytest.raises(ValueError):r.start_configured_game('host',rev)
    with pytest.raises(ValueError):r.set_lobby_ready('p1',True,rev)
    with pytest.raises(ValueError):r.update_lobby_settings('host',{'speech_duration':80},rev)
    assert r.lobby_settings['speech_duration']==90


def test_disconnected_player_never_counts_as_ready():
    r=room();ready_all(r);r.players['p1'].connected=False
    assert not r.lobby_state()['ready']['p1']
    assert not r.lobby_state()['can_start']
    with pytest.raises(ValueError):r.start_configured_game('host')


def test_limits_and_room_lock_apply_to_join():
    r=room(3);edit(r,max_players=3)
    with pytest.raises(ValueError):r.can_join_lobby()
    with pytest.raises(ValueError):r.add_player('late','Later')
    edit(r,max_players=4,room_locked=True)
    with pytest.raises(ValueError):r.can_join_lobby()
    edit(r,room_locked=False);r.can_join_lobby()
    with pytest.raises(ValueError):edit(r,max_players=2)


@pytest.mark.parametrize('n',range(3,21))
def test_auto_capacity_stays_valid_and_reacts_to_roster(n):
    r=room(n);assert r.effective_lobby_capacity()==n//2
    edit(r,game_mode='METEORITE')
    assert r.effective_lobby_capacity()==(1 if n<5 else 2)
    assert 1<=r.effective_lobby_capacity()<n


def test_manual_capacity_is_validated_before_launch():
    r=room(3);edit(r,capacity_mode='manual',capacity=4)
    with pytest.raises(ValueError):r.start_configured_game('host')
    assert all(not p.cards for p in r.players.values())
    r.add_player('p4','Four');r.add_player('p5','Five')
    r.start_configured_game('host');assert r.bunker_capacity==4


@pytest.mark.parametrize('cat', [c['id'] for c in public_catalog()['catastrophes']])
def test_every_selected_catastrophe_is_used(cat):
    r=room();edit(r,catastrophe_id=cat,show_prologue=False)
    r.start_configured_game('host');assert r.catastrophe['id']==cat
    assert r.phase=='REVEAL'


@pytest.mark.parametrize('bunker',public_catalog()['bunkers'])
def test_every_selected_bunker_is_used(bunker):
    r=room();edit(r,bunker_id=bunker['id']);r.start_configured_game('host')
    assert r.bunker['name']==bunker['name']
    assert r.bunker['supplies_years']==bunker['supplies_years']


@pytest.mark.parametrize('mode,reveal,opened',[
    ('STANDARD','mode',[]),('METEORITE','mode',['profession','health']),
    ('STANDARD','profession',['profession']),('STANDARD','profession_health',['profession','health']),
    ('METEORITE','closed',[])])
def test_initial_reveal_is_not_confused_with_game_mode(mode,reveal,opened):
    r=room();edit(r,game_mode=mode,initial_reveal=reveal);r.start_configured_game('host')
    for p in r.players.values():
        assert sorted(k for k,v in p.cards.items() if v.get('revealed'))==sorted(opened)


def test_speaker_seating_shuffled_once_and_reversed_in_even_round():
    r=room(8);random.seed(771);edit(r,speaker_order='random',show_prologue=False)
    r.start_configured_game('host');first=list(r.speakers_order)
    assert set(first)==set(r.players) and first!=list(r.players)
    r.start_accusation_phase();assert r.accusation_speakers_order==first
    r.round_number=2;r.start_round();assert r.speakers_order==list(reversed(first))
    r.players[first[2]].is_alive=False;r.round_number=3;r.start_round()
    assert r.speakers_order==[x for x in first if x!=first[2]]


def test_all_timer_fields_drive_their_actual_phases():
    r=room();edit(r,speech_duration=80,voting_duration=35,justification_duration=55,
                  revote_duration=25,last_word_duration=45,show_prologue=False)
    r.start_configured_game('host');assert r.timer_seconds_left==60
    assert r.get_state('host')['timers_config']['reveal']==60
    while r.phase=='REVEAL':r.next_reveal_player(force=True)
    assert r.phase=='SPEECH' and r.timer_seconds_left==80
    r.start_accusation_phase();assert r.timer_seconds_left==40
    r.start_voting();assert r.timer_seconds_left==35
    assert r.justification_duration_sec==55 and r.revote_duration_sec==25 and r.last_word_duration_sec==45
    assert r.discussion_duration_sec==0
    r.start_justification(['p1','p2'],True,[],50);assert r.timer_seconds_left==55
    r.next_justification_speaker();assert r.timer_seconds_left==55
    r.start_revote();assert r.timer_seconds_left==25
    r.vote_results={'is_tie':False,'eliminated_id':'p1','eliminated_ids':['p1']}
    r.phase='VOTE_RESULTS';r.confirm_elimination();assert r.timer_seconds_left==45


@pytest.mark.parametrize('difficulty,delta',[('easy',10),('normal',0),('hard',-10)])
def test_difficulty_is_applied_once_and_clamped(difficulty,delta):
    r=room();edit(r,event_difficulty=difficulty);r.start_configured_game('host')
    r.event_difficulty='normal';r.recalculate_event_odds();base=r.current_event_odds['unclamped_chance']
    r.event_difficulty=difficulty;r.recalculate_event_odds();odds=copy.deepcopy(r.current_event_odds)
    assert odds['unclamped_chance']==base+delta
    assert odds['final_chance']==round(max(CONFIG['event_min'],min(CONFIG['event_max'],base+delta)))
    r.recalculate_event_odds();assert r.current_event_odds==odds
    factors=odds['positive_factors']+odds['negative_factors']
    assert sum(f['delta'] for f in factors if f['category']=='difficulty')==delta


def test_frozen_snapshot_and_duplicate_start_guard():
    r=room();edit(r,enable_special_cards=False,enable_traitor=True,show_prologue=False)
    r.start_configured_game('host');snapshot=copy.deepcopy(r.get_state('host'))
    with pytest.raises(ValueError):r.start_configured_game('host')
    with pytest.raises(ValueError):r.update_lobby_settings('host',{'enable_special_cards':True})
    assert r.get_state('host')==snapshot
    assert all('special' not in p.cards for p in r.players.values())
    assert sum('traitor' in p.cards for p in r.players.values())==1
    assert r.get_state('p1')['lobby'] is None


def test_public_catalog_and_state_cannot_mutate_room():
    r=room();view=r.get_state('p1');view['lobby']['settings']['speech_duration']=900
    assert r.lobby_settings['speech_duration']==60
    c=public_catalog();c['presets']['classic']['speech_duration']=900
    assert public_catalog()['presets']['classic']['speech_duration']==60
    assert not any(k in view['lobby'] for k in ('cards','host_token','seed'))


def until(ws,kind,action=None):
    for _ in range(40):
        m=ws.receive_json()
        if m['type']==kind and (action is None or m.get('action')==action):return m
    raise AssertionError(kind)


def test_asgi_permissions_readiness_and_shared_snapshot(monkeypatch):
    r=room(3);api.rooms[r.room_code]=r;client=TestClient(api.app)
    try:
        with ExitStack() as stack:
            ws={pid:stack.enter_context(client.websocket_connect(f'/ws/{r.room_code}/{pid}')) for pid in r.players}
            for x in ws.values():until(x,'STATE_UPDATE')
            ws['host'].send_json({'action':'UPDATE_LOBBY_SETTINGS','payload':{'settings':{'speech_duration':90,'require_ready':True},'expected_revision':r.lobby_revision}})
            until(ws['host'],'ACTION_OK','UPDATE_LOBBY_SETTINGS')
            state=until(ws['host'],'STATE_UPDATE')['state'];assert state['lobby']['settings']['speech_duration']==90
            ws['p1'].send_json({'action':'UPDATE_LOBBY_SETTINGS','payload':{'settings':{'capacity':1}}})
            assert 'ведущ' in until(ws['p1'],'ERROR')['message']
            ws['host'].send_json({'action':'START_GAME','payload':{'expected_revision':r.lobby_revision}})
            until(ws['host'],'ERROR','START_GAME');assert r.phase=='LOBBY'
            for pid in ('p1','p2'):
                ws[pid].send_json({'action':'SET_LOBBY_READY','payload':{'ready':True,'expected_revision':r.lobby_revision}})
                until(ws[pid],'ACTION_OK','SET_LOBBY_READY')
            ws['host'].send_json({'action':'START_GAME','payload':{'expected_revision':r.lobby_revision}})
            until(ws['host'],'ACTION_OK','START_GAME');assert r.phase=='PROLOGUE'
            ws['p1'].send_json({'action':'CLAIM_HOST','payload':{}});until(ws['p1'],'ERROR','CLAIM_HOST');assert r.host_id=='host'
            assert client.post(f'/api/room/{r.room_code}/claim-host',json={'player_name':'Thief'}).status_code==400
            ws['host'].send_json({'action':'START_GAME','payload':{}});until(ws['host'],'ERROR','START_GAME')
    finally:api.rooms.pop(r.room_code,None);api.connections.pop(r.room_code,None);client.close()


def test_http_catalog_lock_limits_and_bot_authorization():
    r=room(3);api.rooms[r.room_code]=r;client=TestClient(api.app)
    try:
        catalog=client.get('/api/lobby-options').json();assert len(catalog['catastrophes'])==25 and len(catalog['bunkers'])==20
        assert client.post(f'/api/room/{r.room_code}/add-bots',json={'count':1}).status_code==403
        edit(r,room_locked=True)
        assert client.post('/api/room/join',json={'room_code':r.room_code,'player_name':'New'}).status_code==400
        edit(r,room_locked=False,max_players=3)
        assert client.post('/api/room/join',json={'room_code':r.room_code,'player_name':'New'}).status_code==400
    finally:api.rooms.pop(r.room_code,None);api.connections.pop(r.room_code,None);client.close()


@pytest.mark.parametrize('action', ['SET_LOBBY_READY','START_GAME'])
def test_boolean_revision_is_not_a_version_number(action):
    r=room(3);r.lobby_revision=1
    with pytest.raises(ValueError):
        if action=='START_GAME':r.start_configured_game('host',True)
        else:r.set_lobby_ready('p1',True,True)


def test_host_kick_has_ack_and_legacy_lobby_actions_remain_consistent():
    r=room(4);api.rooms[r.room_code]=r;client=TestClient(api.app)
    try:
        with client.websocket_connect(f'/ws/{r.room_code}/host') as ws:
            until(ws,'STATE_UPDATE')
            ws.send_json({'action':'HOST_TOGGLE_EVENTS','payload':{'enabled':False}})
            state=until(ws,'STATE_UPDATE')['state'];assert not state['lobby']['settings']['enable_events']
            ws.send_json({'action':'HOST_TOGGLE_TRAITOR','payload':{'enable_traitor':True}})
            state=until(ws,'STATE_UPDATE')['state'];assert state['lobby']['settings']['enable_traitor']
            ws.send_json({'action':'HOST_ADJUST_CAPACITY','payload':{'capacity':1}})
            state=until(ws,'STATE_UPDATE')['state'];assert state['lobby']['effective_capacity']==1
            ws.send_json({'action':'HOST_KICK','payload':{'player_id':'p3'}})
            result=until(ws,'ACTION_OK','HOST_KICK');assert result['player_id']=='p3' and 'p3' not in r.players
    finally:api.rooms.pop(r.room_code,None);api.connections.pop(r.room_code,None);client.close()


def test_http_reservation_is_not_a_connected_player(monkeypatch):
    monkeypatch.setattr(api,'get_external_ip',lambda:None)
    monkeypatch.setattr(api,'get_local_ip',lambda:'127.0.0.1')
    monkeypatch.setattr(api,'generate_qr_data_url',lambda url:'')
    client=TestClient(api.app);made=client.post('/api/room/create',json={'host_name':'Reserved'}).json()
    code=made['room_code'];r=api.rooms[code]
    try:
        assert not r.players[made['host_id']].connected
        joined=client.post('/api/room/join',json={'room_code':code,'player_name':'Guest'}).json()
        assert not r.players[joined['player_id']].connected
        with client.websocket_connect(f"/ws/{code}/{joined['player_id']}") as ws:
            until(ws,'STATE_UPDATE');assert r.players[joined['player_id']].connected
    finally:api.rooms.pop(code,None);api.connections.pop(code,None);client.close()
