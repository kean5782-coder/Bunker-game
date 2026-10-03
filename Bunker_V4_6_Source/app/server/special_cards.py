"""Validated, transactional special-card actions and client-side availability.

Every dealt ID has a handler. Validation precedes consumption. The outer
transaction also restores the room and RNG if an unexpected handler error occurs.
"""
from __future__ import annotations
import copy
import random
import time
from .balance import decorate_card, effects_for_card, mechanics_text
from .card_text import gender_age_title, profession_title, TREATED_HEALTH
from .age_balance import read_age
from . import speech_effects as speech

ANY = ('REVEAL','SPEECH','ACCUSATION','VOTING','JUSTIFICATION','REVOTE','VOTE_RESULTS')
TALK = ('REVEAL','SPEECH','ACCUSATION')
ALIASES = {'immunity_round':'round_immunity','repair_bunker_threat':'threat_fix','spy_dossier':'secret_peek'}
TITLES = {
 'heal_illness': 'Вовремя вылечили', 'swap_baggage': 'Давай поменяемся',
 'force_reveal': 'А что ты скрываешь?', 'veto_vote': 'Никто никуда не идёт',
 'extra_bunk': 'Подвиньтесь немного', 'double_vote': 'Мой голос за два',
 'round_immunity': 'Сегодня меня не трогаем', 'reroll_profession': 'Вообще-то я ещё и…',
 'steal_loot': 'Рюкзак можешь оставить', 'secret_peek': 'Покажи только мне',
 'change_health': 'Перепутали медкарты', 'silence_player': 'Дай другим сказать',
 'threat_fix': 'Починили!', 'quarantine_lock': 'Посиди отдельно',
 'truth_serum': 'Два неудобных вопроса', 'steal_item': 'Теперь это обмен',
 'exchange_places': 'В списке ошибка', 'silence_speech': 'На сегодня хватит речей',
 'cure_phobia': 'Уже не так страшно', 'sabotage_inventory': 'Ой, сломалось',
 'reroll_dossier_card': 'Начнём с чистого листа', 'blood_transfusion': 'Стало полегче',
 'bunker_ration_boost': 'Нашли ещё кладовку', 'reveal_all_fact': 'Есть что рассказать',
 'force_re_vote': 'Давайте переголосуем', 'event_bunker_overdrive': 'Знаю, как починить',
 'event_route_reroll': 'Пойдём другим путём', 'event_suppress_sabotage': 'Без подстав',
 'event_hazard_exosuit': 'Хорошо подготовились', 'event_satellite_recon': 'Есть подсказка',
}
DEFINITIONS = {
 'heal_illness':(ANY,'player',True,'Исцелите себя или живого игрока. Здоровье становится хорошим; карта раскрывается.'),
 'swap_baggage':(TALK,'player',False,'Обменяйте рюкзак или крупный инвентарь с другим живым игроком. Категорию выбираете вы. Оба предмета раскрываются.'),
 'force_reveal':(TALK,'player',False,'Раскройте одну случайную скрытую обычную карту другого живого игрока.'),
 'veto_vote':(('VOTE_RESULTS',),'none',False,'После объявления результатов отмените все изгнания этого раунда. Повторное вето недоступно в следующем раунде.'),
 'extra_bunk':(ANY,'none',False,'Добавьте одно место. Дополнительный житель расходует припасы и создаёт нагрузку −3 балла. Если мест уже достаточно, игра заканчивается.'),
 'double_vote':(('VOTING','REVOTE'),'self',False,'До подачи собственного голоса удвойте его вес на голосованиях текущего раунда. Проценты учитывают общий вес голосов.'),
 'round_immunity':(TALK+('VOTING',),'self',False,'До первого поданного бюллетеня получите иммунитет на этот раунд. Не отменяет уже поданные голоса.'),
 'reroll_profession':(TALK,'self',False,'Замените свою профессию другой случайной профессией. Новая карта сразу раскрывается.'),
 'steal_loot':(('VOTING','REVOTE','VOTE_RESULTS'),'none',False,'Подготовьтесь забрать рюкзак первого изгнанного в этом раунде. Предмет переносится к вам, а не копируется. Без изгнания эффект истекает.'),
 'secret_peek':(ANY,'player',False,'Тайно посмотрите одну скрытую обычную карту другого игрока. Можно выбрать категорию; содержимое видите только вы.'),
 'change_health':(TALK,'self',False,'Замените здоровье другой случайной картой. Новое состояние раскрывается.'),
 'silence_player':(TALK,'player',False,'Другой игрок не может говорить в оставшейся части второго круга этого раунда. Право голосовать и раскрывать карты сохраняется. Discord автоматически не отключается.'),
 'threat_fix':(ANY,'bunker',False,'Один раз за партию устраните угрозу: её вклад меняется с −5 на +5 баллов, то есть эффект составляет +10 баллов рейтинга до ограничения шкалы.'),
 'quarantine_lock':(TALK,'player',False,'Изолируйте другого игрока до конца раунда: он не говорит, не голосует и не раскрывает свои карты. Его норму раскрытия пропускают. Чужие эффекты раскрытия действуют.'),
 'truth_serum':(TALK,'player',False,'Выберите и раскройте две скрытые обычные карты другого игрока. Если осталась одна — раскрывается она.'),
 'steal_item':(TALK,'player',False,'Выберите категорию снаряжения и обменяйте свой предмет на предмет другого игрока. Оба предмета раскрываются.'),
 'exchange_places':(('VOTE_RESULTS',),'player',False,'Только при окончательном голосовании, когда вас изгоняют: замените себя в списке изгнания другим живым кандидатом без иммунитета. Не действует на уже изгнанных.'),
 'silence_speech':(TALK,'player',False,'Другой игрок лишается оставшихся устных выступлений в этом раунде, но раскрывает карты и голосует. Discord автоматически не отключается.'),
 'cure_phobia':(ANY,'player',True,'Излечите фобию у себя или живого игрока. Её ситуативные штрафы удаляются; карта раскрывается.'),
 'sabotage_inventory':(TALK,'player',False,'Выберите и уничтожьте один предмет другого игрока: рюкзак, крупный инвентарь или трофей. Бонусы предмета пропадают.'),
 'reroll_dossier_card':(('REVEAL','SPEECH'),'self',False,'Выберите одну свою скрытую обычную карту и замените другой картой той же категории. Новая карта остаётся скрытой.'),
 'blood_transfusion':(ANY,'player',True,'Улучшите своё здоровье или здоровье живого игрока на одну ступень: critical → medium → minor → good. Карта раскрывается.'),
 'bunker_ration_boost':(ANY,'bunker',False,'Добавьте 2 года провизии для исходной вместимости бункера. Запас участвует в потребности «Вода и питание», а не только в тексте финала.'),
 'reveal_all_fact':(TALK,'all',False,'Раскройте биографический факт каждого живого игрока. Уже открытые факты не меняются.'),
 'force_re_vote':(('VOTE_RESULTS',),'all',False,'До изгнания отмените результаты и заново запустите голосование среди живых кандидатов без иммунитета. Не отменяет вето.'),
 'event_bunker_overdrive':(ANY,'none',False,'При активной аварии в бункере получите обычный успех без броска и без критического бонуса. На вылазку не действует.'),
 'event_route_reroll':(ANY,'none',False,'Замените активное испытание другим совместимым событием. Текущее событие повторно не выбирается; его временные бонусы сбрасываются.'),
 'event_suppress_sabotage':(ANY,'none',False,'На текущей вылазке полностью уберите действующий штраф от изгнанников. Не действует без саботажа.'),
 'event_hazard_exosuit':(ANY,'none',False,'На текущей вылазке добавьте +15 п.п. и защитите добровольца текущей вылазки от ухудшения здоровья. Общий предел бонусов спецкарт +25 п.п.'),
 'event_satellite_recon':(ANY,'none',False,'Добавьте +15 п.п. к активному испытанию. Общий предел бонусов спецкарт +25 п.п.'),
}


