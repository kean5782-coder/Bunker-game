"""Player-facing information policy. Exact balancing data never leaves the server.

Filtering happens AFTER per-viewer card masking, including secret-peek and health
privacy. This module creates detached allow-listed DTOs, never changes the model.
Both human hosts and guests use the same policy. No client 'debug' bypass exists.
"""
from __future__ import annotations

import copy
import math
import re

IMMERSION = 'immersion'
UNCERTAINTY = 'uncertainty'
MODE_INFO = {
    IMMERSION: {
        'id': IMMERSION, 'label': 'Погружение',
        'description': 'Общий шанс испытания: низкий, средний или высокий. Без процентов, формул и оценки полезности участников.',
    },
    UNCERTAINTY: {
        'id': UNCERTAINTY, 'label': 'Неизвестность',
        'description': 'Даже оценка шанса скрыта. Только условия испытания, решения команды и их последствия.',
    },
}


def pick(data: dict | None, fields) -> dict:
    return {key: copy.deepcopy(data[key]) for key in fields if key in (data or {})}


def mode_for(room) -> str:
    settings = room.match_settings if room.phase != 'LOBBY' and room.match_settings else room.lobby_settings
    mode = settings.get('information_mode', IMMERSION)
    return mode if mode in MODE_INFO else IMMERSION  # Fail closed for old saved state.


# Action contracts stay precise. Narrative details are not replaced by a
# numerical or qualitative ranking of the card's usefulness.
SPECIAL_DESCRIPTIONS = {
    'double_vote': 'До подачи собственного бюллетеня удвойте его вес на голосованиях текущего раунда. Ваш голос считается за два.',
    'extra_bunk': 'Добавьте одно место. Дополнительный житель расходует припасы и нуждается в пространстве. Если мест стало достаточно для всех оставшихся, игра заканчивается.',
    'threat_fix': 'Один раз за партию устраните основную угрозу убежища. Повторный ремонт уже устранённой угрозы невозможен.',
    'blood_transfusion': 'Улучшите своё здоровье или здоровье живого игрока на одну ступень: критическое → средней тяжести → лёгкое нарушение → хорошее. Карта здоровья раскрывается.',
    'event_hazard_exosuit': 'Улучшите подготовку к текущей вылазке и защитите её добровольца от ухудшения здоровья. Не гарантирует успех вылазки. Дополнительное усиление имеет общий предел.',
    'event_satellite_recon': 'Разведданные улучшают подготовку к активному испытанию. Не гарантируют успех. Дополнительное усиление имеет общий предел.',
    'event_bunker_overdrive': 'Устраните текущую аварию в бункере без броска. Это обычный успех, без дополнительной награды. На вылазке карта не сработает.',
}
CARD_FIELDS = ('category', 'label', 'icon', 'value', 'details', 'revealed', 'used', 'destroyed',
               'age', 'gender', 'orientation', 'reproduction', 'card_id', 'phase',
               'target', 'allow_self', 'allowed_phases', 'available', 'unavailable_reason',
               'target_ids', 'category_options', 'selection_count', 'choose_category', 'input_config')


def public_card(card: dict, category: str) -> dict:
    safe = pick(card, CARD_FIELDS)
    if category == 'special' and card.get('card_id'):
        from .special_cards import canonical
        desc = SPECIAL_DESCRIPTIONS.get(canonical(card['card_id']))
        if desc:
            safe['details'] = desc
    if category == 'traitor' and card.get('value') != '🔒 Скрыто':
        safe['details'] = 'Ваша тайная цель — остаться в убежище и сорвать спасение колонии. Другие участники не знают вашу роль до финала.'
    # Health treatments append an engine enum to otherwise narrative text.
    if category == 'health' and isinstance(safe.get('details'), str):
        for key, value in {'good': 'хорошее состояние', 'minor': 'лёгкое нарушение',
                           'medium': 'средней тяжести', 'danger': 'тяжёлое состояние',
                           'critical': 'критическое состояние'}.items():
            safe['details'] = safe['details'].replace('Тяжесть после лечения: '+key, 'Состояние после лечения: '+value)
    return safe


