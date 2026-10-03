"""Age V4 regressions: accounting, bounded costs, privacy and real effects."""
import copy
import json
import math
import random
from unittest.mock import patch

import pytest
from server import balance as b, deck_data as d, special_cards as sc
from server.age_balance import read_age, age_from_cards, base_care_load
from server.game_engine import BunkerGameRoom, Player

RULES = b.CONFIG['age_care']
CAT = {'duration_years': 5}
BUNK = {'capacity': 3, 'initial_capacity': 3, 'supplies_years': 5}


def person(age=30, severity='medium', pid='p', skills=None, endurance=False):
    return {'id': pid, 'name': 'Персонаж ' + pid, 'is_alive': True, 'cards': {
        'gender': {'category': 'gender', 'value': f'Женщина, {age} лет', 'age': age,
                   'gender': 'Женщина', 'orientation': 'Бисексуалка', 'reproduction': 'Бесплодна', 'revealed': False},
        'health': {'category': 'health', 'value': 'Fixture', 'severity': severity, 'mechanics': {}, 'revealed': True},
        'body': {'category': 'body', 'value': 'Fixture body', 'mechanics': {'traits': ['endurance'] if endurance else []}},
        'profession': {'category': 'profession', 'value': 'Fixture profession', 'mechanics': {'skills': skills or {}}}}}


def evaluate(ps, **kwargs):
    return b.evaluate_survival(ps, kwargs.get('cat', CAT), kwargs.get('bunk', BUNK))


def age_result(ps, **kwargs):
    return evaluate(ps, **kwargs)['breakdown']['age_care']


@pytest.mark.parametrize('age,expected', [(16,0),(35,0),(55,0),(56,.3),(59,1.2),(60,1.5),
    (63,2.4),(65,3),(66,3.3),(70,4.5),(72,5.1),(75,6),(80,8),(85,9),(90,10),(120,10)])
def test_age_curve_exact_and_continuous(age, expected):
    assert base_care_load(age, RULES) == pytest.approx(expected)


@pytest.mark.parametrize('value', [None, True, False, '', 'bad', 'NaN', float('nan'), float('inf'),
                                    -1, 121, 63.5, [], {}, '1e999'])
def test_invalid_age_never_inferred(value):
    assert read_age({'age': value, 'value': 'Мужчина, 88 лет'}) is None


@pytest.mark.parametrize('value', [0, 16, 55, 70, 120, ' 70 ', 70.0])
def test_structured_age_accepts_valid_numbers(value):
    assert read_age({'age': value}) == int(value)


@pytest.mark.parametrize('text,expected', [('Мужчина, 72 года',72),('Женщина, 61 год',61),
    ('Женщина, 69 лет',69),('Мужчина, 70.5 лет',None),('Рост 180 см',None),('Возраст неизвестен',None),('🔒 Скрыто',None)])
def test_legacy_age_parsed_only_from_explicit_age_phrase(text, expected):
    assert read_age({'value': text}) == expected


def test_no_double_charge_for_legacy_and_modern_cards():
    p = person(65)
    old = age_result([p])
    p['cards']['biology'] = {'age': 95}
    assert age_from_cards(p['cards']) == 65
    assert age_result([p]) == old
    del p['cards']['gender']
    assert age_result([p])['rows'][0]['age'] == 95


def test_age_only_card_dictionary_is_supported():
    assert b.evaluate_survival(survivor_cards_list=[{'gender': {'age': 70}}])['breakdown']['age_care']['penalty'] > 0


def test_exact_aggregate_formula_and_personal_sum():
    people = [person(65, 'good', 'a', endurance=True), person(75, 'medium', 'b'), person(35, 'minor', 'c')]
    result = evaluate(people)
    age = result['breakdown']['age_care']
    before = (3*.8*.9 + 6) / 3**.35
    reduction = .45*result['breakdown']['needs']['medicine']['coverage'] + .15*result['breakdown']['needs']['social']['coverage']
    assert age['penalty'] == round(before*(1-reduction), 2)
    assert sum(p['penalty'] for p in age['rows']) == pytest.approx(age['penalty'])
    assert result['breakdown']['score_components']['age_care'] == -age['penalty']
    assert result['breakdown']['score_components']['raw'] == pytest.approx(age['raw_without_age']-age['penalty'], abs=.001)


def test_no_penalty_for_young_or_missing_age():
    ps = [person(55), person(30, pid='q')]
    ps[1]['cards'].pop('gender')
    age = age_result(ps)
    assert age['penalty'] == 0 and age['unknown_age_count'] == 1
    assert age['rating_without_age'] == evaluate(ps)['survival_score']


