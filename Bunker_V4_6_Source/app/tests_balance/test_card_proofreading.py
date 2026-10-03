"""Regressions for generated Russian text and card/action contradictions."""
import copy
import json
import random
from unittest.mock import patch

import pytest

from server import balance, deck_data as d, special_cards as sc
from server.card_text import gender_age_title
from server.game_engine import BunkerGameRoom
from server.presentation import public_card


def game():
    result = BunkerGameRoom('WORDS', 'p0', 'Ведущий')
    for i in range(1, 4):
        result.add_player(f'p{i}', f'Игрок {i}')
    result.start_game(capacity=2, enable_events=True)
    result.phase = 'REVEAL'
    result.result_review = None
    return result


def give_special(player, key):
    player.cards['special'] = {
        'category': 'special', 'card_id': key, 'value': sc.TITLES[key],
        'used': False, 'revealed': False,
    }


def pool_card(row, category):
    return balance.decorate_card({
        'category': category, 'value': row['name'], 'details': row['desc'],
        'revealed': False, **({'severity': row['severity']} if category == 'health' else {}),
    }, category)


@pytest.mark.parametrize('age, unit', [
    (11, 'лет'), (12, 'лет'), (14, 'лет'), (16, 'лет'), (20, 'лет'),
    (21, 'год'), (22, 'года'), (24, 'года'), (25, 'лет'), (31, 'год'),
    (64, 'года'), (100, 'лет'), (101, 'год'), (111, 'лет'), (114, 'лет'),
])
def test_age_inflection(age, unit):
    assert gender_age_title('Женщина', age) == f'Женщина, {age} {unit}'


@pytest.mark.parametrize('mode', ['full_random', 'balanced'])
def test_deals_and_replacements_use_age_inflection(mode):
    random.seed(71)
    for _ in range(20):
        for cards in d.generate_game_deck(20, deal_mode=mode)['players_cards']:
            for c in (cards['gender'], sc.new_card('gender', cards['gender'])):
                assert c['value'] == gender_age_title(c['gender'], c['age'])


def test_gender_reroll_excludes_same_character_in_old_and_new_format():
    same = {'gender': 'Женщина', 'age': 24, 'orientation': '', 'reproduction': ''}
    different = {**same, 'age': 31}
    for old in ({'value': 'Женщина, 24 лет'}, {'value': 'Женщина, 24 года', 'gender': 'Женщина', 'age': 24}):
        with patch.object(d, 'GENDER_TRAITS', [same, different]):
            new = sc.new_card('gender', old)
        assert new['value'] == 'Женщина, 31 год'


def test_implausible_experience_stays_random_but_is_a_claim_in_deal_and_reroll():
    # Force the inconvenient combination without depending on an RNG seed.
    with patch.object(d, 'EXPERIENCE_PRESETS', ['двадцать лет опыта']), \
         patch.object(d.random, 'randint', return_value=0), \
         patch.object(d, 'GENDER_TRAITS', [
             {'gender': 'Женщина', 'age': 16, 'orientation': '', 'reproduction': ''},
         ]):
        cards = d.generate_game_deck(1, enable_traitor=False)['players_cards'][0]
        rerolled = sc.new_card('profession', cards['profession'])
    assert cards['gender']['age'] == 16
    for profession in (cards['profession'], rerolled):
        assert '(по собственным словам: двадцать лет опыта)' in profession['value']
        assert profession['source_id'] in {
            e['id'] for e in balance.CARD_EFFECTS['profession'].values()
        }


@pytest.mark.parametrize('row', d.PHOBIAS, ids=lambda row: row['name'])
def test_any_phobia_can_be_cured_once_including_roleplay_only(row):
    r = game()
    actor, target = r.players['p0'], r.players['p1']
    target.cards['phobia'] = pool_card(row, 'phobia')
    give_special(actor, 'cure_phobia')
    assert target.id in sc.special_availability(r, actor.id)['target_ids']
    r.use_special_card(actor.id, target_player_id=target.id)
    cured = target.cards['phobia']
    assert cured['revealed'] and cured['cured']
    assert cured['value'] == 'Фобия излечена'
    assert not balance.effects_for_card(cured, 'phobia').get('risks')
    give_special(actor, 'cure_phobia')
    assert target.id not in sc.special_availability(r, actor.id)['target_ids']
    with pytest.raises(ValueError, match='нет действующей фобии'):
        r.use_special_card(actor.id, target_player_id=target.id)
    assert not actor.cards['special']['used']
    replacement = sc.new_card('phobia', cured)
    target.cards['phobia'] = replacement
    assert not replacement.get('cured')
    assert target.id in sc.special_availability(r, actor.id)['target_ids']