def public_player(player: dict) -> dict:
    safe = pick(player, ('id', 'name', 'is_host', 'is_alive', 'has_voted', 'has_immunity',
                         'is_silenced', 'is_speech_silenced', 'is_quarantined', 'connected'))
    safe['cards'] = {cat: public_card(card, cat) for cat, card in player.get('cards', {}).items()}
    peek = player.get('last_peeked')
    if peek:
        safe['last_peeked'] = pick(peek, ('player_id', 'player_name', 'target_id', 'target_name', 'category', 'value', 'details', 'label', 'icon'))
        if isinstance(peek.get('card'), dict):
            safe['last_peeked']['card'] = public_card(peek['card'], peek.get('category', ''))
    else:
        safe['last_peeked'] = None
    return safe


def public_catastrophe(cat: dict | None):
    return pick(cat, ('id', 'title', 'description', 'duration_years', 'hazard')) if cat else None


def public_bunker(bunker: dict | None):
    return pick(bunker, ('id', 'name', 'size_sqm', 'description', 'facilities', 'threat',
                         'supplies_years', 'capacity', 'initial_capacity', 'threat_fixed')) if bunker else None


CONDITIONS = {
    'radiation': 'Снаружи возможное радиоактивное заражение.',
    'chemical': 'Придётся действовать в химически опасной среде.',
    'infection': 'Есть опасность заражения.',
    'cold': 'Работе мешает сильный холод.',
    'heat': 'Придётся выдерживать высокую температуру.',
    'air': 'Воздух опасен для дыхания.',
    'water': 'Задача связана с водой и угрозой затопления.',
    'darkness': 'Работать предстоит при плохой видимости.',
    'confined': 'Действовать придётся в тесном пространстве.',
    'height': 'Часть действий придётся выполнять на высоте.',
    'injury': 'Есть риск получить травму.',
    'combat': 'Возможны опасные столкновения.',
    'stress': 'Решения придётся принимать под сильным давлением.',
    'animals': 'Поблизости опасные животные.',
    'pests': 'Вредители угрожают убежищу и запасам.',
    'electricity': 'Работа связана с повреждёнными электрическими системами.',
    'dust': 'Пыль мешает дышать и ограничивает видимость.',
    'noise': 'Громкий шум мешает сосредоточиться.',
    'alone': 'Часть действий придётся выполнять в одиночку.',
    'corpses': 'На месте могут оказаться погибшие.',
    'open': 'Предстоит действовать на открытом пространстве.',
    'blood': 'Возможен контакт с кровью и тяжёлыми ранениями.',
    'needles': 'При помощи пострадавшим могут потребоваться инъекции.',
    'stranger': 'Придётся взаимодействовать с незнакомцами.',
    'crowd': 'Людей много, организовать действия будет непросто.',
    'transport': 'Нужно действовать рядом с транспортом или во время движения.',
    'fire': 'Есть угроза огня и дыма.',
}


def public_event(event: dict | None):
    if not event:
        return None
    safe = pick(event, ('id', 'type', 'title', 'description'))
    # No skills/professions, best-helper list, outcome previews or coefficients.
    hazards = (event.get('requirements') or {}).get('hazards', [])
    safe['conditions'] = [CONDITIONS[k] for k in dict.fromkeys(hazards) if k in CONDITIONS]
    return safe


def public_odds(odds: dict | None, mode: str, *, skipped: bool = False):
    if mode == UNCERTAINTY or not odds or skipped:
        return None
    chance = odds.get('final_chance')
    if not isinstance(chance, (int, float)) or not math.isfinite(chance):
        return None
    level = 'low' if chance < 40 else 'medium' if chance < 70 else 'high'
    label, text = {
        'low': ('Низкий шанс', 'Подготовка ограничена. Попытка остаётся рискованной.'),
        'medium': ('Средний шанс', 'Есть возможности справиться, но исход неясен.'),
        'high': ('Высокий шанс', 'Команда хорошо подготовлена. Неудача всё ещё возможна.'),
    }[level]
    return {'level': level, 'label': label, 'description': text}