def test_same_cards_get_monotonic_age_cost():
    scores = []; costs = []
    for age in range(16, 121):
        result = evaluate([person(age), person(30,pid='q'), person(30,pid='r')])
        scores.append(result['breakdown']['score_components']['raw'])
        costs.append(result['breakdown']['age_care']['penalty'])
    assert all(x >= y for x,y in zip(scores,scores[1:]))
    assert all(x <= y for x,y in zip(costs,costs[1:]))


def test_sex_orientation_fertility_do_not_change_any_numerical_component():
    p = person(72); baseline = evaluate([p])
    p['cards']['gender'].update(gender='Мужчина',orientation='Гетеросексуал',reproduction='Фертилен',value='Мужчина, 72 года')
    result = evaluate([p])
    assert result['breakdown']['score_components'] == baseline['breakdown']['score_components']
    assert result['breakdown']['age_care'] == baseline['breakdown']['age_care']


def test_health_and_endurance_mitigate_not_multiply_sickness():
    neutral = age_result([person(75)])['penalty']
    assert age_result([person(75,'good')])['penalty'] == pytest.approx(neutral*.8, abs=.01)
    assert age_result([person(75,'minor')])['penalty'] == pytest.approx(neutral*.9, abs=.01)
    assert age_result([person(75,'critical')])['penalty'] == neutral
    assert age_result([person(75,endurance=True)])['penalty'] == pytest.approx(neutral*.9, abs=.01)


def test_missing_health_does_not_mean_healthy():
    p = person(70); neutral = age_result([p])['penalty']
    p['cards'].pop('health')
    assert age_result([p])['penalty'] == neutral


def test_medicine_social_and_facility_relief():
    target=person(75); base=age_result([target])['penalty']
    target['cards']['profession']['mechanics']['skills']={'medicine':1,'social':1}
    assert age_result([target])['penalty'] < base
    bunk={**BUNK,'name':'Законсервированный подземный спецгоспиталь МЧС'}
    assert age_result([person(75)],bunk=bunk)['penalty'] < base


def test_inventory_relief_and_destruction_use_explicit_properties():
    p=person(75); old=age_result([p])['penalty']
    p['cards']['backpack']={'mechanics':{'skills':{'medicine':1}},'value':'Аптечка'}
    assert age_result([p])['penalty'] < old
    p['cards']['backpack']['destroyed']=True
    assert age_result([p])['penalty'] == old
    p['cards']['backpack']={'value':'Неизвестная батарейка','details':'больница, врач, уход, медицина'}
    assert age_result([p])['penalty'] == old


def test_no_fitness_from_flavour_or_destroyed_card():
    p=person(75); old=age_result([p])['penalty']
    p['cards']['body']={'value':'Неизвестная фигура','details':'атлет, выносливый'}
    assert age_result([p])['penalty'] == old
    p['cards']['body']={'mechanics':{'traits':['endurance']},'destroyed':True}
    assert age_result([p])['penalty'] == old


def test_isolation_modifier_is_bounded_and_not_automatic_death():
    short=age_result([person(70)],cat={'duration_years':3})
    normal=age_result([person(70)],cat={'duration_years':5})
    long=age_result([person(70)],cat={'duration_years':8})
    extreme=age_result([person(70)],cat={'duration_years':1000})
    assert short['penalty'] == normal['penalty']
    assert long['duration_multiplier'] == 1.075 and long['penalty'] > normal['penalty']
    assert extreme['duration_multiplier'] == 1.25


@pytest.mark.parametrize('size', [1,2,3,4,6,10,20])
def test_caps_population_and_rounding(size):
    ps=[person(120,pid=str(i)) for i in range(size)]
    age=age_result(ps)
    assert age['population']==size and 0 <= age['penalty'] <= 12
    assert sum(row['penalty'] for row in age['rows']) == pytest.approx(age['penalty'])
    if size >= 2: assert age['cap_applied'] and age['penalty']==12


def test_no_survivors_and_exiles_do_not_add_age_cost():
    assert evaluate([])['survival_score']==0 and age_result([])['penalty']==0
    exile=person(120);exile['is_alive']=False
    assert age_result([exile])['population']==0
    assert evaluate([exile])['survival_score']==0


def test_medical_profession_survives_age_tradeoff():
    others=[person(30,pid='a',skills={'engineering':1}),person(30,pid='b',skills={'food':1})]
    old_doctor=evaluate(others+[person(70,'good',pid='c',skills={'medicine':1},endurance=True)])
    young_unskilled=evaluate(others+[person(25,'good',pid='c',endurance=True)])
    assert old_doctor['survival_score'] > young_unskilled['survival_score']
    assert old_doctor['breakdown']['needs']['medicine']['team'] == 1


