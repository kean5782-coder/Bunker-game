"""Lobby V2: validated, versioned room settings and launch readiness.

No dealt cards, seed or credentials belong in the public settings/profile.
Only lobby edits are accepted; the match freezes a validated snapshot.
"""
from __future__ import annotations
import copy
import time

DEFAULTS = {
    'preset': 'classic', 'game_mode': 'STANDARD', 'deal_mode': 'full_random',
    'information_mode': 'immersion', 'max_players': 20,
    'capacity_mode': 'auto', 'capacity': 3,
    'speech_duration': 60, 'voting_duration': 15,
    'justification_duration': 30, 'revote_duration': 15, 'last_word_duration': 15,
    'enable_events': True, 'event_difficulty': 'normal',
    'enable_traitor': False, 'enable_special_cards': True,
    'initial_reveal': 'mode', 'speaker_order': 'join',
    'catastrophe_id': 'random', 'bunker_id': 'random',
    'show_prologue': True, 'require_ready': False, 'room_locked': False,
}
PRESETS = {
    'classic': {**DEFAULTS},
    'blitz': {**DEFAULTS, 'preset': 'blitz', 'game_mode': 'METEORITE',
              'speech_duration': 30, 'initial_reveal': 'profession_health'},
    'discussion': {**DEFAULTS, 'preset': 'discussion', 'speech_duration': 90,
                   'voting_duration': 30, 'justification_duration': 45,
                   'revote_duration': 30, 'last_word_duration': 30},
    'first_game': {**DEFAULTS, 'preset': 'first_game', 'speech_duration': 90,
                   'voting_duration': 30, 'enable_events': False,
                   'enable_special_cards': False, 'initial_reveal': 'profession'},
}
ENUMS = {
    'preset': set(PRESETS) | {'custom'}, 'game_mode': {'STANDARD', 'METEORITE'},
    'capacity_mode': {'auto', 'manual'}, 'event_difficulty': {'easy', 'normal', 'hard'},
    'initial_reveal': {'mode', 'closed', 'profession', 'profession_health'},
    'speaker_order': {'join', 'random'},
    'information_mode': {'immersion', 'uncertainty'},
    'deal_mode': {'full_random', 'balanced'},
}
BOOLEANS = {k for k, v in DEFAULTS.items() if type(v) is bool}
RANGES = {
    'max_players': (3, 20), 'capacity': (1, 19), 'speech_duration': (30, 180),
    'voting_duration': (10, 120), 'justification_duration': (15, 120),
    'revote_duration': (10, 90), 'last_word_duration': (10, 90),
}
FIELD_NAMES = {'max_players': 'Лимит участников', 'capacity': 'Мест в бункере',
               'speech_duration': 'Первая речь', 'voting_duration': 'Голосование',
               'justification_duration': 'Защита', 'revote_duration': 'Переголосование',
               'last_word_duration': 'Последнее слово'}


def public_catalog():
    from .deck_data import CATASTROPHES, BUNKER_PRESETS
    return {'schema_version': 1, 'defaults': copy.deepcopy(DEFAULTS),
            'presets': copy.deepcopy(PRESETS),
            'catastrophes': copy.deepcopy(CATASTROPHES),
            'bunkers': [{'id': f'bunker_{i:02d}', **copy.deepcopy(b)}
                        for i, b in enumerate(BUNKER_PRESETS)]}


def validate_settings(settings: dict) -> dict:
    if not isinstance(settings, dict):
        raise ValueError('Настройки должны быть объектом.')
    unknown = set(settings) - set(DEFAULTS)
    if unknown:
        raise ValueError('Неизвестные настройки: ' + ', '.join(sorted(unknown)))
    result = {**DEFAULTS, **copy.deepcopy(settings)}
    for key in BOOLEANS:
        if type(result[key]) is not bool:
            raise ValueError(f'Настройка {key} должна быть включена или выключена.')
    for key, choices in ENUMS.items():
        if not isinstance(result[key], str) or result[key] not in choices:
            raise ValueError(f'Недопустимое значение настройки {key}.')
    for key, (low, high) in RANGES.items():
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f'{FIELD_NAMES[key]}: допустимо от {low} до {high}.')
    if result['speech_duration'] % 2:
        raise ValueError('Первая речь должна длиться чётное число секунд: вторая длится ровно половину.')
    if result['capacity'] >= result['max_players'] and result['capacity_mode'] == 'manual':
        raise ValueError('Мест в бункере должно быть меньше лимита участников.')
    cat = public_catalog()
    for key, values in [('catastrophe_id', {c['id'] for c in cat['catastrophes']}),
                        ('bunker_id', {b['id'] for b in cat['bunkers']})]:
        if not isinstance(result[key], str) or result[key] not in values | {'random'}:
            raise ValueError('Выбранный сценарий или бункер отсутствует в колоде.')
    return result


