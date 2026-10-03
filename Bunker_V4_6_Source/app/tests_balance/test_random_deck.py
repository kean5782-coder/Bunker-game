"""The party dealer must not quietly repair inconvenient combinations."""
import copy
import random
from collections import Counter
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from server import deck_data as d, balance, special_cards
from server import app as api
from server.character_cards import CARD_EFFECTS
from server.game_engine import BunkerGameRoom
from server.lobby import DEFAULTS, PRESETS, validate_settings


def room():
    result = BunkerGameRoom('RAND', 'host', 'Ведущий')
    for i in range(1, 6):
        result.add_player(str(i), f'Игрок {i}')
    return result


def test_full_random_is_default_for_new_rooms_presets_and_dealer():
    assert DEFAULTS['deal_mode'] == 'full_random'
    assert all(p['deal_mode'] == 'full_random' for p in PRESETS.values())
    r = room()
    r.start_configured_game('host')
    assert r.match_settings['deal_mode'] == 'full_random'
    assert d.generate_game_deck(6)['deal_mode'] == 'full_random'


@pytest.mark.parametrize('n', [1, 3, 6, 12, 20])
@pytest.mark.parametrize('events', [True, False])
def test_random_deals_are_complete_distinct_and_do_not_use_weights(n, events):
    with patch.object(d.random, 'choices', side_effect=AssertionError('Weighted draw')):
        deck = d.generate_game_deck(n, enable_events=events)
    cards = deck['players_cards']
    assert len(cards) == n
    for category in ('profession', 'health', 'body', 'trait', 'hobby', 'phobia', 'big_inventory', 'backpack', 'fact'):
        ids = [c[category]['source_id'] for c in cards]
        assert None not in ids and len(set(ids)) == n
    ids = [special_cards.canonical(c['special']['card_id']) for c in cards]
    assert len(set(ids)) == n
    if not events:
        assert not any(cid.startswith('event_') for cid in ids)


def test_all_weak_and_critical_table_is_left_alone():
    # A deliberately disastrous set is valid. This catches quotas, mandatory
    # specialists AND compensation, independently of any particular RNG seed.
    weak = [p for p in d.PROFESSIONS if p['tag'] == 'useless']
    critical = [p for p in d.HEALTH_CONDITIONS if p['severity'] == 'critical']
    neutral_hobbies = [p for p in d.HOBBIES if CARD_EFFECTS['hobby'][p['name']]['roleplay_only']]
    neutral_items = [p for p in d.BACKPACK_ITEMS if CARD_EFFECTS['backpack'][p['name']]['roleplay_only']]
    with patch.object(d, 'PROFESSIONS', weak), patch.object(d, 'HEALTH_CONDITIONS', critical), \
         patch.object(d, 'HOBBIES', neutral_hobbies), patch.object(d, 'BACKPACK_ITEMS', neutral_items), \
         patch.object(balance, 'effects_for_card', wraps=balance.effects_for_card) as effects:
        cards = d.generate_game_deck(6)['players_cards']
    assert all(c['profession']['tag'] == 'useless' and c['health']['severity'] == 'critical' for c in cards)
    assert all(not c[k]['mechanics']['skills'] for c in cards for k in ('hobby', 'backpack'))
    # Compensation queries raw pool rows; normal decoration queries dealt cards.
    assert all('name' not in call.args[0] for call in effects.call_args_list)


def test_specials_have_equal_sampling_in_random_mode():
    # extra_bunk used to get a separate 40% draw, unlike every other effect.
    original = random.sample
    pools = []
    def observe(population, k):
        if population and isinstance(population[0], dict) and 'phase' in population[0]:
            pools.append({special_cards.canonical(c['id']) for c in population})
        return original(population, k)
    with patch.object(d.random, 'sample', side_effect=observe):
        d.generate_game_deck(6)
    assert len(pools) == 1 and 'extra_bunk' in pools[0]
    assert pools[0] == set(special_cards.DEFINITIONS)


def test_random_tables_really_can_miss_specialists_and_exceed_old_health_limits():
    random.seed(71026)
    seen = Counter()
    for _ in range(200):
        cards = d.generate_game_deck(6)['players_cards']
        tags = [c['profession']['tag'] for c in cards]
        seen['no_medic'] += 'medicine' not in tags
        seen['no_tech'] += not set(tags) & {'engineering', 'tech', 'science'}
        seen['many_weak'] += tags.count('useless') > 1
        seen['many_critical'] += sum(c['health']['severity'] == 'critical' for c in cards) > 1
    assert all(seen[key] > 0 for key in ('no_medic', 'no_tech', 'many_weak', 'many_critical'))


