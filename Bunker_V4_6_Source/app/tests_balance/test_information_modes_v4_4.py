"""V4.4 information policies: model invariance, privacy and live ASGI transport."""
import copy
import json
import random
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from server import app as api, deck_data
from server.game_engine import BunkerGameRoom
from server.lobby import validate_settings, PRESETS
from server.presentation import public_odds, public_card, public_event, public_event_result

MODES = ('immersion', 'uncertainty')
PRIVATE_FIELDS = {
    'mechanics', 'mechanics_text', 'source_id', 'source_category', 'tag', 'rarity', 'rarity_label', 'severity',
    'base_chance', 'final_chance', 'unclamped_chance', 'positive_factors', 'negative_factors', 'factors',
    'chance_required', 'roll', 'danger_chance', 'rating_before', 'rating_after', 'rating_change',
    'score_delta', 'events_score_delta', 'boosted_profession_tags', 'boosted_tags', 'boost_score',
    'boost_reason', 'pity_bonus_active', 'survival_percent', 'survival_score', 'success_threshold',
    'score_components', 'age_care', 'coverage', 'contributors', 'max_percent', 'percent',
    'on_success', 'on_failure', 'requirements', 'requirements_desc', 'key_needs',
}


def assert_public(value):
    if isinstance(value, dict):
        assert not PRIVATE_FIELDS.intersection(value), PRIVATE_FIELDS.intersection(value)
        for child in value.values():
            assert_public(child)
    elif isinstance(value, list):
        for child in value:
            assert_public(child)


def room(mode='immersion', started=True, n=6):
    r = BunkerGameRoom('I444', 'p0', 'Алекс')
    for i in range(1, n):
        r.add_player(f'p{i}', f'Игрок {i}')
    r.update_lobby_settings('p0', {'information_mode': mode, 'show_prologue': False})
    if started:
        r.start_configured_game('p0', r.lobby_revision)
    return r


def event(r, surface=False):
    kind = 'SURFACE_EVENT' if surface else 'BUNKER_CRISIS'
    r.active_event = copy.deepcopy(next(e for e in deck_data.BUNKER_EVENTS if e['type'] == kind))
    r.assigned_volunteer_id = 'p0'
    r.recalculate_event_odds()


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('viewer', ['p0', 'p1', 'observer', None])
def test_every_viewer_has_same_policy_without_model_fields(mode, viewer):
    r = room(mode);event(r, surface=True)
    g = r.get_state(viewer)
    assert_public(g)
    assert g['information_mode'] == mode and g['match_settings']['information_mode'] == mode
    if mode == 'uncertainty':
        assert g['events_state']['current_odds'] is None
    else:
        assert g['events_state']['current_odds']['level'] in ('low', 'medium', 'high')
        assert set(g['events_state']['current_odds']) == {'level', 'label', 'description'}
    own = next(p for p in g['players'] if p['id'] == 'p0')['cards']
    if viewer == 'p0':
        assert own['gender']['age'] == r.players['p0'].cards['gender']['age']
    else:
        assert 'age' not in own['gender']


@pytest.mark.parametrize('mode', MODES)
def test_lobby_readiness_authority_freeze_and_old_profile(mode):
    r = room(started=False)
    r.set_lobby_ready('p1', True, r.lobby_revision)
    r.update_lobby_settings('p0', {'information_mode': mode}, r.lobby_revision)
    if mode == 'uncertainty':
        assert not r.lobby_ready
    with pytest.raises(ValueError):
        r.update_lobby_settings('p1', {'information_mode': mode})
    r.start_configured_game('p0')
    with pytest.raises(ValueError):
        r.update_lobby_settings('p0', {'information_mode': 'uncertainty'})
    # Frozen snapshot, not a reference to the lobby dictionary.
    r.lobby_settings['information_mode'] = 'immersion' if mode == 'uncertainty' else 'uncertainty'
    assert r.get_state('p0')['information_mode'] == mode
    assert validate_settings({'speech_duration': 60})['information_mode'] == 'immersion'


@pytest.mark.parametrize('value', ['debug', 'numbers', '', None, True, 1, [], {}, 'UNKNOWN'])
def test_invalid_policy_is_atomic(value):
    r = room(started=False);before = copy.deepcopy(r.lobby_settings);revision = r.lobby_revision
    with pytest.raises(ValueError):
        r.update_lobby_settings('p0', {'information_mode': value}, revision)
    assert r.lobby_settings == before and r.lobby_revision == revision


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('preset', list(PRESETS))
def test_modes_work_with_every_preset(preset, mode):
    r = room(started=False)
    r.update_lobby_settings('p0', {**PRESETS[preset], 'information_mode': mode})
    r.start_configured_game('p0')
    assert r.match_settings['preset'] == preset
    assert r.get_state('p0')['information_mode'] == mode