TITLES.update({key: row[0] for key, row in speech.SPEECH_CARDS.items()})
DEFINITIONS.update({key: (speech.SPEECH_PHASES, 'player', False, row[1] + speech.DURATION_TEXT)
                    for key, row in speech.SPEECH_CARDS.items()})


def canonical(card_id):
    return ALIASES.get(card_id,card_id)


def normalize_special_definitions(rows):
    """Preserve alias IDs for old clients, but never deal duplicate IDs."""
    seen=set(); result=[]
    rows = list(rows) + [{'id': key, 'icon': '🗣️'} for key in speech.SPEECH_CARDS]
    for row in rows:
        cid=row['id']
        if cid in seen:continue
        seen.add(cid);key=canonical(cid)
        if key not in DEFINITIONS:raise ValueError('Special card without handler: '+cid)
        phases,target,self_ok,desc=DEFINITIONS[key]
        result.append({**row,'title':TITLES[key],'phase':' / '.join(phases),'allowed_phases':list(phases),
                       'target':target,'allow_self':self_ok,'desc':desc})
    return result


def hidden_categories(p):
    return [k for k,c in p.cards.items() if k not in ('special','traitor','stolen_baggage') and not c.get('revealed') and not c.get('destroyed')]


def inventory_categories(p):
    return [k for k in ('backpack','big_inventory','baggage','stolen_baggage') if k in p.cards and not p.cards[k].get('destroyed')]


