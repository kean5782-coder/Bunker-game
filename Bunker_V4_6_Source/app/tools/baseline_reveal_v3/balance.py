"""Balance v2: explicit card properties, bounded events and scenario needs.

Only the server's catalogue is authoritative. Flavour text is never searched for
skills/equipment. The legacy public function signatures and result fields remain
compatible with existing clients; survival_percent is an alias for a SCORE.
"""
from __future__ import annotations

import copy
import json
import math
import random
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / 'balance_config.json').read_text(encoding='utf-8'))
CATALOG = json.loads((ROOT / 'balance_catalog.json').read_text(encoding='utf-8'))
VERSION = CONFIG['version']
INVENTORY = ('big_inventory', 'backpack', 'baggage', 'stolen_baggage')
NEEDS = ('air_energy', 'food_water', 'medicine', 'security', 'social')
NEED_LABELS = dict(zip(NEEDS, ('Воздух и энергия', 'Вода и питание', 'Медицина', 'Безопасность', 'Организация и мораль')))
SKILL_LABELS = {'medicine':'медицина', 'engineering':'инженерия', 'water':'водоснабжение',
 'agriculture':'выращивание пищи', 'food':'питание', 'security':'безопасность',
 'science':'наука', 'tech':'электроника и связь', 'craft':'ремесло',
 'education':'знания', 'social':'общение', 'logistics':'снабжение', 'transport':'транспорт'}
CONTEXT_LABELS = {'physical':'физическая нагрузка','strength':'силовая работа','agility':'ловкость',
 'precision':'точная работа','calm':'хладнокровие','organization':'организация','empathy':'поддержка',
 'resourceful':'смекалка','vigilance':'наблюдательность','frugal':'экономность','endurance':'выносливость',
 'cold':'холод','confined':'теснота','reach':'работа на высоте','water':'вода',
 'discipline':'дисциплина','trust':'доверие','teamwork':'взаимопомощь','morale':'мораль',
 'negotiation':'переговоры','initiative':'инициатива','panic':'паника','conflict':'конфликт',
 'combat':'бой','darkness':'темнота','pests':'вредители','infection':'инфекция','fire':'огонь',
 'corpses':'погибшие','noise':'шум','open':'открытое пространство','height':'высота','blood':'кровь',
 'alone':'одиночество','radiation':'радиация','public':'публичное выступление','needles':'инъекции',
 'food':'приём пищи','stranger':'незнакомцы','electricity':'электричество','transport':'транспорт',
 'responsibility':'ответственность','air':'плохой воздух','chemical':'химикаты','dust':'пыль',
 'crowd':'толпа','injury':'травмы'}
EMPTY = {'skills':{}, 'traits':[], 'risks':[], 'protection':[]}


def player_data(player: Any) -> tuple[str, str, dict, bool]:
    if isinstance(player, dict):
        cards = player.get('cards')
        if not isinstance(cards, dict):
            cards = player if any(k in player for k in ('profession','health','backpack','body')) else {}
        return str(player.get('id','')), player.get('name','Выживший'), cards, player.get('is_alive',True)
    return str(getattr(player,'id','')), getattr(player,'name','Выживший'), getattr(player,'cards',{}), getattr(player,'is_alive',True)


@lru_cache(maxsize=8192)
def lookup_effects(category: str, name: str, tag: str = '') -> dict:
    rows = CATALOG['cards'].get(category, {})
    if name in rows:
        return rows[name]
    # Experience is appended to a profession's exact title. Longest prefix wins
    # so parentheses in the source title do not cause an identity collision.
    if category == 'profession':
        matches = [n for n in rows if name.startswith(n + ' (')]
        if matches:
            return rows[max(matches,key=len)]
        if tag in SKILL_LABELS:
            return {**EMPTY, 'skills':{tag:1.0}}
    return EMPTY