class LobbyMixin:
    def init_lobby(self):
        self.lobby_settings = copy.deepcopy(DEFAULTS)
        self.lobby_revision = 0
        self.lobby_ready = set()
        self.event_difficulty = 'normal'
        self.speaker_order_mode = 'join'
        self.match_seating = []
        self.match_settings = None

    def invalidate_lobby_ready(self):
        if self.phase == 'LOBBY':
            self.lobby_ready.clear()
            self.lobby_revision += 1

    def effective_lobby_capacity(self, settings=None):
        s = settings or self.lobby_settings
        n = len(self.players)
        if s['capacity_mode'] == 'manual':
            return s['capacity']
        return (2 if n >= 5 else 1) if s['game_mode'] == 'METEORITE' else max(1, n // 2)

    def update_lobby_settings(self, player_id, patch, expected_revision=None):
        if player_id != self.host_id:
            raise ValueError('Настройки партии меняет только ведущий.')
        if self.phase != 'LOBBY':
            raise ValueError('Партия уже началась. Настройки лобби заблокированы.')
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision != self.lobby_revision):
            raise ValueError('Состав или настройки комнаты изменились. Проверьте актуальные значения и повторите действие.')
        if not isinstance(patch, dict):
            raise ValueError('Некорректный формат настроек.')
        candidate = validate_settings({**self.lobby_settings, **patch})
        if candidate['max_players'] < len(self.players):
            raise ValueError('Лимит не может быть меньше числа уже вошедших участников.')
        if candidate != self.lobby_settings:
            # A browser may label a modified preset. Verify it rather than trusting its name.
            name = candidate['preset']
            if name in PRESETS:
                ignored = {'preset', 'room_locked', 'require_ready', 'max_players', 'information_mode'}
                if any(candidate[k] != PRESETS[name][k] for k in DEFAULTS if k not in ignored):
                    candidate['preset'] = 'custom'
            self.lobby_settings = candidate
            self.enable_traitor = candidate['enable_traitor']
            self.events_enabled = candidate['enable_events']
            self.game_mode = candidate['game_mode']
            self.speech_duration_sec = candidate['speech_duration']
            self.accusation_duration_sec = candidate['speech_duration'] // 2
            self.debate_duration_sec = self.accusation_duration_sec
            self.voting_duration_sec = candidate['voting_duration']
            self.justification_duration_sec = candidate['justification_duration']
            self.revote_duration_sec = candidate['revote_duration']
            self.last_word_duration_sec = candidate['last_word_duration']
            self.bunker_capacity = self.effective_lobby_capacity()
            self.invalidate_lobby_ready()
            self.last_activity = time.time()
        return copy.deepcopy(self.lobby_settings)

    def set_lobby_ready(self, player_id, ready, expected_revision=None):
        if self.phase != 'LOBBY' or player_id not in self.players:
            raise ValueError('Готовность доступна только участникам лобби.')
        if type(ready) is not bool:
            raise ValueError('Некорректный статус готовности.')
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision != self.lobby_revision):
            raise ValueError('Настройки изменились. Ознакомьтесь с ними и подтвердите готовность заново.')
        if not self.players[player_id].connected:
            raise ValueError('Нет активного подключения.')
        if ready:
            self.lobby_ready.add(player_id)
        else:
            self.lobby_ready.discard(player_id)

    def can_join_lobby(self):
        if self.phase != 'LOBBY':
            raise ValueError('Игра уже началась.')
        if self.lobby_settings['room_locked']:
            raise ValueError('Ведущий закрыл вход в комнату. Попросите его открыть шлюз.')
        if len(self.players) >= self.lobby_settings['max_players']:
            raise ValueError('Достигнут лимит участников комнаты.')

    def lobby_state(self, viewer=None):
        s = self.lobby_settings
        n = len(self.players)
        capacity = self.effective_lobby_capacity()
        ready = {p.id: bool(p.connected and (p.id == self.host_id or p.id.startswith('bot_') or p.id in self.lobby_ready))
                 for p in self.players.values()}
        blockers = []
        if n < 3:
            blockers.append(f'Для старта нужно ещё {3-n} участн. (минимум 3).')
        if n > s['max_players']:
            blockers.append('Число участников превышает лимит.')
        if capacity >= n:
            blockers.append('Мест должно быть меньше, чем участников.')
        offline = [p.name for p in self.players.values() if not p.connected]
        if offline:
            blockers.append('Нет связи: ' + ', '.join(offline) + '. Дождитесь подключения или удалите участника.')
        waiting = [p.name for p in self.players.values() if not ready[p.id]]
        if s['require_ready'] and waiting:
            blockers.append('Ожидается готовность: ' + ', '.join(waiting) + '.')
        return {'settings': copy.deepcopy(s), 'revision': self.lobby_revision,
                'ready': ready, 'ready_count': sum(ready.values()), 'effective_capacity': capacity,
                'can_start': not blockers and self.phase == 'LOBBY', 'blockers': blockers,
                'is_editable': viewer == self.host_id and self.phase == 'LOBBY'}

    def start_configured_game(self, player_id, expected_revision=None):
        if self.phase != 'LOBBY':
            raise ValueError('Игра уже запущена.')
        if player_id != self.host_id:
            raise ValueError('Начать игру может только ведущий.')
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision != self.lobby_revision):
            raise ValueError('Состав или настройки изменились. Проверьте их перед стартом.')
        s = validate_settings(self.lobby_settings)
        status = self.lobby_state(player_id)
        if status['blockers']:
            raise ValueError(status['blockers'][0])
        self.start_game(capacity=status['effective_capacity'], enable_traitor=s['enable_traitor'],
                        enable_events=s['enable_events'], game_mode=s['game_mode'],
                        speech_duration=s['speech_duration'], voting_duration=s['voting_duration'],
                        last_word_duration=s['last_word_duration'], skip_prologue=not s['show_prologue'],
                        lobby_options=s)
        self.match_settings = copy.deepcopy(s)
        self.lobby_ready.clear()

    def ordered_alive_ids(self):
        alive = [p.id for p in self.get_alive_players()]
        if self.speaker_order_mode == 'random' and self.match_seating:
            return [pid for pid in self.match_seating if pid in alive] + [pid for pid in alive if pid not in self.match_seating]
        return alive