def elimination_ids(room):
    result=room.vote_results or {}
    return list(result.get('eliminated_ids') or ([result['eliminated_id']] if result.get('eliminated_id') else []))


def _base_check(room,player):
    room.require_review_finished("USE_SPECIAL_CARD")
    if not player or not player.is_alive:raise ValueError('Игрок не найден или уже изгнан.')
    card=player.cards.get('special',{})
    if not card or card.get('used'):raise ValueError('Спецкарта отсутствует или уже использована.')
    if getattr(player,'is_quarantined',False):raise ValueError('В изоляторе нельзя применять спецкарты до конца раунда.')
    key=canonical(card.get('card_id'))
    if key not in DEFINITIONS:raise ValueError('Эта спецкарта не поддерживается; она не израсходована.')
    phases=DEFINITIONS[key][0]
    if room.phase not in phases:raise ValueError('Карта доступна в фазах: '+', '.join(phases)+'.')
    targets=elimination_ids(room)
    if key=='veto_vote':
        if not targets or room.veto_used:raise ValueError('Нет действующего решения об изгнании.')
        if room.veto_used_round is not None and room.round_number-room.veto_used_round<=1:raise ValueError('После вето должен пройти один полный раунд.')
    if key=='force_re_vote' and (not targets or room.veto_used or getattr(room,'forced_revote_round',None)==room.round_number):
        raise ValueError('Повторные выборы сейчас недоступны.')
    if key=='double_vote' and (player.id in room.votes or player.double_vote):raise ValueError('Двойной голос нужно включить до своего бюллетеня.')
    if key=='round_immunity':
        if room.votes or player.has_immunity:raise ValueError('Иммунитет можно включить только до первого бюллетеня.')
        if sum(not p.has_immunity for p in room.get_alive_players())<=1:raise ValueError('Нельзя оставить голосование без кандидатов.')
    if key=='exchange_places':
        if player.id not in targets or len(room.get_alive_players())-len(targets)>room.bunker_capacity:
            raise ValueError('Рокировка доступна только изгоняемому на окончательном голосовании.')
    if key in ('threat_fix','bunker_ration_boost','extra_bunk') and not room.bunker:raise ValueError('Бункер ещё не выбран.')
    if key=='threat_fix' and room.bunker.get('threat_fixed'):raise ValueError('Угроза уже устранена; повторный ремонт не нужен.')
    if key=='extra_bunk' and room.bunker_capacity>=len(room.get_alive_players()):raise ValueError('Мест уже достаточно.')
    if key=='steal_loot' and player.loot_stolen:raise ValueError('Мародёрство уже подготовлено.')
    if key=='reroll_dossier_card' and not hidden_categories(player):raise ValueError('Нет скрытых обычных карт для замены.')
    if key=='reveal_all_fact' and not any('fact' in p.cards and not p.cards['fact'].get('revealed') for p in room.get_alive_players()):raise ValueError('Все биографические факты уже открыты.')
    if key.startswith('event_'):
        if not room.events_enabled or not room.active_event:raise ValueError('Нет активного испытания.')
        if room.is_sortie_skipped:raise ValueError('Сначала возобновите отменённую вылазку.')
        kind=room.active_event.get('type')
        if key=='event_bunker_overdrive' and kind!='BUNKER_CRISIS':raise ValueError('Форсаж работает только при аварии в бункере.')
        if key in ('event_hazard_exosuit','event_suppress_sabotage') and kind!='SURFACE_EVENT':raise ValueError('Эта карта предназначена только для вылазки.')
        if key=='event_hazard_exosuit' and room.volunteer_is_safe:raise ValueError('Защита добровольца уже активна.')
        if key in ('event_hazard_exosuit','event_satellite_recon') and room.event_special_bonus>=25:raise ValueError('Достигнут предел бонусов спецкарт.')
        if key=='event_suppress_sabotage' and (room.sabotage_suppressed or not any(f.get('category')=='sabotage' for f in (room.current_event_odds or {}).get('negative_factors',[]))):raise ValueError('Нет действующего саботажа для подавления.')
        if key=='event_route_reroll' and not _alternative_events(room):raise ValueError('Других совместимых событий нет.')
    return key