def effects_for_card(card: dict, category: str = '') -> dict:
    if not isinstance(card,dict) or card.get('destroyed'):
        return EMPTY
    if 'mechanics' in card:
        return card['mechanics'] or EMPTY
    cat = card.get('source_category') or category or card.get('category','')
    if cat == 'stolen_baggage':
        cat = 'backpack'
    return lookup_effects(cat, str(card.get('source_name') or card.get('value') or card.get('name','')), card.get('tag',''))


def card_event_cap(category: str) -> int:
    if category in INVENTORY:
        return CONFIG['equipment_event_cap']
    return CONFIG.get(category + '_event_cap', 5)


def mechanics_text(card: dict, category: str = '') -> str:
    category = category or card.get('category','')
    if card.get('destroyed'):
        return 'Предмет утрачен. Бонусов не даёт.'
    if category in ('gender','biology'):
        return 'Ролевая характеристика. Не изменяет рейтинг текущего выживания; демография показана отдельно в финале.'
    if category == 'special':
        return card.get('details','')
    e = effects_for_card(card, category)
    bits = []
    if e.get('skills'):
        skills = ', '.join(f"{SKILL_LABELS.get(k,k)} +{round(card_event_cap(category)*v)}" for k,v in e['skills'].items())
        bits.append('Подходящая задача: ' + skills + ' п.п. Берётся одно лучшее совпадение.')
    if e.get('traits'):
        bits.append('Ситуативная помощь: ' + ', '.join(CONTEXT_LABELS.get(k,k) for k in e['traits']) + f' (до +{min(5,card_event_cap(category))} п.п.).')
    if e.get('risks'):
        bits.append('Ограничение: ' + ', '.join(CONTEXT_LABELS.get(k,k) for k in e['risks']) + ' (до −8 п.п., только при совпадении условий).')
    if e.get('protection'):
        bits.append('Защита: ' + ', '.join(CONTEXT_LABELS.get(k,k) for k in e['protection']) + '.')
    if category == 'health':
        bits.append('Текущая тяжесть: '+card.get('severity','good')+'. Нагрузка на медицину учитывается плавно, помощь снижает её. Пол и фертильность не штрафуют выживание.')
    return ' '.join(bits) or 'Ролевая карточка: самостоятельного численного бонуса нет.'


def decorate_card(card: dict, category: str = '') -> dict:
    category = category or card.get('category','')
    if category not in ('special','traitor','gender','biology') and 'mechanics' not in card:
        card['mechanics'] = copy.deepcopy(effects_for_card(card,category))
        card['source_id'] = card['mechanics'].get('id')
    card['mechanics_text'] = mechanics_text(card,category)
    return card


def decorate_deck(deck: dict) -> dict:
    deck['balance_version'] = VERSION
    deck['bunker']['balance_version'] = VERSION
    for cards in deck['players_cards']:
        for category,card in cards.items():
            decorate_card(card,category)
    return deck


def normalize_event(event: dict) -> dict:
    """Canonical outcomes for both historical event schemas; no global mutation."""
    ev = copy.deepcopy(event)
    spec = copy.deepcopy(CATALOG['events'].get(ev.get('id')) or ev.get('requirements') or {})
    ev['base_chance'] = spec.get('base_chance',ev.get('base_chance',40))
    ev['balance_version'] = VERSION
    ev['requirements'] = copy.deepcopy(spec)
    if spec:
        ev['requirements_desc'] = ('Навыки: ' + ', '.join(SKILL_LABELS.get(k,k) for k in spec.get('skills',[])) +
            '. Условия: ' + ', '.join(CONTEXT_LABELS.get(k,k) for k in spec.get('hazards',[])) +
            '. Один ведущий + половина вклада одного помощника; вылазка — один доброволец.')
    for key,sign,old in [('on_success',1,'bonus_pct'),('on_failure',-1,'penalty_pct')]:
        out = dict(ev.get(key) or {})
        if 'score_delta' not in out:
            out['score_delta'] = sign * max(4, min(12, round(abs(ev.get(old,20))*0.4)))
        out.setdefault('title','Испытание пройдено' if sign==1 else 'Испытание провалено')
        out.setdefault('description','Команда получила полезные ресурсы.' if sign==1 else 'Последствия осложняют жизнь бункера.')
        # A failed event must not secretly give a net positive reward for owning
        # the correct profession. Old boosted tags remain informational only.
        out['boost_score'] = 0
        out['boost_reason'] = ''
        if out.get('boosted_tags'):
            # Keep the incident, remove the obsolete promised profession reward.
            out['description'] = out['description'].split('. ')[0].rstrip('.!') + '. Последствия учтены в результате испытания; скрытого бонуса профессиям нет.'
        out['boosted_tags'] = []
        ev[key] = out
    return ev