def test_legacy_cured_phobia_is_not_treated_again():
    r = game()
    actor, target = r.players['p0'], r.players['p1']
    target.cards['phobia'] = {'value': 'Фобия излечена', 'mechanics': {}}
    give_special(actor, 'cure_phobia')
    assert target.id not in sc.special_availability(r, actor.id)['target_ids']


def test_raincoat_does_not_save_an_exile_or_protect_from_flood_hazard():
    row = next(x for x in d.BACKPACK_ITEMS if x['name'] == 'Дождевик')
    raincoat = pool_card(row, 'backpack')
    raincoat['revealed'] = True
    cards = {'backpack': raincoat}
    flood = {'id': 'global_flood'}
    assert not balance.is_exile_alive_on_surface({'cards': cards}, flood)['is_alive_surface']
    assert not balance.has_hazard_protection(cards, flood)


def test_repeated_partial_treatment_updates_current_text_and_preserves_effects():
    r = game()
    actor, target = r.players['p0'], r.players['p1']
    row = next(x for x in d.HEALTH_CONDITIONS if x['name'] == 'Тяжёлое обострение астмы')
    target.cards['health'] = pool_card(row, 'health')
    original_effects = copy.deepcopy(target.cards['health']['mechanics'])
    titles = set()
    for severity in ('medium', 'minor', 'good'):
        give_special(actor, 'blood_transfusion')
        r.use_special_card(actor.id, target_player_id=target.id)
        current = target.cards['health']
        assert current['severity'] == severity and current['revealed']
        titles.add(current['value'])
        shown = json.dumps(public_card(current, 'health'), ensure_ascii=False)
        assert row['name'] not in shown and row['desc'] not in shown
        assert 'Тяжесть после лечения:' not in shown and 'health_before_treatment' not in shown
        assert current['mechanics'] == ({} if severity == 'good' else original_effects)
        assert current['health_before_treatment'] == {'value': row['name'], 'details': row['desc']}
    assert len(titles) == 3
    give_special(actor, 'blood_transfusion')
    with pytest.raises(ValueError, match='хорошее здоровье'):
        r.use_special_card(actor.id, target_player_id=target.id)
    assert not actor.cards['special']['used']


@pytest.mark.parametrize('severity', ['minor', 'medium', 'danger', 'critical'])
def test_full_healing_replaces_old_text_and_removes_penalties(severity):
    r = game()
    actor, target = r.players['p0'], r.players['p1']
    target.cards['health'] = {
        'category': 'health', 'value': 'Прежний диагноз', 'details': 'Прежние ограничения',
        'severity': severity, 'mechanics': {'risks': ['physical']}, 'revealed': False,
    }
    give_special(actor, 'heal_illness')
    r.use_special_card(actor.id, target_player_id=target.id)
    current = target.cards['health']
    assert current['severity'] == 'good' and current['mechanics'] == {}
    assert 'Прежний диагноз' not in current['value']
    assert 'Прежние ограничения' != current['details']


def test_health_setback_after_treatment_does_not_keep_recovery_text():
    r = game()
    actor, target = r.players['p0'], r.players['p1']
    row = next(x for x in d.HEALTH_CONDITIONS if x['severity'] == 'critical')
    target.cards = {'health': pool_card(row, 'health')}
    give_special(actor, 'blood_transfusion')
    r.use_special_card(actor.id, target_player_id=target.id)
    r.catastrophe = {'id': 'super_virus', 'title': 'Вирус', 'description': ''}
    r.active_event = {
        'id': 'health_setback', 'type': 'SURFACE_EVENT', 'title': 'Вылазка',
        'description': 'Поиск припасов', 'base_chance': 10,
        'rules': {'positive': [], 'negative': []},
        'on_success': {'score_delta': 4}, 'on_failure': {'score_delta': -4},
    }
    r.assigned_volunteer_id = target.id
    r.recalculate_event_odds()
    with patch('server.game_engine.random.randint', return_value=1):
        result = r.resolve_active_event(force_roll=99)
    assert result['health_degraded']
    current = target.cards['health']
    assert current['severity'] == 'critical'
    assert 'поправку' not in current['value'] and 'стало лучше' not in current['details']
    assert 'критическое' in current['details']