def _target_categories(room,player,target,key):
    if not target or not target.is_alive:raise ValueError('Нужен живой игрок.')
    if target.id==player.id and not DEFINITIONS[key][2]:raise ValueError('Нужно выбрать другого игрока.')
    if key in speech.SPEECH_CARDS:speech.validate_target(room,target)
    if key in ('heal_illness','blood_transfusion'):
        if 'health' not in target.cards or target.cards['health'].get('severity')=='good':raise ValueError('Лечение не изменит хорошее здоровье.')
    if key=='cure_phobia':
        phobia=target.cards.get('phobia')
        if not phobia or phobia.get('cured') or phobia.get('value')=='Фобия излечена':
            raise ValueError('У цели нет действующей фобии.')
    if key in ('quarantine_lock','silence_player','silence_speech'):
        if key=='quarantine_lock' and getattr(target,'is_quarantined',False):raise ValueError('Игрок уже в изоляторе.')
        if key=='silence_player' and target.is_silenced:raise ValueError('Молчание уже действует.')
        if key=='silence_speech' and getattr(target,'is_speech_silenced',False):raise ValueError('Запрет речей уже действует.')
    if key=='exchange_places' and (target.id in elimination_ids(room) or target.has_immunity):raise ValueError('Цель уже изгоняется либо имеет иммунитет.')
    if key in ('secret_peek','truth_serum','force_reveal'):
        cats=hidden_categories(target)
        if not cats:raise ValueError('У цели нет скрытых обычных карт.')
        return cats
    if key in ('swap_baggage','steal_item'):
        cats=[k for k in inventory_categories(target) if k in inventory_categories(player) and k!='stolen_baggage']
        if not cats:raise ValueError('Нет одинаковой категории снаряжения для обмена.')
        return cats
    if key=='sabotage_inventory':
        cats=inventory_categories(target)
        if not cats:raise ValueError('У цели нет предметов для уничтожения.')
        return cats
    return []