def draw_random_event(catastrophe_id: str, used_ids: list | None = None) -> dict | None:
    from .deck_data import BUNKER_EVENTS
    used = set(used_ids or [])
    pool = [e for e in BUNKER_EVENTS if 'ALL' in e.get('compatible_catastrophes',[]) or catastrophe_id in e.get('compatible_catastrophes',[])]
    if not pool:
        return None
    fresh = [e for e in pool if e['id'] not in used]
    return normalize_event(random.choice(fresh or pool))


def _factor(pid, name, card, category, delta, title):
    return {'player_id':pid,'player_name':name,'category':category,
            'card_name':card.get('value',card.get('name',category)), 'delta':delta, 'title':title}


def _player_event_factors(player: Any, spec: dict) -> list[dict]:
    pid,name,cards,_ = player_data(player)
    skills,traits,hazards = set(spec.get('skills',[])),set(spec.get('traits',[])),set(spec.get('hazards',[]))
    all_contexts = hazards | traits | ({'physical'} if spec.get('physical') else set())
    factors = []
    for cat,card in cards.items():
        if not isinstance(card,dict) or not card.get('revealed') or card.get('destroyed') or cat in ('special','traitor','gender','biology'):
            continue
        e = effects_for_card(card,cat)
        skill_match = max((v for k,v in e.get('skills',{}).items() if k in skills), default=0)
        positive = round(card_event_cap(cat)*skill_match)
        if traits.intersection(e.get('traits',[])):
            positive = max(positive, min(5,card_event_cap(cat)))
        if hazards.intersection(e.get('protection',[])):
            positive = max(positive, min(8,card_event_cap(cat)))
        positive = min(card_event_cap(cat),positive)
        negative = 8 if all_contexts.intersection(e.get('risks',[])) else 0
        if cat == 'health' and spec.get('physical'):
            penalty = e.get('physical_penalty', {'critical':6,'danger':5,'medium':3,'minor':0,'good':0}.get(card.get('severity'),0))
            negative = max(negative,penalty)
        # One positive and at most one contextual restriction per source, not
        # profession-tag + title + role + incidental description four times.
        if positive:
            factors.append(_factor(pid,name,card,cat,positive,f"{name}: {card.get('label',cat)} помогает в задаче (+{positive} п.п.)"))
        if negative:
            factors.append(_factor(pid,name,card,cat,-negative,f"{name}: ограничение в текущих условиях (−{negative} п.п.)"))
    return factors


def is_exile_alive_on_surface(player: Any, catastrophe: dict | None = None) -> dict:
    _,_,cards,_ = player_data(player)
    catastrophe = catastrophe or {}
    cid = catastrophe.get('id','')
    needed = {'ice_age':'cold','acid_rains':'chemical','nanite_swarm':'nanites','atmospheric_fire':'air','global_flood':'water'}.get(cid)
    if not needed:
        return {'is_alive_surface':True,'reason':'Поверхность опасна, но не исключает выживание.'}
    for cat,c in cards.items():
        if not isinstance(c,dict) or not c.get('revealed') or c.get('destroyed'):
            continue
        e = effects_for_card(c,cat)
        if needed in e.get('protection',[]) or (needed=='nanites' and cat=='profession' and e.get('skills',{}).get('tech',0)>=1):
            return {'is_alive_surface':True,'reason':'Подходящее снаряжение или специальная компетенция позволяют укрыться.'}
    return {'is_alive_surface':False,'reason':'По правилам этой катастрофы нет необходимой защиты: '+CONTEXT_LABELS.get(needed,needed)+'.'}