@pytest.mark.parametrize('deal_mode', ['full_random', 'balanced'])
def test_lobby_mode_reaches_dealer_and_is_frozen(deal_mode):
    r = room()
    r.update_lobby_settings('host', {'deal_mode': deal_mode})
    with patch('server.game_engine.generate_game_deck', wraps=d.generate_game_deck) as draw:
        r.start_configured_game('host')
    assert draw.call_args.kwargs['deal_mode'] == deal_mode
    assert r.match_settings['deal_mode'] == deal_mode
    with pytest.raises(ValueError):
        r.update_lobby_settings('host', {'deal_mode': 'balanced'})


def test_saved_mode_applies_to_direct_engine_start():
    r = room()
    r.update_lobby_settings('host', {'deal_mode': 'balanced'})
    with patch('server.game_engine.generate_game_deck', wraps=d.generate_game_deck) as draw:
        r.start_game()
    assert draw.call_args.kwargs['deal_mode'] == 'balanced'


@pytest.mark.parametrize('bad_mode', ['random', '', None, 1, True, []])
def test_bad_mode_is_rejected_without_mutating_room(bad_mode):
    r = room()
    before = copy.deepcopy(r.lobby_settings)
    with pytest.raises(ValueError):
        r.update_lobby_settings('host', {'deal_mode': bad_mode})
    assert r.lobby_settings == before
    with pytest.raises(ValueError):
        d.generate_game_deck(6, deal_mode=bad_mode)


@pytest.mark.parametrize('mode', [None, 'full_random', 'balanced', 'bad'])
def test_http_create_room_accepts_and_validates_mode(mode):
    payload = {'host_name': 'Тест'}
    if mode is not None:
        payload['deal_mode'] = mode
    with TestClient(api.app) as client:
        response = client.post('/api/room/create', json=payload)
    if mode == 'bad':
        assert response.status_code == 400
        return
    assert response.status_code == 200, response.text
    code = response.json()['room_code']
    try:
        assert api.rooms[code].lobby_settings['deal_mode'] == (mode or 'full_random')
    finally:
        api.rooms.pop(code, None)
        api.connections.pop(code, None)


def test_old_profiles_get_default_and_new_profiles_round_trip():
    old = {k: v for k, v in DEFAULTS.items() if k != 'deal_mode'}
    assert validate_settings(old)['deal_mode'] == 'full_random'
    custom = {**DEFAULTS, 'deal_mode': 'balanced', 'preset': 'custom'}
    assert validate_settings(custom) == custom


def test_catalog_has_explicit_effects_and_readable_unique_cards():
    pools = {'profession': d.PROFESSIONS, 'health': d.HEALTH_CONDITIONS,
             'body': d.BODY_BUILDS, 'trait': d.HUMAN_TRAITS, 'phobia': d.PHOBIAS,
             'big_inventory': d.BIG_INVENTORY, 'backpack': d.BACKPACK_ITEMS,
             'hobby': d.HOBBIES, 'fact': d.FACTS}
    for category, rows in pools.items():
        assert len(rows) >= 25
        assert len({r['name'] for r in rows}) == len(rows)
        for row in rows:
            assert row['name'].strip() and row['desc'].strip()
            assert len(row['desc']) <= 220
            effect = balance.CATALOG['cards'][category][row['name']]
            assert effect['id'] and set(effect['skills']) <= set(balance.SKILL_LABELS)
            assert set(effect['traits'] + effect['risks'] + effect['protection']) <= set(balance.CONTEXT_LABELS)
    assert len(d.BIG_INVENTORY) > 35 and len(d.BACKPACK_ITEMS) > 35
    for name in ('Коробка резиновых уток', 'Манекен по пояс', 'Портрет самого себя'):
        assert CARD_EFFECTS['big_inventory'][name]['roleplay_only']
    assert CARD_EFFECTS['big_inventory']['Чемодан с инструментами']['skills']


def test_new_cards_are_used_in_rerolls_too():
    deck = d.generate_game_deck(6)
    for category in CARD_EFFECTS:
        old = deck['players_cards'][0][category]
        new = special_cards.new_card(category, old)
        assert new['source_id'] in {e['id'] for e in CARD_EFFECTS[category].values()}
        assert new['value'] != old['value']