def special_availability(room,player_id):
    player=room.players.get(player_id)
    try:
        key=_base_check(room,player)
        target_type=DEFINITIONS[key][1]
        possible=[];categories={}
        if target_type=='player':
            for target in room.get_alive_players():
                try:cats=_target_categories(room,player,target,key)
                except ValueError:continue
                possible.append(target.id);categories[target.id]=cats
            if not possible:raise ValueError('Сейчас нет подходящих целей для этой карты.')
        elif key=='reroll_dossier_card':categories[player_id]=hidden_categories(player)
        return {'available':True,'unavailable_reason':'','target_ids':possible,'category_options':categories,
                'input_config':copy.deepcopy(speech.INPUTS.get(key)),
                'selection_count':2 if key=='truth_serum' else 1,
                'choose_category':key in ('secret_peek','truth_serum','swap_baggage','steal_item','sabotage_inventory','reroll_dossier_card')}
    except ValueError as exc:
        return {'available':False,'unavailable_reason':str(exc),'target_ids':[],'category_options':{},'selection_count':0,'choose_category':False}


def _alternative_events(room):
    from .deck_data import BUNKER_EVENTS
    cid=(room.catastrophe or {}).get('id','')
    pool=[e for e in BUNKER_EVENTS if e['id']!=room.active_event['id'] and ('ALL' in e.get('compatible_catastrophes',[]) or cid in e.get('compatible_catastrophes',[]))]
    fresh=[e for e in pool if e['id'] not in room.used_event_ids]
    return fresh or pool


def new_card(category, old, *, revealed=False):
    from . import deck_data as d
    from .balance import decorate_deck
    # Build a complete card, including current mechanical properties. Drawing a
    # miniature deck would impose profession quotas and bias rerolls, so use the
    # actual category deck instead.
    tables={'profession':d.PROFESSIONS,'health':d.HEALTH_CONDITIONS,'body':d.BODY_BUILDS,'trait':d.HUMAN_TRAITS,
      'hobby':d.HOBBIES,'phobia':d.PHOBIAS,'big_inventory':d.BIG_INVENTORY,'backpack':d.BACKPACK_ITEMS,'fact':d.FACTS,'gender':d.GENDER_TRAITS,'baggage':d.BAGGAGE_ITEMS}
    if category not in tables:raise ValueError('Для этой категории нет колоды замены.')
    old_id=effects_for_card(old,category).get('id')
    pool=[];seen=set()
    for row in tables[category]:
        name=row.get('name') or str(row)
        if name in seen:continue
        if category=='gender' and (row['gender'], row.get('age',30)) == (old.get('gender', old.get('value','').split(',')[0]), read_age(old)):continue
        seen.add(name)
        if category!='gender' and (name==old.get('value') or (category=='profession' and old.get('value','').startswith(name+' ('))):continue
        pool.append(row)
    if not pool:raise ValueError('В колоде нет другой карты.')
    row=copy.deepcopy(random.choice(pool))
    card={k:v for k,v in old.items() if k in ('category','label','icon')}
    card.update(category=category, revealed=revealed, value=row.get('name',''),details=row.get('desc',row.get('description','')))
    if category=='profession':
        card['value']=profession_title(row['name'], random.choice(d.EXPERIENCE_PRESETS))
        card['tag']=row['tag'];card['rarity']=d.get_card_rarity(row);card['rarity_label']=d.RARITY_LABELS.get(card['rarity'],'Обычная')
    if category=='health':card['severity']=row['severity']
    if category=='gender':
        card.update({k:row[k] for k in ('gender','age','orientation','reproduction') if k in row})
        card['value']=gender_age_title(row['gender'], row.get('age',30))
        card['details']=f"Ориентация: {row.get('orientation','')}. Деторождение: {row.get('reproduction','')}."
    return decorate_card(card,category)