def calculate_event_odds(event: dict, alive_players: list, eliminated_players: list,
                         volunteer_id=None, catastrophe=None, pity_bonus=0,
                         special_bonus=0, sabotage_suppressed=False) -> dict:
    kind = event.get('type','BUNKER_CRISIS')
    spec = event.get('requirements') or CATALOG['events'].get(event.get('id')) or {
        'skills':event.get('success_roles',[]),'traits':[], 'hazards':[], 'physical':False}
    base = spec.get('base_chance',event.get('base_chance',40))
    data = [(p,_player_event_factors(p,spec)) for p in alive_players if player_data(p)[3]]
    factors=[]; volunteer=None; exiles=[]; helpers=[]
    if kind=='BUNKER_CRISIS':
        # Stable ordering for ties: no random calls inside preview calculations.
        data.sort(key=lambda row:sum(f['delta'] for f in row[1]),reverse=True)
        for index,(p,fs) in enumerate(data[:2]):
            net = sum(f['delta'] for f in fs)
            if index==1 and net<=0:
                continue
            weight = 1 if index==0 else CONFIG['second_helper_weight']
            pid,name,_,_ = player_data(p)
            helpers.append({'id':pid,'name':name,'weight':weight})
            for f in fs:
                f=dict(f); f['raw_delta']=f['delta']; f['weight']=weight
                f['delta']=round(f['delta']*weight,1)
                if index:
                    f['title'] += f"; помощь ×{weight} = {f['delta']:+g} п.п."
                factors.append(f)
    else:
        chosen = next((row for row in data if player_data(row[0])[0]==volunteer_id),None)
        if chosen is None and data:
            chosen = max(data,key=lambda row:sum(f['delta'] for f in row[1]))
        if chosen:
            pid,name,_,_=player_data(chosen[0]); factors=list(chosen[1])
            volunteer={'id':pid,'name':name,'factors':list(factors)}
        raw_threats=[]
        for p in eliminated_players:
            pid,name,cards,_=player_data(p)
            status=is_exile_alive_on_surface(p,catastrophe)
            power=0
            if status['is_alive_surface'] and not sabotage_suppressed:
                power=3
                for cat,c in cards.items():
                    if not isinstance(c,dict) or not c.get('revealed') or c.get('destroyed'):continue
                    e=effects_for_card(c,cat)
                    if e.get('weapon'):power=max(power,10)
                    if cat=='profession' and e.get('skills',{}).get('security',0)>=.7:power=max(power,8)
                raw_threats.append(power)
            exiles.append({'id':pid,'name':name,**status,'factors':[{'title':('Саботаж подавлен' if sabotage_suppressed else status['reason']), 'delta':-power}]})
        raw_threats.sort(reverse=True)
        penalty=min(CONFIG['exile_penalty_cap'],(raw_threats[0] if raw_threats else 0)+sum(raw_threats[1:])*.5)
        if penalty:
            factors.append(_factor('exiles','Изгнанники',{},'sabotage',-penalty,'Саботаж: сильнейший полностью, остальные вполовину; предел 15 п.п.'))
    for category,delta,title in [('special',min(CONFIG['event_special_cap'],max(0,special_bonus)),'Спецкарты (общий предел +25 п.п.)'),('pity',min(15,max(0,pity_bonus)),'Сплочённость после двух неудач')]:
        if delta:factors.append(_factor('bunker','Бункер',{},category,delta,title))
    unclamped=base+sum(f['delta'] for f in factors)
    final=round(max(CONFIG['event_min'],min(CONFIG['event_max'],unclamped)))
    return {'type':kind,'base_chance':base,'final_chance':final,'unclamped_chance':unclamped,
            'positive_factors':[f for f in factors if f['delta']>0],
            'negative_factors':[f for f in factors if f['delta']<0],
            'volunteer':volunteer,'exiles':exiles,'helpers':helpers,'balance_version':VERSION}


