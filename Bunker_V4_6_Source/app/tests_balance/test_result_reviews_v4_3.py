"""Result protocol: transitions, frozen timers, permissions and privacy."""
import copy
import json
import random
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from server import app as api, deck_data
from server.game_engine import BunkerGameRoom
from server.results import REVIEW_SECONDS
from server.special_cards import special_availability
from server.bot_turns import plan_turn


def room(count=6, events=False, capacity=None):
    random.seed(443)
    r = BunkerGameRoom('R431', 'p0', 'Алекс')
    for i in range(1, count):
        r.add_player(f'p{i}', ['Ирина', 'Максим', 'Дарья', 'Сергей', 'Никита'][i-1] if i<=5 else f'Участник {i}')
    r.start_game(capacity=capacity or count//2, enable_events=events, skip_prologue=True)
    for person in r.players.values():
        person.connected=True
    r.start_voting()
    return r


def cast_all(r, targets):
    for p, target in zip(r.players, targets):
        r.cast_vote(p, target)


def finish_review(r):
    for _ in range(REVIEW_SECONDS):
        r.tick_timer()


def set_special(r, pid, key):
    row=next(c for c in deck_data.SPECIAL_CARDS if c['id']==key)
    r.players[pid].cards['special']={'card_id':key,'value':row['title'],'details':row['desc'], 'used':False,'revealed':False}


def test_primary_tally_only_exists_after_voting_and_preserves_privacy():
    r=room();r.cast_vote('p0','p1')
    s=r.get_state('p2');assert s['result_review'] is None and s['last_vote_summary'] is None
    assert s['voting_status']['my_vote'] is None
    for p,t in zip(list(r.players)[1:], ['p1','p2','p2','p3','p3']):r.cast_vote(p,t)
    summary=r.get_state('p0')['result_review']
    assert summary['data']['decision']=='defense'
    assert summary['data']['candidate_names']==['Ирина','Максим','Дарья']
    assert all(row['votes']==2 and 'percent' not in row for row in summary['data']['detailed_tally'])
    assert summary['data']['required_votes']==5
    assert all(row['percent']==33.3 for row in r.last_vote_summary['detailed_tally'])
    assert 'votes' not in summary['data']
    assert 'vote_target' not in json.dumps(summary)


def test_shared_five_seconds_precedes_entire_defense_timer():
    r=room();cast_all(r,['p1','p1','p1','p2','p3','p4'])
    assert r.phase=='JUSTIFICATION'
    view=r.get_state('p0')['result_review'];assert view['next_label']=='Защита кандидата'
    assert 'Ирина' in view['next_detail'] and '30 сек' in view['next_detail']
    for seconds in range(5,0,-1):
        views=[r.get_state(pid)['result_review'] for pid in ['p0','p1','observer']]
        assert all(v['id']==view['id'] and v['seconds_left']==seconds for v in views)
        assert r.timer_seconds_left==30
        r.tick_timer()
    assert r.get_state('p0')['result_review'] is None and r.timer_seconds_left==30
    r.tick_timer();assert r.timer_seconds_left==29


def test_real_clock_grants_five_full_seconds_not_four():
    with patch('server.results.time.monotonic',return_value=100):
        r=room();cast_all(r,['p1']*6)
        assert not r.advance_review_clock(100.999)
        for elapsed in range(1,5):
            assert r.advance_review_clock(100+elapsed)
            assert r.result_reviews[0]['seconds_left']==5-elapsed
        assert r.timer_seconds_left==10
        assert r.advance_review_clock(105)
        assert not r.result_reviews and r.timer_seconds_left==10


def test_vote_candidate_not_expelled_during_review_or_veto_window():
    r=room();cast_all(r,['p1']*6)
    assert r.phase=='VOTE_RESULTS' and r.timer_seconds_left==10
    assert r.get_state('p0')['result_review']['next_label']=='Право вето'
    finish_review(r)
    for _ in range(9):r.tick_timer()
    assert r.players['p1'].is_alive and r.timer_seconds_left==1
    r.tick_timer()
    assert not r.players['p1'].is_alive and r.phase=='LAST_WORD'
    assert r.timer_seconds_left==r.last_word_duration_sec


@pytest.mark.parametrize('targets,tied', [(['p1']*6,False),(['p1','p2']*3,True)])
def test_revote_summary_records_final_candidates_and_random_tie(targets,tied):
    r=room();r.start_justification(['p1','p2'],True,[],50);r.start_revote()
    cast_all(r,targets)
    data=r.get_state('p0')['result_review']['data']
    assert data['source']=='REVOTE' and data['revote_completed']
    assert data['is_tie']==tied
    if tied:assert data['tie_broken_by']=='dice'
    assert data['eliminated_ids'][0] in ['p1','p2']


def test_weighted_ballots_count_skip_abstain_and_double_vote():
    r=room();r.players['p0'].double_vote=True
    cast_all(r,['p1','p1','p2','ABSTAIN','SKIP_ROUND','p3'])
    data=r.last_vote_summary
    assert data['counts']['total_weight']==7
    assert data['counts']['skip_weight']==1 and data['counts']['abstain_weight']==1
    assert data['detailed_tally'][0]['votes']==3 and data['detailed_tally'][0]['percent']==42.9
    assert sum(row['votes'] for row in data['detailed_tally']) + sum(data['counts'][key] for key in ['skip_weight','abstain_weight','uncast_weight','other_weight'])==7


def test_early_skip_includes_uncast_and_existing_candidate_votes():
    r=room()
    for pid, target in zip(r.players,['p2','SKIP_ROUND','SKIP_ROUND','SKIP_ROUND','SKIP_ROUND']):r.cast_vote(pid,target)
    data=r.last_vote_summary
    assert data['decision']=='skip'
    assert data['counts']['skip_weight']==4 and data['counts']['uncast_weight']==1
    assert data['detailed_tally'][0]['votes']==1
    assert r.round_number==1
    finish_review(r)
    assert not r.result_reviews and r.round_number==2 and r.phase=='REVEAL'
    assert r.timer_seconds_left==60 and all(p.is_alive for p in r.players.values())
    assert r.double_elimination_pending


def test_no_candidate_votes_finish_after_five_seconds_without_extra_wait():
    r=room();cast_all(r,['ABSTAIN']*6)
    assert r.last_vote_summary['decision']=='none' and r.timer_seconds_left==0
    assert r.review_state_for('p0')['next_label']=='Раунд 2 · открытие карточек'
    finish_review(r)
    assert r.phase=='REVEAL' and r.round_number==2 and r.timer_seconds_left==60


def test_no_exile_review_then_event_review_then_new_round_with_full_timer():
    r=room(events=True);cast_all(r,['ABSTAIN']*6)
    assert r.review_state_for('p0')['next_label']=='Результат испытания'
    finish_review(r)
    view=r.review_state_for('p0')
    assert view['kind']=='event' and view['seconds_left']==5
    assert view['data']['round_number']==1 and r.round_number==2
    assert view['next_label']=='Открытие карточек' and r.timer_seconds_left==60
    finish_review(r)
    assert not r.result_reviews and r.timer_seconds_left==60


def test_automatic_event_after_elimination_does_not_eat_last_word():
    r=room(events=True);cast_all(r,['p1']*6);finish_review(r)
    for _ in range(10):r.tick_timer()
    view=r.review_state_for('p0')
    assert view['kind']=='event' and view['next_label']=='Последнее слово'
    assert not r.players['p1'].is_alive and r.phase=='LAST_WORD'
    assert r.timer_seconds_left==r.last_word_duration_sec
    finish_review(r)
    assert r.timer_seconds_left==r.last_word_duration_sec
    assert len(r.resolved_events)==1


def test_veto_remains_available_after_review_and_changes_next_step():
    r=room();set_special(r,'p0','veto_vote');cast_all(r,['p1']*6)
    assert special_availability(r,'p0')['available'] is False
    with pytest.raises(ValueError):r.use_special_card('p0')
    assert not r.players['p0'].cards['special']['used']
    finish_review(r);assert special_availability(r,'p0')['available']
    r.use_special_card('p0')
    assert r.review_state_for('p0')['data']['decision']=='veto'
    assert r.review_state_for('p0')['next_label']=='Раунд 2 · открытие карточек'
    finish_review(r);assert all(p.is_alive for p in r.players.values()) and r.round_number==2


@pytest.mark.parametrize('roll,success,critical', [(1,True,True),(20,True,False),(95,False,False),(100,False,True)])
def test_event_outcome_uses_server_roll_without_changing_score(roll,success,critical):
    r=room(events=True)
    r.active_event=copy.deepcopy(next(e for e in deck_data.BUNKER_EVENTS if e['type']=='BUNKER_CRISIS'))
    r.recalculate_event_odds()
    result=r.resolve_active_event(force_roll=roll)
    data=r.review_state_for('p0')['data']
    assert data['roll']==roll and data['is_success']==success
    assert (data['is_crit_success'] or data['is_crit_failure'])==critical
    assert data['rating_after']==r.events_score_delta and data['rating_change']==data['rating_after']-data['rating_before']
    assert data['score_delta']==result['score_delta']
    with pytest.raises(ValueError):r.resolve_active_event()
    assert len(r.result_reviews)==1 and len(r.resolved_events)==1


def test_skipped_sortie_and_guaranteed_success_do_not_invent_dice():
    r=room(events=True)
    r.active_event=copy.deepcopy(next(e for e in deck_data.BUNKER_EVENTS if e['type']=='SURFACE_EVENT'))
    r.recalculate_event_odds();r.skip_sortie(True)
    result=r.resolve_active_event()
    assert result['is_skipped'] and result['roll']==0 and result['rating_change']==0
    finish_review(r);r.host_trigger_event()
    result=r.resolve_active_event(guaranteed_success=True)
    assert result['guaranteed_success'] and result['is_success'] and not result['is_crit_success'] and result['roll']==0


def test_manual_event_review_restores_same_timer_and_preserves_existing_pause():
    r=room(events=True);r.timer_seconds_left=37;r.timer_is_paused=True
    r.resolve_active_event(force_roll=50)
    assert r.phase=='VOTING' and not r.review_state_for('p0')['is_paused']
    finish_review(r)
    assert r.timer_seconds_left==37 and r.timer_is_paused
    r.tick_timer();assert r.timer_seconds_left==37


def test_review_pause_freezes_review_not_the_original_phase_pause():
    r=room();cast_all(r,['p1']*6);r.tick_timer()
    r.host_pause_timer(True)
    for _ in range(10):r.tick_timer()
    assert r.review_state_for('p0')['seconds_left']==4 and r.timer_seconds_left==10
    assert not r.timer_is_paused
    r.host_pause_timer(False)
    for _ in range(4):r.tick_timer()
    assert not r.result_reviews and not r.timer_is_paused and r.timer_seconds_left==10


def test_hidden_health_is_removed_from_popup_last_result_and_history():
    r=room(events=True);r.players['p1'].cards['health']['revealed']=False
    result={'is_success':False,'health_degraded':{'player_id':'p1','player_name':'Ирина',
        'old_condition':'PRIVATE_OLD','new_condition':'PRIVATE_NEW'},'resolved_at':1}
    r.last_resolved_event=result;r.resolved_events=[{'result':result,'event':{},'round':1}]
    r.present_event_result(result,{'type':'SURFACE_EVENT'},0,'p1')
    for pid in ['p0','observer',None]:
        state=r.get_state(pid)
        assert 'PRIVATE_' not in json.dumps([state['result_review'],state['events_state']],ensure_ascii=False)
    state=r.get_state('p1')
    assert state['result_review']['data']['health_degraded']['new_condition']=='PRIVATE_NEW'
    r.players['p1'].cards['health']['revealed']=True
    assert r.get_state('p0')['events_state']['last_resolved']['health_degraded']['new_condition']=='PRIVATE_NEW'
    assert r.last_resolved_event['health_degraded'] is not None


def test_result_payloads_are_copies_not_mutable_room_references():
    r=room();cast_all(r,['p1']*6)
    view=r.get_state('p0');view['result_review']['data']['detailed_tally'].clear()
    view['last_vote_summary']['eliminated_ids'].clear()
    assert len(r.review_state_for('p0')['data']['detailed_tally'])==1
    assert r.last_vote_summary['eliminated_ids']==['p1']


def test_queued_results_do_not_replace_each_other_or_spend_next_timer():
    r=room(events=True);r.resolve_active_event(force_roll=1);r.host_trigger_event();r.resolve_active_event(force_roll=99)
    assert len(r.result_reviews)==2
    first=r.review_state_for('p0');assert first['next_label']=='Результат испытания'
    finish_review(r)
    second=r.review_state_for('p0');assert second['id']!=first['id'] and second['seconds_left']==5
    finish_review(r)
    assert not r.result_reviews and r.timer_seconds_left==r.voting_duration_sec


def test_event_review_can_finish_after_engine_reaches_final():
    r=room(events=True);r.resolve_active_event(force_roll=1);r.trigger_final()
    assert r.phase=='FINAL' and r.review_state_for('p0')['next_label']=='Итоги партии'
    finish_review(r);assert not r.result_reviews and r.phase=='FINAL'


def test_new_game_clears_review_and_recap():
    r=room();cast_all(r,['p1']*6)
    r.start_game(capacity=3,enable_events=False,skip_prologue=True)
    assert not r.result_reviews and not r.last_vote_summary and not r.vote_summary_history


@pytest.mark.parametrize('action', ['CAST_VOTE','CONFIRM_ELIMINATION','NEXT_SPEAKER','NEXT_REVEAL',
  'NEXT_JUSTIFICATION_SPEAKER','NEXT_ACCUSATION_SPEAKER','FINISH_LAST_WORD','USE_SPECIAL_CARD',
  'HOST_FORCE_NEXT_SPEAKER','HOST_SET_PHASE','HOST_RESTART_PHASE','HOST_ADD_TIME',
  'HOST_ELIMINATE','HOST_RESTORE','HOST_ADJUST_CAPACITY','RESOLVE_EVENT','HOST_TRIGGER_EVENT',
  'ASSIGN_VOLUNTEER','REVEAL_CARD','EXILE_VENDETTA','SKIP_SORTIE','HOST_KICK'])
def test_action_barrier_keeps_review_from_being_skipped(action):
    r=room();cast_all(r,['p1']*6)
    with pytest.raises(ValueError,match='общий показ'):r.require_review_finished(action)


@pytest.mark.parametrize('action',['PING','HOST_PAUSE_TIMER','CLAIM_HOST','JOIN_LOBBY'])
def test_connection_and_pause_commands_still_allowed(action):
    r=room();cast_all(r,['p1']*6);r.require_review_finished(action)


def test_bots_wait_for_review_even_when_next_speaker_is_already_prepared():
    r=room(events=True);r.start_speech_phase();r.resolve_active_event(force_roll=1)
    pid=r.get_current_speaker().id
    assert plan_turn(r.get_state(pid),pid,['profession','health']) is None
    finish_review(r)
    assert plan_turn(r.get_state(pid),pid,['profession','health'])['action']=='NEXT_SPEAKER'


def receive(ws,kind):
    for _ in range(80):
        msg=ws.receive_json()
        if msg.get('type')==kind:return msg
    raise AssertionError(kind)


def test_asgi_blocks_premature_commands_but_allows_reconnect_and_review_pause():
    r=room();cast_all(r,['p1']*6);api.rooms[r.room_code]=r
    client=TestClient(api.app)
    try:
        with client.websocket_connect('/ws/R431/p0') as host:
            view=receive(host,'STATE_UPDATE')['state']['result_review']
            host.send_json({'action':'CONFIRM_ELIMINATION','payload':{}})
            assert 'общий показ' in receive(host,'ERROR')['message']
            assert r.players['p1'].is_alive
            host.send_json({'action':'HOST_PAUSE_TIMER','payload':{'is_paused':True}})
            assert receive(host,'STATE_UPDATE')['state']['result_review']['is_paused']
        with client.websocket_connect('/ws/R431/p0') as host:
            again=receive(host,'STATE_UPDATE')['state']['result_review']
            assert view['id']==again['id'] and again['seconds_left']==5 and again['is_paused']
            host.send_json({'action':'HOST_PAUSE_TIMER','payload':{'is_paused':False}})
            assert not receive(host,'STATE_UPDATE')['state']['result_review']['is_paused']
            finish_review(r)
            host.send_json({'action':'CONFIRM_ELIMINATION','payload':{}})
            assert receive(host,'STATE_UPDATE')['state']['phase']=='LAST_WORD'
    finally:
        api.rooms.pop(r.room_code,None);api.connections.pop(r.room_code,None);client.close()


def test_new_assets_are_present_in_index_and_served():
    client=TestClient(api.app)
    try:
        text=client.get('/').text
        for resource in ['js/results.js','css/results.css']:
            assert resource in text and client.get('/static/'+resource).status_code==200
    finally:client.close()
