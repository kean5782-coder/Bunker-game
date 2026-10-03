"""One speech of roleplay restrictions. No voice processing or vote penalties."""
from __future__ import annotations

import copy
from functools import wraps
import time
import unicodedata
import uuid

SPEECH_PHASES = ('REVEAL', 'SPEECH', 'ACCUSATION', 'JUSTIFICATION')
SPEECH_CARDS = {
    'speech_style': ('Теперь ты так разговариваешь', 'Говорите в манере, которую задаёт применивший карту. Перед началом он показывает пример.'),
    'speech_word': ('Слово прилипло', 'Вставляйте выбранное слово в каждое предложение.'),
    'speech_questions': ('Я только спрашиваю', 'Говорите только вопросами.'),
    'speech_short': ('Короче', 'Не больше трёх слов в одном предложении.'),
    'speech_third_person': ('Это не я', 'Говорите о себе только в третьем лице.'),
    'speech_advert': ('Продай себя', 'Произнесите свою речь как рекламу.'),
    'speech_rhyme': ('Всё в рифму', 'Пытайтесь рифмовать каждые две соседние фразы. Плохие рифмы засчитываются.'),
    'speech_address': ('Уважаемый огурец', 'Используйте выбранное обращение каждый раз, когда обращаетесь к другому участнику.'),
    'speech_prompter': ('Суфлёр', 'Применивший карту подбрасывает до трёх слов по ходу речи. Каждое нужно вплести в следующую фразу.'),
}
DURATION_TEXT = ' Выберите другого живого игрока. Эффект действует до конца его ближайшего выступления (или текущего, если он уже говорит). Одновременно — одно ограничение. За оговорки штрафов нет.'
INPUTS = {
    'speech_style': {'label': 'Манера речи', 'placeholder': 'Как сонный диктор', 'max_length': 80, 'single_word': False},
    'speech_word': {'label': 'Одно слово', 'placeholder': 'Пельмень', 'max_length': 32, 'single_word': True},
    'speech_address': {'label': 'Обращение', 'placeholder': 'Уважаемый огурец', 'max_length': 60, 'single_word': False},
}


def clean_text(value, *, max_length, single_word=False):
    if not isinstance(value, str):
        raise ValueError('Введите текст ограничения.')
    value = value.strip()
    if not value or len(value) > max_length or any(unicodedata.category(c).startswith('C') for c in value):
        raise ValueError(f'Введите от 1 до {max_length} символов без переносов строк.')
    value = ' '.join(value.split())
    if single_word and not all(part.isalpha() for part in value.replace('’', "'").replace("'", '-').split('-')):
        raise ValueError('Нужно одно слово без пробелов и цифр.')
    return value


def speech_turn(room):
    if room.phase == 'SPEECH':
        speaker = room.get_current_speaker()
    elif room.phase == 'ACCUSATION':
        speaker = room.get_current_accusation_speaker()
    elif room.phase == 'JUSTIFICATION':
        speaker = room.get_current_justification_speaker()
    else:
        return None
    if not speaker or not speaker.is_alive or speaker.is_quarantined:
        return None
    if room.phase == 'SPEECH' and speaker.is_speech_silenced:
        return None
    if room.phase == 'ACCUSATION' and (speaker.is_silenced or speaker.is_speech_silenced):
        return None
    return (room.phase, room.round_number, speaker.id, room.turn_id)


def sync_speech_effects(room):
    current = speech_turn(room)
    for pid, effect in list(room.speech_effects.items()):
        player = room.players.get(pid)
        author = room.players.get(effect['author_id'])
        no_prompter = effect['card_id'] == 'speech_prompter' and (not author or not author.is_alive)
        if not player or not player.is_alive or no_prompter or room.phase in ('LOBBY', 'FINAL'):
            del room.speech_effects[pid]
        elif effect['turn'] is not None and effect['turn'] != current:
            del room.speech_effects[pid]
        elif effect['turn'] is None and current and current[2] == pid:
            effect['turn'] = current


def speech_transition(method):
    """Keep timer, host and ordinary transitions on the same lifecycle path."""
    @wraps(method)
    def wrapped(room, *args, **kwargs):
        sync_speech_effects(room)
        result = method(room, *args, **kwargs)
        sync_speech_effects(room)
        return result
    return wrapped


def validate_target(room, target):
    if target.id in room.speech_effects:
        raise ValueError('У этого игрока уже есть ограничение речи.')
    if target.is_quarantined or target.is_speech_silenced or (room.phase == 'ACCUSATION' and target.is_silenced):
        raise ValueError('Сейчас этому игроку запрещено выступать.')


def option_for(key, value):
    config = INPUTS.get(key)
    if config:
        return clean_text(value, max_length=config['max_length'], single_word=config['single_word'])
    if value not in (None, ''):
        raise ValueError('У этой карты нет настраиваемого текста.')
    return ''


def apply_effect(room, actor, target, key, option):
    title, instruction = SPEECH_CARDS[key]
    if option:
        instruction += ' ' + INPUTS[key]['label'] + ': «' + option + '».'
    turn = speech_turn(room)
    room.speech_effects[target.id] = {
        'id': uuid.uuid4().hex, 'card_id': key, 'title': title,
        'instruction': instruction, 'target_id': target.id, 'author_id': actor.id,
        'author_name': actor.name, 'turn': turn if turn and turn[2] == target.id else None,
        'prompts': [],
    }
    room.log_event('Ограничение речи', f'{target.name}: «{title}». {instruction} На одно выступление.', 'info')


def send_prompt(room, actor_id, target_id, effect_id, index, word):
    room.require_review_finished('SPEECH_PROMPT')
    sync_speech_effects(room)
    if not isinstance(target_id, str) or not isinstance(effect_id, str):
        raise ValueError('Неверная цель подсказки.')
    actor = room.players.get(actor_id)
    effect = room.speech_effects.get(target_id)
    if not actor or not actor.is_alive or actor.is_quarantined:
        raise ValueError('Подсказки сейчас недоступны.')
    if not effect or effect['card_id'] != 'speech_prompter' or effect['id'] != effect_id or effect['author_id'] != actor_id:
        raise ValueError('Вы не суфлёр этого выступления.')
    if effect['turn'] is None or effect['turn'] != speech_turn(room):
        raise ValueError('Дождитесь выступления выбранного игрока.')
    if room.timer_is_paused:
        raise ValueError('Речь на паузе. Дождитесь её продолжения.')
    if type(index) is not int or index != len(effect['prompts']) or index >= 3:
        raise ValueError('Слово уже отправлено или все три подсказки использованы.')
    word = clean_text(word, max_length=32, single_word=True)
    effect['prompts'].append(word)
    room.last_activity = time.time()
    room.log_event('Слово от суфлёра', f'{room.players[target_id].name}: вплетите «{word}» в следующую фразу.', 'info')


def public_effects(room, viewer):
    result = []
    for effect in room.speech_effects.values():
        target = room.players.get(effect['target_id'])
        if not target or not target.is_alive:
            continue
        safe = {k: copy.deepcopy(effect[k]) for k in ('id', 'card_id', 'title', 'instruction', 'target_id', 'author_id', 'author_name', 'prompts')}
        safe['target_name'] = target.name
        safe['active'] = effect['turn'] is not None
        actor = room.players.get(viewer)
        safe['can_prompt'] = bool(effect['card_id'] == 'speech_prompter' and effect['author_id'] == viewer
                                  and actor and actor.is_alive and not actor.is_quarantined
                                  and safe['active'] and len(effect['prompts']) < 3
                                  and not room.timer_is_paused and not room.result_reviews)
        result.append(safe)
    return result