def resolve_event_roll(event: dict, odds_data: dict, force_roll=None, *, guaranteed_success=False) -> dict:
    if force_roll is not None and (isinstance(force_roll,bool) or not isinstance(force_roll,int) or not 1<=force_roll<=100):
        raise ValueError('Результат d100 должен быть целым числом от 1 до 100.')
    ev=normalize_event(event)
    chance=odds_data.get('final_chance',40)
    roll=0 if guaranteed_success else force_roll if force_roll is not None else random.randint(1,100)
    success=guaranteed_success or roll<=chance
    critical=success and not guaranteed_success and roll<=5
    disaster=not success and roll>=96
    out=ev['on_success' if success else 'on_failure']
    delta=out['score_delta']+(2 if critical else -2 if disaster else 0)
    return {'event_id':ev['id'],'event_title':ev['title'],'roll':roll,'chance_required':chance,
      'is_success':success,'is_crit_success':critical,'is_crit_failure':disaster,
      'guaranteed_success':guaranteed_success,'score_delta':delta,'title':out['title'],
      'description':out['description'],'boosted_tags':[],'boost_score':0,'boost_reason':''}


def normalized_event_score(history: list | None) -> float:
    played=[h for h in (history or []) if not h.get('result',h).get('is_skipped')]
    if not played:return 0.0
    quality=[]
    for h in played:
        result=h.get('result',h); event=h.get('event')
        ev=normalize_event(event) if event else None
        scale=max(abs(ev['on_success']['score_delta'])+2,abs(ev['on_failure']['score_delta'])+2,1) if ev else 12
        quality.append(max(-1,min(1,result.get('score_delta',0)/scale)))
    return round(CONFIG['events_final_cap']*sum(quality)/len(quality),2)


NEED_SKILLS={
 'air_energy':{'engineering':1,'tech':.8,'craft':.65,'science':.4},
 'food_water':{'water':1,'agriculture':1,'food':.85,'logistics':.45},
 'medicine':{'medicine':1,'science':.3},
 'security':{'security':1,'transport':.25},
 'social':{'social':1,'education':.9,'logistics':.65}}
NEED_TRAITS={
 'air_energy':{'precision':.18,'resourceful':.22,'discipline':.15},
 'food_water':{'frugal':.25,'endurance':.10,'organization':.15},
 'medicine':{'empathy':.15,'precision':.1},
 'security':{'vigilance':.25,'strength':.15,'calm':.15},
 'social':{'morale':.25,'empathy':.25,'teamwork':.25,'organization':.25,'negotiation':.20,'trust':.15,'calm':.12}}
SOURCE_WEIGHTS={'profession':1,'hobby':.42,'fact':.30,'big_inventory':.50,'backpack':.35,'baggage':.40,'stolen_baggage':.35}


def _capabilities(cards: dict) -> dict:
    result={k:0.0 for k in NEEDS}
    for cat,c in cards.items():
        if not isinstance(c,dict) or c.get('destroyed') or cat in ('special','traitor','gender','biology'):continue
        e=effects_for_card(c,cat)
        for need in NEEDS:
            skill=max((v*NEED_SKILLS[need].get(k,0) for k,v in e.get('skills',{}).items()),default=0)
            skill*=SOURCE_WEIGHTS.get(cat,0)
            trait=max((NEED_TRAITS[need].get(k,0) for k in e.get('traits',[])),default=0)
            # One contribution per card and need, not a title bonus + tag bonus.
            result[need]+=max(skill,trait)
        if cat in ('trait','hobby','fact'):
            if set(e.get('risks',[])).intersection({'conflict','trust','morale'}):
                result['social']-=.12
    return {k:max(0,min(1.8,v)) for k,v in result.items()}


