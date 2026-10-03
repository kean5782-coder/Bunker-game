"""Independent regressions for Balance 2.0. No network, UI or mocks of calculations."""
import copy
import json
import math
import random
from unittest.mock import patch
import pytest
from server import deck_data as d
from server.game_engine import BunkerGameRoom, Player
from server import balance as b
from server import special_cards as sc


def room(n=6, events=False):
    random.seed(12345)
    r=BunkerGameRoom('BAL','p0','Player 0')
    for i in range(1,n): r.add_player(f'p{i}',f'Player {i}')
    r.start_game(capacity=max(1,n//2),enable_events=events)
    return r


def card(category, skills=None, **effects):
    return {'category':category,'value':'Fixture '+category,'label':category,'details':'Test fixture',
            'revealed':True,'mechanics':{'skills':skills or {},**effects}}


def give(r,cid):
    src=next(x for x in d.SPECIAL_CARDS if x['id']==cid)
    r.players['p0'].cards['special']={'category':'special','card_id':cid,'value':src['title'],
        'details':src['desc'],'used':False,'revealed':False}
    return sc.canonical(cid)


def prepare(cid):
    r=room();key=give(r,cid);p=r.players['p0'];t=r.players['p1'];args={}
    r.phase=sc.DEFINITIONS[key][0][0]
    if sc.DEFINITIONS[key][1]=='player':args['target_player_id']=t.id
    t.cards['health']={'category':'health','value':'Fixture illness','details':'Test','severity':'medium','revealed':False,'mechanics':{}}
    t.cards['phobia']={'category':'phobia','value':'Fixture phobia','revealed':False,'mechanics':{'risks':['confined']}}
    if key=='exchange_places':
        r.bunker_capacity=5;r.vote_results={'eliminated_id':p.id,'eliminated_ids':[p.id]}
    if key in ('veto_vote','force_re_vote'):
        r.vote_results={'eliminated_id':'p5','eliminated_ids':['p5']}
    if key in ('swap_baggage','steal_item','sabotage_inventory'):args['category']='backpack'
    if key=='secret_peek':args['category']='hobby'
    if key=='truth_serum':args['categories']=['hobby','fact']
    if key=='reroll_dossier_card':args['category']='hobby'
    if key in sc.speech.INPUTS:args['option_text']='Пельмень'
    if key.startswith('event_'):
        r.events_enabled=True;r.catastrophe={'id':'zombie_outbreak'}
        typ='BUNKER_CRISIS' if key=='event_bunker_overdrive' else 'SURFACE_EVENT'
        r.active_event=b.normalize_event(next(x for x in d.BUNKER_EVENTS if x['type']==typ and 'ALL' in x['compatible_catastrophes']))
        if key=='event_suppress_sabotage':
            r.players['p5'].is_alive=False
            r.players['p5'].cards={'profession':card('profession',{'security':1})}
        r.recalculate_event_odds()
    return r,key,args


@pytest.mark.parametrize('cid',[x['id'] for x in d.SPECIAL_CARDS])
def test_every_special_effect_and_consumption(cid):
    r,key,args=prepare(cid);p=r.players['p0'];t=r.players['p1']
    before=copy.deepcopy(r.__dict__)
    availability=sc.special_availability(r,p.id)
    assert availability['available'],availability
    r.use_special_card(p.id,**args)
    assert p.cards['special']['used'] and p.cards['special']['revealed']
    if key=='heal_illness':assert t.cards['health']['severity']=='good'
    elif key=='blood_transfusion':assert t.cards['health']['severity']=='minor'
    elif key in ('swap_baggage','steal_item'):
        assert p.cards['backpack']['source_id']==before['players']['p1'].cards['backpack']['source_id']
        assert t.cards['backpack']['source_id']==before['players']['p0'].cards['backpack']['source_id']
    elif key=='force_reveal':assert sum(c.get('revealed',False) for c in t.cards.values())>sum(c.get('revealed',False) for c in before['players']['p1'].cards.values())
    elif key=='veto_vote':assert not sc.elimination_ids(r) and r.veto_used
    elif key=='extra_bunk':assert r.bunker_capacity==before['bunker_capacity']+1
    elif key=='double_vote':assert p.double_vote
    elif key=='round_immunity':assert p.has_immunity
    elif key=='reroll_profession':assert p.cards['profession']['value']!=before['players']['p0'].cards['profession']['value'] and p.cards['profession']['revealed']
    elif key=='steal_loot':assert p.loot_stolen
    elif key=='secret_peek':assert p.last_peeked['category']=='hobby' and not t.cards['hobby']['revealed']
    elif key=='change_health':assert p.cards['health']['value']!=before['players']['p0'].cards['health']['value'] and p.cards['health']['revealed']
    elif key=='silence_player':assert t.is_silenced
    elif key=='threat_fix':assert r.bunker['threat_fixed']
    elif key=='quarantine_lock':assert t.is_quarantined
    elif key=='truth_serum':assert all(t.cards[k]['revealed'] for k in args['categories'])
    elif key=='exchange_places':assert sc.elimination_ids(r)==[t.id]
    elif key=='silence_speech':assert t.is_speech_silenced
    elif key=='cure_phobia':assert not b.effects_for_card(t.cards['phobia'],'phobia').get('risks')
    elif key=='sabotage_inventory':assert t.cards['backpack']['destroyed'] and not b.effects_for_card(t.cards['backpack'],'backpack').get('skills')
    elif key=='reroll_dossier_card':assert p.cards['hobby']['value']!=before['players']['p0'].cards['hobby']['value'] and not p.cards['hobby']['revealed']
    elif key=='bunker_ration_boost':assert r.bunker['supplies_years']==before['bunker']['supplies_years']+2
    elif key=='reveal_all_fact':assert all(q.cards['fact']['revealed'] for q in r.get_alive_players())
    elif key=='force_re_vote':assert r.phase=='VOTING' and r.vote_results is None and not r.votes
    elif key=='event_bunker_overdrive':assert r.last_resolved_event['is_success'] and not r.last_resolved_event['is_crit_success'] and r.active_event is None
    elif key=='event_route_reroll':assert r.active_event['id']!=before['active_event']['id']
    elif key=='event_suppress_sabotage':assert r.sabotage_suppressed and not any(f['category']=='sabotage' for f in r.current_event_odds['negative_factors'])
    elif key=='event_hazard_exosuit':assert r.volunteer_is_safe and r.event_special_bonus==15
    elif key=='event_satellite_recon':assert r.event_special_bonus==15
    elif key in sc.speech.SPEECH_CARDS:assert r.speech_effects[t.id]['card_id']==key
    else:pytest.fail('Missing expected effect for '+key)
    with pytest.raises(ValueError):r.use_special_card(p.id,**args)
    json.dumps(r.get_state(for_player_id=p.id),ensure_ascii=False)


@pytest.mark.parametrize('cid',[x['id'] for x in d.SPECIAL_CARDS])
def test_every_special_invalid_phase_preserves_card_and_room(cid):
    r,_,args=prepare(cid);r.phase='LOBBY';before=copy.deepcopy(r.__dict__)
    with pytest.raises(ValueError):r.use_special_card('p0',**args)
    assert not r.players['p0'].cards['special']['used']
    assert r.game_log==before['game_log'] and r.bunker==before['bunker']


def test_unexpected_handler_exception_rolls_back_full_room():
    r,key,args=prepare('threat_fix');p=r.players['p0'];original=copy.deepcopy(r.bunker)
    def crash(*a,**kw):r.bunker['threat_fixed']=True;p.cards['health']['value']='changed';raise RuntimeError('artificial failure')
    health=copy.deepcopy(p.cards['health']);rng=random.getstate()
    with patch.object(sc,'_apply',side_effect=crash),pytest.raises(RuntimeError):r.use_special_card(p.id)
    assert r.players[p.id] is p and p.cards['health']==health and r.bunker==original
    assert not p.cards['special']['used'] and random.getstate()==rng


@pytest.mark.parametrize('event',d.BUNKER_EVENTS,ids=lambda e:e['id'])
def test_every_event_has_explicit_requirements_and_real_outcomes(event):
    normalized=b.normalize_event(event)
    assert normalized['requirements']['skills']
    success=b.resolve_event_roll(event,{'final_chance':80},force_roll=30)
    failure=b.resolve_event_roll(event,{'final_chance':20},force_roll=80)
    assert success['score_delta']>0 and failure['score_delta']<0
    assert not failure['boosted_tags'] and failure['boost_score']==0
    if 'bonus_pct' in event:assert success['score_delta']==max(4,min(12,round(abs(event['bonus_pct'])*.4)))
    if 'penalty_pct' in event:assert failure['score_delta']==-max(4,min(12,round(abs(event['penalty_pct'])*.4)))
    guaranteed=b.resolve_event_roll(event,{'final_chance':10},guaranteed_success=True)
    assert guaranteed['is_success'] and not guaranteed['is_crit_success']
    assert guaranteed['score_delta']==normalized['on_success']['score_delta']


def test_vote_double_denominator_and_abstain():
    r=room();r.phase='VOTING';r.players['p0'].double_vote=True
    for pid in r.players:r.votes[pid]='p5'
    r.finish_voting()
    assert r.vote_results['detailed_tally'][0]['votes']==7
    assert r.vote_results['detailed_tally'][0]['percent']==100
    r.phase='VOTING';r.votes['p0']='ABSTAIN';r.finish_voting()
    tally=r.vote_results['detailed_tally']
    assert tally[0]['percent']==71.4 and r.vote_results['abstain_count']==2


def test_skip_change_not_stale_and_weighted_majority():
    r=room();r.phase='VOTING'
    r.cast_vote('p0','SKIP_ROUND');r.cast_vote('p0','p5')
    assert 'p0' not in r.skip_round_votes
    r.players['p1'].double_vote=True
    r.cast_vote('p1','SKIP_ROUND');r.cast_vote('p2','SKIP_ROUND')
    assert r.phase=='VOTING'  # 3/7 not majority.
    r.cast_vote('p3','SKIP_ROUND')
    assert r.phase!='VOTING'  # 4/7 majority.


def test_veto_blocks_both_ids_and_explicit_host_exile():
    r,key,args=prepare('veto_vote');r.vote_results['eliminated_ids']=['p4','p5']
    r.use_special_card('p0');r.confirm_elimination('p5')
    assert all(p.is_alive for p in r.players.values()) and not sc.elimination_ids(r)


def test_quarantine_no_vote_no_afk_no_deadlock_reset_next_round():
    r=room();give(r,'quarantine_lock');target=r.get_current_speaker()
    # Actor cannot target self; force the current speaker to p1 first.
    r.start_speech_phase();r.host_grant_speech_speaker('p1');r.use_special_card('p0','p1')
    assert r.get_current_speaker().id!='p1'
    r.phase='VOTING'
    with pytest.raises(ValueError):r.cast_vote('p1','p5')
    r.votes={pid:'p5' for pid in r.players if pid!='p1'};r.finish_voting()
    assert r.vote_results['detailed_tally'][0]['votes']==5 and 'p1' not in r.votes
    r.round_number+=1;r.start_round();assert not r.players['p1'].is_quarantined


def test_loot_moves_no_copy_and_overrides_category_correctly():
    r=room();give(r,'steal_loot');r.phase='VOTE_RESULTS';r.vote_results={'eliminated_id':'p5','eliminated_ids':['p5']}
    src=copy.deepcopy(r.players['p5'].cards['backpack']);r.use_special_card('p0');r.confirm_elimination()
    assert 'backpack' not in r.players['p5'].cards
    trophy=r.players['p0'].cards['stolen_baggage']
    assert trophy['source_id']==src['source_id'] and trophy['mechanics']==src['mechanics']


def test_double_exile_does_not_overrun_capacity():
    r=room(4);r.bunker_capacity=3;r.double_elimination_pending=True;r.phase='REVOTE';r.justification_candidates=['p2','p3']
    r.votes={'p0':'p2','p1':'p2','p2':'p3','p3':'p3'};r.finish_revote();r.confirm_elimination()
    assert len(r.get_alive_players())==3


def test_profession_counted_once_and_two_helpers_only():
    ev=next(e for e in d.BUNKER_EVENTS if e['id']=='fuel_tanker_discovery')
    p=Player('p','P');p.cards={'profession':{'value':'Инженер-электрик','tag':'engineering','revealed':True,'details':'engineering инженер техника безопасности'}}
    odds=b.calculate_event_odds(ev,[p],[])
    assert odds['final_chance']==62 and len(odds['positive_factors'])==1
    crisis={**ev,'type':'BUNKER_CRISIS'}
    ps=[]
    for i in range(10):q=Player(str(i),str(i));q.cards=copy.deepcopy(p.cards);ps.append(q)
    two=b.calculate_event_odds(crisis,ps[:2],[]);ten=b.calculate_event_odds(crisis,ps,[])
    assert two['final_chance']==ten['final_chance']==72
    assert len(ten['helpers'])==2


def test_description_does_not_grant_equipment():
    for category,name in [('backpack',n) for n in b.CATALOG['cards']['backpack'] if 'аккумулятор' in n.lower() or 'баллончик' in n.lower()]:
        c={'value':name,'details':'защита противогаз дозиметр ОЗК оружие','revealed':True}
        effects=b.effects_for_card(c,category)
        assert not set(effects.get('protection',[]))&{'chemical','radiation','air'}
    c={'value':'Invented battery','details':'противогаз радиация оружие','revealed':True}
    assert not b.effects_for_card(c,'backpack').get('protection')


def test_phobia_context_and_cure():
    p=Player('p','P');p.cards={'phobia':card('phobia',risks=['confined'])}
    ev={'id':'fixture','title':'Fixture','type':'SURFACE_EVENT','base_chance':40,'requirements':{'skills':[],'hazards':['confined']}}
    assert b.calculate_event_odds(ev,[p],[],volunteer_id=p.id)['final_chance']==32
    ev['requirements']['hazards']=['open'];assert b.calculate_event_odds(ev,[p],[])['final_chance']==40


def test_events_do_not_inflate_with_duration():
    ev=b.normalize_event(d.BUNKER_EVENTS[0]);result=b.resolve_event_roll(ev,{'final_chance':80},force_roll=30)
    h={'event':ev,'result':result}
    assert b.normalized_event_score([h])==b.normalized_event_score([h]*20)
    assert -12<=b.normalized_event_score([h]*100)<=12
    assert b.normalized_event_score([h,{'result':{'is_skipped':True,'score_delta':0}}])==b.normalized_event_score([h])


def test_repair_ten_points_food_real_sex_and_fertility_no_penalty():
    ps=[{'id':'p','name':'P','cards':{}}];cat={'duration_years':10};bunk={'capacity':1,'initial_capacity':1,'supplies_years':1}
    base=b.evaluate_survival(ps,cat,bunk)
    fixed=b.evaluate_survival(ps,cat,{**bunk,'threat_fixed':True})
    food=b.evaluate_survival(ps,cat,{**bunk,'supplies_years':3})
    assert fixed['breakdown']['score_components']['raw']-base['breakdown']['score_components']['raw']==pytest.approx(10)
    assert food['breakdown']['score_components']['raw']>base['breakdown']['score_components']['raw']
    ps[0]['cards']['gender']={'value':'Женщина, 70 лет','age':70,'reproduction':'Бесплодна'}
    older=b.evaluate_survival(ps,cat,bunk)
    assert older['breakdown']['score_components']['raw']<base['breakdown']['score_components']['raw']
    ps[0]['cards']['gender']={'value':'Мужчина, 70 лет','age':70,'reproduction':'Фертилен'}
    assert b.evaluate_survival(ps,cat,bunk)['survival_score']==older['survival_score']


def test_rerolls_all_categories_and_professions_without_exp():
    r=room();p=r.players['p0']
    for category,c in p.cards.items():
        if category in ('special','traitor'):continue
        for _ in range(5):
            new=sc.new_card(category,c)
            assert new['category']==category and new['value']!=c['value']
    for _ in range(200):
        new=sc.new_card('profession',p.cards['profession'])
        assert new['tag'] and any(new['value'].endswith('(по собственным словам: '+str(exp)+')') for exp in d.EXPERIENCE_PRESETS) and new['mechanics']


@pytest.mark.parametrize('n',[3,4,6,8,10,12,20])
def test_deal_constraints(n):
    random.seed(912+n)
    health_good=0
    for _ in range(100):
        deck=d.generate_game_deck(n,enable_events=False,deal_mode='balanced');cs=deck['players_cards']
        assert len(cs)==n
        assert sum(c['profession']['tag']=='useless' for c in cs)<=math.floor(n*.25)
        ids=[sc.canonical(c['special']['card_id']) for c in cs]
        assert len(ids)==len(set(ids))
        assert not any(i.startswith('event_') for i in ids)
        health_good+=sum(c['health']['severity']=='good' for c in cs)
    assert health_good>0


def test_hidden_mechanics_and_peek_are_private():
    r,key,args=prepare('secret_peek');r.use_special_card('p0',**args)
    own=r.get_state(for_player_id='p0');other=r.get_state(for_player_id='p2')
    for p in other['players']:
        if p['id']=='p1':
            assert 'mechanics' not in p['cards']['hobby'] and p['cards']['hobby']['value']=='🔒 Скрыто'
    assert r.players['p0'].cards['special']['used']
    assert r.players['p0'].to_dict(for_player_id='p2').get('last_peeked') is None


@pytest.mark.parametrize('roll',[0,101,True,2.5,'1'])
def test_invalid_d100(roll):
    with pytest.raises(ValueError):b.resolve_event_roll(d.BUNKER_EVENTS[0],{'final_chance':50},force_roll=roll)