def use_special_card(room,player_id,target_player_id=None,category=None,categories=None,option_text=None):
    speech.sync_speech_effects(room)
    player=room.players.get(player_id);key=_base_check(room,player)
    target_type=DEFINITIONS[key][1]
    target=room.players.get(target_player_id or (player_id if DEFINITIONS[key][2] else '')) if target_type=='player' else player
    options=_target_categories(room,player,target,key) if target_type=='player' else hidden_categories(player) if key=='reroll_dossier_card' else []
    option=speech.option_for(key,option_text)
    chosen=list(categories) if categories is not None else [category] if category else []
    if not all(isinstance(k,str) for k in chosen) or len(chosen)!=len(set(chosen)):raise ValueError('Категории должны быть различными строками.')
    if any(k not in options for k in chosen):raise ValueError('Выбранная категория недоступна.')
    count=min(2,len(options)) if key=='truth_serum' else 1
    needs_choice=key in ('secret_peek','truth_serum','swap_baggage','steal_item','sabotage_inventory','reroll_dossier_card','force_reveal')
    if needs_choice:
        if not chosen:chosen=random.sample(options,count)
        if len(chosen)!=count:raise ValueError(f'Нужно выбрать категорий: {count}.')
    replacement=None
    if key in ('reroll_profession','change_health','reroll_dossier_card'):
        cat='profession' if key=='reroll_profession' else 'health' if key=='change_health' else chosen[0]
        replacement=new_card(cat,player.cards[cat],revealed=key!='reroll_dossier_card')
    # Unexpected errors also roll back health, event history, vote data and RNG.
    snapshot=copy.deepcopy(room.__dict__); rng=random.getstate()
    try:
        if key in speech.SPEECH_CARDS:
            speech.apply_effect(room,player,target,key,option)
        else:
            _apply(room,player,target,key,chosen,replacement)
        player.cards['special']['used']=True
        player.cards['special']['revealed']=True
        room.last_activity=time.time()
        if room.active_event:room.recalculate_event_odds()
        room.log_event('Спецкарта применена',f"{player.name}: {player.cards['special'].get('value',key)}.",'info')
        if key in ('veto_vote','exchange_places'):
            room.present_vote_summary(room.vote_results, source='CORRECTION',
                after='confirm_no_exile' if key=='veto_vote' else None)
        if key=='extra_bunk' and len(room.get_alive_players())<=room.bunker_capacity:
            if room.active_event and room.events_enabled:room.resolve_active_event()
            room.trigger_final()
        speech.sync_speech_effects(room)
    except Exception:
        original_players=room.players
        room.__dict__.clear(); room.__dict__.update(snapshot)
        for pid,saved in room.players.items():
            if pid in original_players:
                original_players[pid].__dict__.clear(); original_players[pid].__dict__.update(saved.__dict__)
                room.players[pid]=original_players[pid]
        random.setstate(rng)
        raise