@pytest.mark.parametrize('chance,level', [(0,'low'), (39,'low'), (40,'medium'), (69,'medium'), (70,'high'), (100,'high')])
def test_coarse_odds_boundaries_never_reveal_value(chance, level):
    p = public_odds({'final_chance': chance, 'base_chance': 33}, 'immersion')
    assert p['level'] == level and set(p) == {'level', 'label', 'description'}
    assert public_odds({'final_chance': chance}, 'uncertainty') is None
    assert public_odds({'final_chance': chance}, 'immersion', skipped=True) is None


@pytest.mark.parametrize('value', [None, '40', float('nan'), float('inf')])
def test_invalid_odds_do_not_invent_a_rating(value):
    assert public_odds({'final_chance': value}, 'immersion') is None


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('roll', [1, 50, 99])
def test_reviews_history_final_and_log_never_expose_calculations(mode, roll):
    r = room(mode);event(r)
    r.resolve_active_event(force_roll=roll)
    for viewer in ('p0', 'p1', None):
        g = r.get_state(viewer);assert_public(g)
        review = g['result_review'];assert review['seconds_left'] == 5
        assert review['data']['outcome'] and review['next_label']
        assert g['events_state']['resolved_history'][0]['result']['outcome']
        assert 'd100' not in json.dumps(g['game_log'], ensure_ascii=False)
    for _ in range(5):
        r.tick_result_review()
    r.trigger_final();g = r.get_state('p1');assert_public(g)
    assert len(g['final_evaluation']['breakdown']['needs']) == 5
    assert all(n['status'] for n in g['final_evaluation']['breakdown']['needs'].values())
    assert r.final_evaluation['survival_score'] >= 0  # Underlying numeric model still exists.


@pytest.mark.parametrize('mode', MODES)
def test_cancelled_and_guaranteed_results_keep_unambiguous_meaning(mode):
    r = room(mode);event(r, surface=True);r.skip_sortie(True);r.resolve_active_event()
    result = r.get_state('p0')['result_review']['data']
    assert result['outcome'] == 'Вылазка отменена' and result['is_skipped']
    assert_public(result)
    r.result_reviews.clear();event(r);r.resolve_active_event(guaranteed_success=True)
    result = r.get_state('p0')['result_review']['data']
    assert result['guaranteed_success'] and result['is_success'] and not result['is_crit_success']
    assert_public(result)


@pytest.mark.parametrize('mode', MODES)
def test_hidden_health_and_peek_are_not_leaked_to_other_viewers(mode):
    r = room(mode);event(r, surface=True)
    result = {'event_id': 'surface', 'event_title': 'Вылазка', 'is_success': False, 'roll': 99,
              'score_delta': -6, 'chance_required': 60,
              'health_degraded': {'player_id': 'p0', 'player_name': 'Алекс', 'new_condition': 'PRIVATE_HEALTH',
                                  'danger_chance': 60, 'roll': 1}}
    r.players['p0'].cards['health']['revealed'] = False
    r.players['p0'].last_peeked = {'target_id': 'p1', 'target_name': 'Другой игрок', 'category': 'health',
                                  'value': 'PRIVATE_PEEK', 'mechanics': {'secret': 12}}
    r.last_resolved_event = result;r.present_event_result(result, r.active_event, 0, 'p0')
    for viewer in ('p1', 'observer', None):
        text = json.dumps(r.get_state(viewer), ensure_ascii=False)
        assert 'PRIVATE_HEALTH' not in text and 'PRIVATE_PEEK' not in text
    own = r.get_state('p0');assert_public(own)
    assert own['result_review']['data']['health_degraded']['new_condition'] == 'PRIVATE_HEALTH'
    assert own['players'][0]['last_peeked']['target_name'] == 'Другой игрок'


@pytest.mark.parametrize('mode', MODES)
def test_weighted_ballots_keep_counts_without_percentages(mode):
    r = room(mode);r.start_voting();r.players['p0'].double_vote = True
    for pid, target in zip(r.players, ['p1', 'p1', 'p1', 'p2', 'p2', 'p2']):
        r.cast_vote(pid, target)
    summary = r.get_state('p2')['result_review']['data'];assert_public(summary)
    assert summary['counts']['total_weight'] == 7 and summary['required_votes'] == 5
    assert summary['top_votes'] == 4 and summary['decision'] == 'defense'
    assert sorted(row['votes'] for row in summary['detailed_tally']) == [3, 4]


@pytest.mark.parametrize('mode', MODES)
def test_projection_does_not_mutate_model_rng_or_other_views(mode):
    r = room(mode);event(r, True)
    before = copy.deepcopy(r.__dict__);rng = random.getstate()
    for viewer in ('p0', 'p1', None):
        g = r.get_state(viewer)
        g['players'][0]['cards']['gender']['age'] = 999
        g['events_state']['active_event']['title'] = 'CHANGED'
    assert r.players['p0'].cards == before['players']['p0'].cards
    assert r.active_event == before['active_event'] and r.current_event_odds == before['current_event_odds']
    assert r.match_settings == before['match_settings'] and random.getstate() == rng


def test_modes_do_not_change_balance_or_outcomes():
    results = []
    for mode in MODES:
        random.seed(9044);r = room(mode);event(r)
        odds = copy.deepcopy(r.current_event_odds)
        r.resolve_active_event(force_roll=50);r.trigger_final()
        results.append((odds, r.last_resolved_event['is_success'], r.final_evaluation))
    assert results[0] == results[1]