def test_all_event_odds_unchanged_by_age():
    p=person(20,skills={'engineering':1,'medicine':1})
    p['cards']['profession']['revealed']=True;p['cards']['gender']['revealed']=True
    for ev in d.BUNKER_EVENTS:
        before=b.calculate_event_odds(ev,[p],[],volunteer_id=p['id'])
        p['cards']['gender']['age']=100
        assert b.calculate_event_odds(ev,[p],[],volunteer_id=p['id'])==before
        p['cards']['gender']['age']=20


def test_no_randomness_mutation_or_double_charge():
    ps=[person(70),person(80,pid='q')];before=copy.deepcopy(ps);rng=random.getstate()
    one=evaluate(ps);two=evaluate(ps)
    assert one==two and ps==before and random.getstate()==rng
    json.dumps(one,ensure_ascii=False,allow_nan=False)


def make_room():
    random.seed(7012)
    r=BunkerGameRoom('AGE4','p0','Алекс')
    for i in range(1,6):r.add_player('p'+str(i),'Игрок '+str(i))
    r.start_game(capacity=3,enable_events=True)
    p=r.players['p0'];p.cards['gender'].update(age=78,value='Мужчина, 78 лет')
    b.decorate_card(p.cards['gender'],'gender')
    return r


def test_hidden_age_and_mechanics_not_in_public_state_before_final():
    r=make_room();guest=r.get_state('p1');own=r.get_state('p0')
    hidden=next(p for p in guest['players'] if p['id']=='p0')['cards']['gender']
    assert 'age' not in hidden and 'mechanics_text' not in hidden
    assert guest['final_evaluation'] is None
    actual=next(p for p in own['players'] if p['id']=='p0')['cards']['gender']
    assert actual['age']==78 and 'mechanics_text' not in actual
    assert 'нагрузка' in r.players['p0'].cards['gender']['mechanics_text']
    assert 'нагрузка' not in json.dumps(hidden,ensure_ascii=False)
    r.players['p0'].cards['gender']['revealed']=True
    public=next(p for p in r.get_state('p1')['players'] if p['id']=='p0')['cards']['gender']
    assert public['age']==78


def test_final_uses_survivors_and_actual_current_cards():
    r=make_room()
    for i in range(3,6):r.players['p'+str(i)].is_alive=False
    r.trigger_final();final=r.get_state('p1')['final_evaluation'];age=r.final_evaluation['breakdown']['age_care']
    assert 'age_care' not in final['breakdown'] and final['care_note']
    assert age['population']==3 and len(age['rows'])==3
    assert age['rows'][0]['age']==78 and age['penalty']>0
    assert not any(row['player_id']=='p5' for row in age['rows'])
    assert 'Возрастная нагрузка' in ' '.join(r.final_evaluation['cons'])
    assert not any('балл' in item for item in final['cons'])


def test_healing_and_reroll_are_not_stale():
    r=make_room();p=r.players['p0'];p.cards['health'].update(severity='critical',mechanics={})
    old=b.evaluate_survival(r.get_alive_players(),r.catastrophe,r.bunker)['breakdown']['age_care']['penalty']
    scard=next(c for c in d.SPECIAL_CARDS if c['id']=='heal_illness')
    p.cards['special']={'card_id':'heal_illness','value':scard['title'],'used':False}
    r.phase=sc.DEFINITIONS['heal_illness'][0][0]
    r.use_special_card(p.id,p.id)
    assert p.cards['health']['severity']=='good'
    new=b.evaluate_survival(r.get_alive_players(),r.catastrophe,r.bunker)['breakdown']['age_care']['penalty']
    assert new<old
    with patch.object(sc.random,'choice',return_value=d.GENDER_TRAITS[0]):
        p.cards['gender']=sc.new_card('gender',p.cards['gender'])
    assert p.cards['gender']['age']==20 and 'нагрузка ухода 0' in p.cards['gender']['mechanics_text']
    assert b.evaluate_survival([p])['breakdown']['age_care']['penalty']==0


def test_config_knots_and_scope():
    xs=[r[0] for r in RULES['age_knots']];ys=[r[1] for r in RULES['age_knots']]
    assert xs==sorted(set(xs)) and ys==sorted(ys)
    assert RULES['support_reduction_cap']<1 and RULES['final_penalty_cap']<=12
    assert age_result([person(70)])['applies_to']=='final_rating_only'