def public_event_result(result: dict | None):
    if not result:
        return None
    safe = pick(result, ('event_id', 'event_title', 'event_type', 'round_number', 'resolved_at',
                         'is_success', 'is_crit_success', 'is_crit_failure', 'is_skipped',
                         'guaranteed_success', 'title', 'description', 'volunteer_name'))
    if isinstance(safe.get('description'), str):
        safe['description'] = safe['description'].replace(' Последствия учтены в результате испытания; скрытого бонуса профессиям нет.', '')
    skipped = bool(result.get('is_skipped'))
    safe['outcome'] = ('Вылазка отменена' if skipped else 'Выдающийся успех' if result.get('is_crit_success')
                       else 'Тяжёлый провал' if result.get('is_crit_failure')
                       else 'Успех' if result.get('is_success') else 'Провал')
    safe['consequence'] = ('Никто не выходил на поверхность. Новые припасы не добыты; риска этой вылазки нет.' if skipped
                            else 'Успех испытания помог колонии.' if result.get('is_success')
                            else 'Последствия неудачи осложнят жизнь в убежище.')
    if result.get('health_degraded'):
        safe['health_degraded'] = pick(result['health_degraded'], ('player_id', 'player_name', 'old_condition', 'new_condition'))
    else:
        safe['health_degraded'] = None
    return safe


def public_final(evaluation: dict | None):
    if not evaluation:
        return None
    safe = pick(evaluation, ('is_success', 'title', 'traitor_in_bunker', 'traitor_name'))
    safe['text'] = ('Колония выстояла. Состав команды, оснащение и принятые решения позволили сохранить убежище.'
                    if evaluation.get('is_success') else
                    'Колония не выдержала испытаний. Сочетания ресурсов, навыков и поддержки оказалось недостаточно.')
    needs = {}
    pros, cons = [], []
    breakdown = evaluation.get('breakdown', {})
    for key, row in breakdown.get('needs', {}).items():
        coverage = row.get('coverage', 0)
        tier = 'critical' if coverage < .4 else 'limited' if coverage < .75 else 'secure'
        status = {'critical': 'Критическое', 'limited': 'Ограниченное', 'secure': 'Надёжное'}[tier]
        label = row.get('label', key)
        needs[key] = {'label': label, 'tier': tier, 'status': status}
        (pros if tier == 'secure' else cons).append(f'{label}: '+{
            'critical': 'команда не обеспечила необходимое.',
            'limited': 'возможности остаются ограниченными.',
            'secure': 'потребности надёжно обеспечены.',
        }[tier])
    parts = breakdown.get('score_components', {})
    if parts.get('threat', 0) > 0:
        pros.append('Основная угроза убежища была устранена.')
    elif parts.get('threat', 0) < 0:
        cons.append('Неустранённая угроза осложняла жизнь в убежище.')
    for key, positive, negative in [
        ('events', 'Испытания в целом помогли команде.', 'Неудачные испытания осложнили положение колонии.'),
        ('traitor', 'Диверсант был разоблачён.', 'Оставшийся в убежище диверсант мешал спасению.'),
        ('health', '', 'Потребность в лечении создавала дополнительную нагрузку.'),
        ('overcrowding', '', 'Дополнительным жильцам не хватало пространства.'),
    ]:
        value = parts.get(key, 0)
        if value > 0 and positive:
            pros.append(positive)
        elif value < 0 and negative:
            cons.append(negative)
    age = breakdown.get('age_care', {})
    care_note = None
    if age.get('penalty', 0) > 0:
        care_note = 'Части команды требовалась дополнительная помощь в длительной изоляции.'
        cons.append(care_note)
        if age.get('support_reduction_pct', 0) > 0:
            pros.append('Медицина, оснащение и организация помогали заботиться о нуждающихся в помощи.')
    safe.update(pros=pros, cons=cons, breakdown={'needs': needs}, care_note=care_note, achievements=[])
    return safe