def _apply(room,p,t,key,chosen,replacement):
    if key in ('heal_illness','blood_transfusion'):
        c=t.cards['health'];old=c.get('severity','good')
        # Preserve the original diagnosis/effects internally before replacing
        # outdated prose. Partial treatment changes severity, not the diagnosis.
        c.setdefault('health_before_treatment', {'value':c.get('value',''), 'details':c.get('details','')})
        effects=copy.deepcopy(effects_for_card(c,'health'))
        c['severity']='good' if key=='heal_illness' else {'critical':'medium','danger':'medium','medium':'minor','minor':'good'}[old]
        value,details=TREATED_HEALTH[c['severity']]
        c.update(value=value,details=details,mechanics={} if c['severity']=='good' else effects)
        c['revealed']=True;c['mechanics_text']=mechanics_text(c,'health')
    elif key in ('swap_baggage','steal_item'):
        cat=chosen[0];p.cards[cat],t.cards[cat]=t.cards[cat],p.cards[cat]
        p.cards[cat]['revealed']=t.cards[cat]['revealed']=True
    elif key in ('force_reveal','truth_serum'):
        for cat in chosen:t.cards[cat]['revealed']=True
    elif key=='veto_vote':
        room.veto_used=True;room.veto_used_round=room.round_number
        room.vote_results.update(eliminated_id=None,eliminated_ids=[],eliminated_name=None,top_candidates=[],veto_used=True,veto_possible=False)
        room.double_elimination_pending=False
        room.log_event('ВЕТО','Все изгнания этого раунда отменены.','success')
    elif key=='extra_bunk':
        room.bunker_capacity+=1;room.bunker['capacity']=room.bunker_capacity
    elif key=='double_vote':p.double_vote=True
    elif key=='round_immunity':p.has_immunity=True
    elif key in ('reroll_profession','change_health','reroll_dossier_card'):
        p.cards[replacement['category']]=replacement
    elif key=='steal_loot':p.loot_stolen=True
    elif key=='secret_peek':
        c=t.cards[chosen[0]]
        p.last_peeked={'target_id':t.id,'target_name':t.name,'category':chosen[0],
                      'label':c.get('label',''),'value':c.get('value',''),'details':c.get('details','')}
    elif key=='silence_player':
        t.is_silenced=True
        if room.phase=='ACCUSATION' and room.get_current_accusation_speaker()==t:
            room.next_accusation_speaker()
    elif key in ('quarantine_lock','silence_speech'):
        t.is_silenced=True;t.is_speech_silenced=True
        if key=='quarantine_lock':
            t.is_quarantined=True;room.votes.pop(t.id,None);room.skip_round_votes.discard(t.id);t.vote_target=None
            if room.phase in ('REVEAL','SPEECH') and room.get_current_speaker()==t:
                room.next_speaker(force=True)
        if key=='silence_speech' and room.phase=='SPEECH' and room.get_current_speaker()==t:
            room.next_speaker(force=True)
        if room.phase=='ACCUSATION' and room.get_current_accusation_speaker()==t:
            room.next_accusation_speaker()
    elif key=='threat_fix':
        room.bunker['threat_fixed']=True;room.bunker['threat']='Угроза устранена.'
    elif key=='exchange_places':
        ids=[t.id if x==p.id else x for x in elimination_ids(room)]
        room.vote_results.update(eliminated_ids=ids,eliminated_id=ids[0],eliminated_name=', '.join(room.players[x].name for x in ids),top_candidates=ids)
    elif key=='cure_phobia':
        t.cards['phobia'].update(value='Фобия излечена',details='Этот страх больше не мешает. Штрафов фобии нет.',revealed=True,cured=True,mechanics={})
        t.cards['phobia']['mechanics_text']='Фобия излечена: штрафов нет.'
    elif key=='sabotage_inventory':
        c=t.cards[chosen[0]];old=c.get('value','Предмет')
        c.update(value='Утрачен: '+old,details='Предмет уничтожен спецкартой и не даёт бонусов.',revealed=True,destroyed=True,mechanics={})
        c['mechanics_text']='Предмет утрачен: бонусов нет.'
    elif key=='bunker_ration_boost':room.bunker['supplies_years']=room.bunker.get('supplies_years',5)+2
    elif key=='reveal_all_fact':
        for q in room.get_alive_players():
            if 'fact' in q.cards:q.cards['fact']['revealed']=True
    elif key=='force_re_vote':
        room.vote_results=None;room.justification_candidates=[];room.forced_revote_round=room.round_number
        room.start_voting()
    elif key=='event_satellite_recon':room.event_special_bonus=min(25,room.event_special_bonus+15)
    elif key=='event_hazard_exosuit':
        room.event_special_bonus=min(25,room.event_special_bonus+15);room.volunteer_is_safe=True
    elif key=='event_suppress_sabotage':room.sabotage_suppressed=True
    elif key=='event_route_reroll':
        from .balance import normalize_event
        ev=normalize_event(random.choice(_alternative_events(room)))
        room.active_event=ev
        if ev['id'] not in room.used_event_ids:room.used_event_ids.append(ev['id'])
        room.event_special_bonus=0;room.volunteer_is_safe=False;room.sabotage_suppressed=False;room.is_sortie_skipped=False
    elif key=='event_bunker_overdrive':room.resolve_active_event(guaranteed_success=True)
    else:raise ValueError('Обработчик карты отсутствует: '+key)