def test_all_event_and_special_definitions_have_safe_descriptions():
    for ev in deck_data.BUNKER_EVENTS:
        assert_public(public_event(ev))
        for key in ('on_success', 'on_failure'):
            outcome = ev.get(key, {})
            result = public_event_result({**outcome, 'event_title': ev['title'], 'is_success': key == 'on_success'})
            assert_public(result)
            assert 'скрытого бонуса профессиям' not in result.get('description', '')
    for special in deck_data.SPECIAL_CARDS:
        card = public_card({'category': 'special', 'card_id': special['id'], 'details': special['desc']}, 'special')
        assert_public(card)
        text = card['details']
        assert 'п.п.' not in text and 'балл' not in text and '%' not in text, special['id']


def until(ws, predicate):
    for _ in range(120):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError('Expected protocol message was not received')


@pytest.mark.parametrize('mode', MODES)
def test_real_asgi_websockets_enforce_policy(mode, monkeypatch):
    monkeypatch.setattr(api, 'get_external_ip', lambda: None)
    monkeypatch.setattr(api, 'get_local_ip', lambda: '127.0.0.1')
    monkeypatch.setattr(api, 'generate_qr_data_url', lambda *a: '')
    client = TestClient(api.app)
    created = client.post('/api/room/create', json={'host_name': 'Policy host'}).json()
    code, host_id = created['room_code'], created['host_id']
    guests = [client.post('/api/room/join', json={'room_code': code, 'player_name': f'Guest {i}'}).json()['player_id'] for i in range(2)]
    try:
        catalog = client.get('/api/lobby-options').json()
        assert catalog['defaults']['information_mode'] == 'immersion'
        assert {m['id'] for m in catalog['information_modes']} == set(MODES)
        assert_public(catalog['catastrophes'])
        with ExitStack() as stack:
            sockets = [stack.enter_context(client.websocket_connect(f'/ws/{code}/{pid}')) for pid in [host_id, *guests]]
            host, guest = sockets[:2]
            guest.send_json({'action': 'UPDATE_LOBBY_SETTINGS', 'payload': {'settings': {'information_mode': mode}}})
            until(guest, lambda m: m.get('type') == 'ERROR' and m.get('action') == 'UPDATE_LOBBY_SETTINGS')
            host.send_json({'action': 'UPDATE_LOBBY_SETTINGS', 'payload': {'settings': {'information_mode': mode, 'show_prologue': False}}})
            until(host, lambda m: m.get('type') == 'ACTION_OK' and m.get('action') == 'UPDATE_LOBBY_SETTINGS')
            host.send_json({'action': 'START_GAME', 'payload': {}})
            for ws in sockets:
                g = until(ws, lambda m: m.get('type') == 'STATE_UPDATE' and m['state']['phase'] == 'REVEAL')['state']
                assert g['information_mode'] == mode;assert_public(g)
            host.send_json({'action': 'UPDATE_LOBBY_SETTINGS', 'payload': {'settings': {'information_mode': 'immersion'}}})
            until(host, lambda m: m.get('type') == 'ERROR' and m.get('action') == 'UPDATE_LOBBY_SETTINGS')
            host.send_json({'action': 'HOST_TRIGGER_EVENT', 'payload': {}})
            for ws in sockets:
                g = until(ws, lambda m: m.get('type') == 'STATE_UPDATE' and m['state']['events_state']['active_event'])['state']
                assert_public(g)
                assert (g['events_state']['current_odds'] is None) == (mode == 'uncertainty')
            # Reconnect joins the same frozen policy; no debug data is resent.
            with client.websocket_connect(f'/ws/{code}/{guests[1]}') as again:
                g = until(again, lambda m: m.get('type') == 'STATE_UPDATE')['state']
                assert g['information_mode'] == mode;assert_public(g)
    finally:
        api.rooms.pop(code, None);api.connections.pop(code, None);client.close()


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('expel', [False, True])
def test_automatic_event_after_vote_has_no_numeric_log_leaks(mode, expel):
    r = room(mode); event(r)
    r.phase = 'VOTE_RESULTS'
    r.vote_results = {'eliminated_id': 'p1' if expel else None}
    r.confirm_elimination()
    assert r.last_resolved_event is not None
    g = r.get_state('p0'); assert_public(g)
    text = json.dumps([row for row in g['game_log'] if row.get('title', '').startswith(('ИСПЫТАНИЕ ПОСЛЕ', 'ИСПЫТАНИЕ РАУНДА'))], ensure_ascii=False)
    assert text != '[]'
    assert '%' not in text
    # This guard also covers legacy log consumers, not just current public DTOs.
    text = json.dumps([row for row in r.game_log if row.get('title', '').startswith(('ИСПЫТАНИЕ ПОСЛЕ', 'ИСПЫТАНИЕ РАУНДА'))], ensure_ascii=False)
    assert '%' not in text