VOTE_FIELDS = ('eliminated_id', 'eliminated_ids', 'eliminated_name', 'is_tie', 'tie_broken_by',
               'threshold_failed', 'revote_completed', 'double_elimination', 'top_candidates',
               'veto_possible', 'abstain_count', 'instant_exile', 'veto_used', 'skipped_round',
               'candidates', 'candidate_names', 'round_number', 'source', 'decision', 'summary_id')


def public_vote(vote: dict | None, total_weight: int):
    if vote is None:
        return None
    safe = pick(vote, VOTE_FIELDS)
    safe['detailed_tally'] = [pick(row, ('player_id', 'player_name', 'votes')) for row in vote.get('detailed_tally', [])]
    safe['counts'] = pick(vote.get('counts', {}), ('total_weight', 'abstain_weight', 'skip_weight',
                                                 'uncast_weight', 'other_weight', 'voters'))
    total = safe['counts'].get('total_weight', total_weight)
    safe['counts'].setdefault('total_weight', total)
    safe['required_votes'] = (7 * total + 9) // 10  # Same rule as server weighted ballot, no round-off.
    safe['top_votes'] = max((row.get('votes', 0) for row in safe['detailed_tally']), default=0)
    return safe


def public_log(entry: dict) -> dict:
    """Compatibility filter for older in-memory logs; new messages are narrative."""
    safe = pick(entry, ('timestamp', 'title', 'text', 'type'))
    text = safe.get('text', '')
    text = re.sub(r'\s*Базовый шанс успеха:.*$', '', text)
    text = re.sub(r'^\d+ на d100 при пороге \d+\.\s*', '', text)
    text = re.sub(r'\s*\(результат испытания:.*?\)', '', text)
    text = re.sub(r'\s*Активирован бонус сплоченности.*$', '', text)
    text = re.sub(r'Рейтинг устойчивости колонии:\s*\d+/100\.?', 'Итог колонии определён.', text)
    text = re.sub(r'\s*\([+−\-]?\d+(?:[.,]\d+)?\s*балл[^)]*\)', '', text)
    text = re.sub(r'\s*\([^)]*п\.п\.[^)]*\)', '', text)
    safe['text'] = text.strip()
    return safe


def public_state(room, raw: dict) -> dict:
    """Single transport boundary for every viewer, including host and spectators."""
    mode = mode_for(room)
    state = copy.deepcopy(raw)
    state.pop('balance_version', None)
    state['information_mode'] = mode
    state['information_policy'] = copy.deepcopy(MODE_INFO[mode])
    state['players'] = [public_player(p) for p in raw['players']]
    state['catastrophe'] = public_catastrophe(raw.get('catastrophe'))
    state['bunker'] = public_bunker(raw.get('bunker'))
    state['final_evaluation'] = public_final(raw.get('final_evaluation'))
    events = raw.get('events_state') or {}
    state['events_state'] = pick(events, ('enabled', 'volunteer_id', 'assigned_volunteer_id', 'is_sortie_skipped'))
    state['events_state'].update(
        active_event=public_event(events.get('active_event')),
        current_odds=public_odds(events.get('current_odds'), mode, skipped=events.get('is_sortie_skipped', False)),
        last_resolved=public_event_result(events.get('last_resolved')),
        resolved_history=[{**pick(h, ('timestamp', 'round')), 'event': public_event(h.get('event')),
                           'result': public_event_result(h.get('result'))} for h in events.get('resolved_history', [])],
    )
    total = state.get('voting_status', {}).get('total_vote_weight', 0)
    state['voting_status']['required_votes'] = (7 * total + 9) // 10
    state['vote_results'] = public_vote(raw.get('vote_results'), total)
    state['last_vote_summary'] = public_vote(raw.get('last_vote_summary'), total)
    if raw.get('result_review'):
        review = state['result_review']
        review['data'] = (public_event_result(raw['result_review']['data']) if review['kind'] == 'event'
                          else public_vote(raw['result_review']['data'], total))
    state['game_log'] = [public_log(entry) for entry in raw.get('game_log', [])]
    return state