def evaluate_survival(survivors=None, catastrophe=None, bunker=None, traitor_eliminated=False,
                      events_score_delta=0, boosted_profession_tags=None,
                      resolved_events_history=None, survivor_cards_list=None) -> dict:
    if survivors is None:survivors=survivor_cards_list or []
    catastrophe=catastrophe or {};bunker=bunker or {}
    people=[player_data(p) for p in survivors]
    n=len(people)
    facilities=CATALOG['facilities'].get(bunker.get('name'),{})
    weights=CATALOG['scenarios'].get(catastrophe.get('id'),{k:1 for k in NEEDS})
    caps=[_capabilities(p[2]) for p in people]
    item_caps=[_capabilities({k:c for k,c in p[2].items() if k in INVENTORY}) for p in people]
    demand=CONFIG['needs_base']*(max(1,n)/3)**CONFIG['needs_size_exponent']
    duration=max(1,float(catastrophe.get('duration_years',5)))
    supplies=max(0,float(bunker.get('supplies_years',5)))
    init_cap=max(1,int(bunker.get('initial_capacity') or bunker.get('capacity') or n or 1))
    # Supplies in presets are for the original number of bunks, so extra people
    # really consume the extra food rather than receiving a free resource copy.
    effective_years=supplies*min(1,init_cap/max(1,n))
    provision=min(.60,.45*effective_years/duration)
    need_rows={};pros=[];cons=[]
    for need in NEEDS:
        ranked=sorted(enumerate(caps),key=lambda p:p[1][need],reverse=True)
        contribution=sum(row[1][need]*(1 if i==0 else CONFIG['second_helper_weight']) for i,row in enumerate(ranked[:2]))
        support=facilities.get(need,0)+(provision if need=='food_water' else 0)
        coverage=min(1,max(0,(contribution+support)/demand)) if n else 0
        need_rows[need]={'label':NEED_LABELS[need],'coverage':round(coverage,4),'weight':weights.get(need,1),
                         'team':round(contribution,3),'facilities_and_resources':round(support,3),'required':round(demand,3),
                         'contributors':[{'id':people[i][0],'name':people[i][1],'contribution':round(c[need]*(1 if j==0 else CONFIG['second_helper_weight']),3)} for j,(i,c) in enumerate(ranked[:2]) if c[need]>0]}
        (pros if coverage>=.65 else cons).append(f"{NEED_LABELS[need]}: обеспеченность {round(100*coverage)}% от потребности сценария.")
    total_weight=sum(weights.get(k,1) for k in NEEDS)
    coverage=sum(need_rows[k]['coverage']*weights.get(k,1) for k in NEEDS)/total_weight
    base=CONFIG['final_base']; coverage_score=CONFIG['final_range']*coverage
    threat=5 if bunker.get('threat_fixed') else -5
    (pros if threat>0 else cons).append('Угроза устранена (+5 баллов).' if threat>0 else 'Неустранённая угроза бункера (−5 баллов).')
    burden=0;critical_count=0;fertile_males=0;fertile_females=0;items=[];traitor_name=None
    for _,name,cards,_ in people:
        health=cards.get('health',{});severity=health.get('severity','good')
        burden+=effects_for_card(health,'health').get('burden',{'good':0,'minor':.4,'medium':2,'danger':3,'critical':4}.get(severity,0))
        critical_count+=severity=='critical'
        bio=cards.get('gender') or cards.get('biology',{})
        if bio.get('reproduction','').lower().startswith('фертил'):
            fertile_males+=('Мужчина' in bio.get('value',''))
            fertile_females+=('Женщина' in bio.get('value',''))
        for cat in INVENTORY:
            if cards.get(cat,{}).get('value') and not cards[cat].get('destroyed'):items.append(cards[cat]['value'])
        if 'traitor' in cards:traitor_name=name
    health_penalty=round(min(10,burden/max(1,n)**.65)*(1-.5*need_rows['medicine']['coverage']),2)
    if health_penalty:cons.append(f'Потребность в лечении с учётом медицинской помощи (−{health_penalty:g} балла).')
    event_delta=max(-12,min(12,normalized_event_score(resolved_events_history)+bunker.get("vendetta_delta",0))) if resolved_events_history is not None else round(max(-CONFIG['events_final_cap'],min(CONFIG['events_final_cap'],events_score_delta)),2)
    if event_delta:(pros if event_delta>0 else cons).append(f'Средний результат испытаний ({event_delta:+g} балла; предел ±12).')
    traitor_delta=-30 if traitor_name else 10 if traitor_eliminated else 0
    if traitor_delta:(pros if traitor_delta>0 else cons).append(f"{'Диверсант внутри' if traitor_name else 'Диверсант разоблачён'} ({traitor_delta:+g} баллов).")
    overcrowding=max(0,n-init_cap)*3
    if overcrowding:cons.append(f'Дополнительные жильцы: нагрузка на пространство (−{overcrowding} балла).')
    raw=base+coverage_score+threat-health_penalty+event_delta+traitor_delta-overcrowding
    score=round(max(0,min(100,raw))) if n else 0
    success=score>=CONFIG['success_threshold'] and n>0
    title='Уверенное выживание колонии' if score>=80 else 'Трудное выживание' if success else 'Колония не выдержала испытаний'
    text=(f'Итоговый рейтинг устойчивости — {score}/100, порог успеха — {CONFIG["success_threshold"]}. '
          f'Потребности рассчитаны на {duration:g} лет изоляции. Это оценка состава и ресурсов, а не вероятность и не случайный финальный бросок.')
    achievements=[]
    for (pid,name,cards,_),cap in zip(people,caps):
        best=max(NEEDS,key=lambda k:cap[k])
        achievements.append({'player_id':pid,'player_name':name,'badge':'🤝','title':NEED_LABELS[best],
                             'desc':'Главный вклад досье: '+NEED_LABELS[best].lower()+'.'})
    tags={p[2].get('profession',{}).get('tag') for p in people}
    return {'survival_percent':score,'survival_score':score,'score_kind':'rating','success_threshold':CONFIG['success_threshold'],
      'is_success':success,'title':title,'text':text,'pros':pros,'cons':cons,
      'traitor_in_bunker':traitor_name is not None,'traitor_name':traitor_name,'achievements':achievements,
      'balance_version':VERSION,'breakdown':{'needs':need_rows,'score_components':{'base':base,'needs':round(coverage_score,3),'threat':threat,'health':-health_penalty,'events':event_delta,'traitor':traitor_delta,'overcrowding':-overcrowding,'raw':round(raw,3)},
        'profession_coverage':{'doctor':'medicine' in tags,'engineer':bool(tags&{'engineering','tech'}),'agronomist':bool(tags&{'agriculture','food'}),'security':'security' in tags},
        'health_status':{'critical_count':critical_count,'has_critical':critical_count>0},
        'demographics_status':{'fertile_males':fertile_males,'fertile_females':fertile_females,'reproduction_possible':bool(fertile_males and fertile_females),'affects_current_survival':False},
        'inventory_status':{'all_items':items,'has_med_item':any(c['medicine']>0 for c in item_caps),'has_eng_item':any(c['air_energy']>0 for c in item_caps),'has_food_item':any(c['food_water']>0 for c in item_caps)},
        'supplies_status':{'effective_years':round(effective_years,2),'required_years':duration}}}


def has_hazard_protection(cards: dict, catastrophe: dict | None) -> bool:
    cid=(catastrophe or {}).get('id','')
    hazards={'ice_age':{'cold'},'acid_rains':{'chemical'},'global_flood':{'water'},
      'nuclear_winter':{'radiation','cold'},'cosmic_radiation':{'radiation'},'atmospheric_fire':{'air'},
      'super_virus':{'infection'},'zombie_outbreak':{'infection'},'toxic_bloom':{'chemical','infection'}}.get(cid,{'injury','infection'})
    return any(isinstance(c,dict) and c.get('revealed') and hazards.intersection(effects_for_card(c,cat).get('protection',[])) for cat,c in cards.items())
