"""
Движок игровой логики «Бункер».
Управляет состоянием комнаты, игроками, фазами, таймерами, голосованием,
правами хоста (пауза, дебаты, смена фаз, тайбрейк) и опциональным режимом предателя.
"""

import logging
import time
import uuid
import random
import asyncio
from typing import Dict, List, Optional, Any
from .deck_data import (
    generate_game_deck, 
    evaluate_survival, 
    PROFESSIONS, 
    HEALTH_CONDITIONS,
    draw_random_event,
    calculate_event_odds,
    resolve_event_roll,
    is_exile_alive_on_surface
)

logger = logging.getLogger("bunker.engine")

# Доступные фазы игры
PHASE_LOBBY = "LOBBY"
PHASE_SPEECH = "SPEECH"                                 # Защитная речь активного игрока со вскрытием карт
PHASE_COLLECTIVE_DISCUSSION = "COLLECTIVE_DISCUSSION"   # Этап 1 обсуждения: открытый микрофон 60 сек
PHASE_ACCUSATION = "ACCUSATION"                         # Этап 2 обсуждения: раунд обвинений по 30 сек
PHASE_DEBATE = "COLLECTIVE_DISCUSSION"                  # Алиас совместимости со старыми модулями
PHASE_VOTING = "VOTING"                                 # Тайное голосование 15 сек (авто-штраф за AFK)
PHASE_JUSTIFICATION = "JUSTIFICATION"                   # Оправдательная речь 30 сек (если порог < 70% или ничья)
PHASE_REVOTE = "REVOTE"                                 # Переголосование 15 сек между кандидатами на оправдание
PHASE_VOTE_RESULTS = "VOTE_RESULTS"                     # Результаты голосования / Право вето
PHASE_LAST_WORD = "LAST_WORD"                           # Последнее слово изгнанного кандидата (15 сек)
PHASE_FINAL = "FINAL"                                   # Финал и расчет выживаемости в бункере


def get_reveal_quota(total_players: int, round_number: int, unrevealed_count: int) -> int:
    """
    Динамическая таблица норм вскрытия характеристик по числу игроков (Вариант 2Б):
    - До 6 игроков: Р1=3 (включая профессию), Р2=3, Р3=2, Р4+=1
    - 7-8 игроков:  Р1=3 (включая профессию), Р2=2, Р3=2, Р4+=1
    - 9+ игроков:   Р1=2 (включая профессию), Р2=2, Р3=2, Р4+=1
    """
    if unrevealed_count <= 0:
        return 0
    if total_players <= 6:
        table = {1: 3, 2: 3, 3: 2}
        base = table.get(round_number, 1)
    elif total_players <= 8:
        table = {1: 3, 2: 2, 3: 2}
        base = table.get(round_number, 1)
    else:
        table = {1: 2, 2: 2, 3: 2}
        base = table.get(round_number, 1)
    return min(base, unrevealed_count)

class Player:
    def __init__(self, player_id: str, name: str, is_host: bool = False):
        self.id = player_id
        self.name = name
        self.is_host = is_host
        self.is_alive = True
        self.cards: Dict[str, Any] = {}
        self.vote_target: Optional[str] = None
        self.has_immunity = False
        self.double_vote = False
        self.loot_stolen = False
        self.is_silenced = False
        self.connected = True
        self.last_seen = time.time()
        self.last_peeked: Optional[dict] = None

    def to_dict(self, show_all_secret: bool = False, for_player_id: Optional[str] = None) -> dict:
        """
        Преобразует данные игрока в словарь.
        Скрытые карты маскируются для других игроков.
        Секретная роль предателя скрыта от других игроков до финального экрана.
        """
        masked_cards = {}
        is_self = (for_player_id == self.id)

        for cat, card in self.cards.items():
            if cat == "traitor":
                if show_all_secret or is_self:
                    masked_cards[cat] = card
                # Для других игроков не показываем даже заглушку, чтобы не выдать наличие роли
                continue

            if show_all_secret or is_self or card.get("revealed", False):
                masked_cards[cat] = card
            else:
                masked_cards[cat] = {
                    "category": cat,
                    "label": card.get("label", cat),
                    "icon": card.get("icon", "❓"),
                    "value": "🔒 Скрыто",
                    "details": "Характеристика еще не открыта",
                    "revealed": False
                }

        return {
            "id": self.id,
            "name": self.name,
            "is_host": self.is_host,
            "is_alive": self.is_alive,
            "cards": masked_cards,
            "has_voted": self.vote_target is not None,
            "has_immunity": self.has_immunity,
            "is_silenced": self.is_silenced,
            "connected": self.connected,
            "last_peeked": self.last_peeked if is_self else None
        }


class BunkerGameRoom:
    def __init__(self, room_code: str, host_id: str, host_name: str):
        self.room_code = room_code.upper()
        self.host_id = host_id
        self.host_token = str(uuid.uuid4())[:8]
        self.phase = PHASE_LOBBY
        self.round_number = 1
        self.players: Dict[str, Player] = {}
        self.catastrophe: Optional[dict] = None
        self.bunker: Optional[dict] = None
        
        # Настройки игры и режима
        self.game_mode = "STANDARD"          # STANDARD | METEORITE
        self.speech_duration_sec = 45
        self.discussion_duration_sec = 60    # 60 сек на общее обсуждение (Вариант 4Б)
        self.accusation_duration_sec = 30    # 30 сек на обвинения/защиту (Вариант 4Б)
        self.debate_duration_sec = 60        # Совместимость
        self.voting_duration_sec = 15        # 15 сек на тайное голосование (Вариант 5Б)
        self.justification_duration_sec = 30 # 30 сек на оправдательную речь (Вариант 5Б)
        self.revote_duration_sec = 15        # 15 сек на переголосование (Вариант 5Б)
        self.last_word_duration_sec = 15
        self.bunker_capacity = 3
        self.enable_traitor = False
        self.traitor_eliminated = False
        self.last_activity = time.time()

        # Система случайных событий и испытаний
        self.events_enabled = True
        self.active_event: Optional[dict] = None
        self.current_event_odds: Optional[dict] = None
        self.assigned_volunteer_id: Optional[str] = None
        self.resolved_events: List[dict] = []
        self.used_event_ids: List[str] = []
        self.events_score_delta: int = 0
        self.boosted_profession_tags: Dict[str, int] = {}
        self.last_resolved_event: Optional[dict] = None
        self.consecutive_event_failures: int = 0  # Для системы жалости (pity system)

        # Механики изгнанных и спецкарт
        self.veto_used_round: Optional[int] = None
        self.exile_vendetta_used: bool = False
        self.eliminated_in_last_word_id: Optional[str] = None

        # Состояние таймера
        self.timer_seconds_left = 0
        self.timer_is_paused = False

        # Указатель на текущего говорящего игрока (фаза речи)
        self.active_speaker_idx = 0
        self.speakers_order: List[str] = []
        self.turn_revealed_categories: set[str] = set()

        # Этап обвинений
        self.accusation_speakers_order: List[str] = []
        self.active_accusation_speaker_idx: int = 0
        self.debate_speakers_order: List[str] = []  # Совместимость
        self.active_debate_speaker_idx: int = 0      # Совместимость

        # Оправдание и переголосование
        self.justification_candidates: List[str] = []
        self.justification_speakers_order: List[str] = []
        self.active_justification_speaker_idx: int = 0

        # Голосование, скип 1 раунда и двойное изгнание
        self.votes: Dict[str, str] = {}
        self.skip_round_votes: set[str] = set()
        self.double_elimination_pending: bool = False
        self.vote_results: Optional[dict] = None
        self.veto_used = False
        self.is_tiebreaker_active = False

        # Финальный результат
        self.final_evaluation: Optional[dict] = None

        # История логов игры
        self.game_log: List[dict] = []

        # Регистрация хоста
        self.add_player(host_id, host_name, is_host=True)
        self.log_event("Комната создана", f"Ведущий {host_name} открыл шлюзы бункера.")

    def log_event(self, title: str, text: str, alert_type: str = "info"):
        self.game_log.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "title": title,
            "text": text,
            "type": alert_type
        })
        if len(self.game_log) > 60:
            self.game_log.pop(0)

    def add_player(self, player_id: str, name: str, is_host: bool = False) -> Player:
        self.last_activity = time.time()
        if player_id in self.players:
            self.players[player_id].name = name
            self.players[player_id].connected = True
            self.players[player_id].last_seen = time.time()
            return self.players[player_id]

        player = Player(player_id, name, is_host=is_host)
        self.players[player_id] = player
        self.log_event("Новый кандидат", f"{name} прибыл к дверям бункера.")
        return player

    def transfer_host(self, new_host_id: str, new_name: Optional[str] = None):
        """Передает права ведущего новому игроку"""
        self.last_activity = time.time()
        old_host = self.players.get(self.host_id)
        if old_host:
            old_host.is_host = False
            # Если старый хост был авто-сгенерированным плейсхолдером или отключен
            if (not old_host.connected or old_host.name in ["Host", "Ведущий", "host", "HostPlayer"]) and new_host_id != self.host_id:
                if self.host_id in self.players:
                    del self.players[self.host_id]

        if new_host_id in self.players:
            self.players[new_host_id].is_host = True
            if new_name:
                self.players[new_host_id].name = new_name
            self.host_id = new_host_id
            name = self.players[new_host_id].name
        else:
            self.host_id = new_host_id
            p = self.add_player(new_host_id, new_name or "Ведущий", is_host=True)
            name = p.name

        self.log_event("Смена ведущего", f"Права ведущего переданы игроку {name}.", "success")

    def remove_player(self, player_id: str):
        self.last_activity = time.time()
        if player_id in self.players:
            name = self.players[player_id].name
            del self.players[player_id]
            self.log_event("Игрок покинул лобби", f"{name} покинул бункер.", "warning")

    def get_alive_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.is_alive]

    def get_eliminated_players(self) -> List[Player]:
        return [p for p in self.players.values() if not p.is_alive]

    def get_exiled_players(self) -> List[Player]:
        return [p for p in self.players.values() if not p.is_alive]

    def trigger_next_event(self, force_reroll: bool = False):
        """
        Вытягивает случайное событие, совместимое с текущей катастрофой,
        и производит первичный расчет шансов на основе открытых карт.
        """
        if not self.events_enabled or not self.catastrophe:
            return

        cat_id = self.catastrophe.get("id", "")
        ev = draw_random_event(cat_id, self.used_event_ids if not force_reroll else None)
        if not ev:
            return

        self.active_event = ev
        if ev["id"] not in self.used_event_ids:
            self.used_event_ids.append(ev["id"])

        # Автоматический выбор первого добровольца для вылазки
        alive = self.get_alive_players()
        if alive:
            self.assigned_volunteer_id = alive[0].id
        else:
            self.assigned_volunteer_id = None

        self.recalculate_event_odds()

        ev_type_label = "АВАРИЯ В БУНКЕРЕ 🚨" if ev["type"] == "BUNKER_CRISIS" else "ВЫЛАЗКА НА ПОВЕРХНОСТЬ 🪂"
        self.log_event(
            f"🎲 {ev_type_label}: {ev['title']}",
            f"{ev['description']} Базовый шанс успеха: {ev['base_chance']}%. Вскрывайте карты для изменения шанса!",
            "warning"
        )

    def recalculate_event_odds(self):
        """Пересчитывает текущие шансы на основе ТОЛЬКО ОТКРЫТЫХ характеристик"""
        if not self.active_event:
            self.current_event_odds = None
            return

        alive = self.get_alive_players()
        eliminated = self.get_eliminated_players()

        pity = 15 if self.consecutive_event_failures >= 2 else 0

        self.current_event_odds = calculate_event_odds(
            self.active_event,
            alive,
            eliminated,
            volunteer_id=self.assigned_volunteer_id,
            catastrophe=self.catastrophe,
            pity_bonus=pity
        )

    def assign_volunteer(self, player_id: str):
        """Назначение добровольца из бункера на вылазку на поверхность"""
        p = self.players.get(player_id)
        if not p or not p.is_alive:
            raise ValueError("Добровольцем может быть только живой кандидат в бункере!")
        self.assigned_volunteer_id = player_id
        self.recalculate_event_odds()
        self.log_event("Назначен доброволец", f"{p.name} вызвался совершить вылазку на поверхность!", "primary")

    def resolve_active_event(self, force_roll: Optional[int] = None) -> dict:
        """Хост или таймер бросает кубик d100 и разрешает активное событие"""
        if not self.active_event or not self.current_event_odds:
            raise ValueError("Нет активного события для разрешения!")

        result = resolve_event_roll(self.active_event, self.current_event_odds, force_roll=force_roll)
        self.events_score_delta += result["score_delta"]

        if result["is_success"]:
            self.consecutive_event_failures = 0
        else:
            self.consecutive_event_failures += 1

        # Если провал — активируем буст профессий
        if not result["is_success"] and result["boosted_tags"]:
            boost_val = result.get("boost_score", 10)
            for tag in result["boosted_tags"]:
                self.boosted_profession_tags[tag] = max(self.boosted_profession_tags.get(tag, 0), boost_val)

        result["resolved_at"] = time.time()
        self.last_resolved_event = result
        self.resolved_events.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "round": self.round_number,
            "event": self.active_event,
            "result": result
        })

        if result["is_success"]:
            crit_mark = " ⭐ КРИТИЧЕСКИЙ УСПЕХ!" if result.get("is_crit_success") else ""
            self.log_event(
                f"✅ {result['title']}{crit_mark}",
                f"Кубик: {result['roll']} из требуемых {result['chance_required']}%. {result['description']} (+{result['score_delta']}% к шансам бункера)",
                "success"
            )
        else:
            boost_msg = f" {result.get('boost_reason', '')}" if result.get("boost_reason") else ""
            crit_mark = " 💥 КРИТИЧЕСКИЙ ПРОВАЛ!" if result.get("is_crit_failure") else ""
            pity_msg = " Активирован бонус сплоченности (+15% к следующему испытанию)!" if self.consecutive_event_failures >= 2 else ""
            self.log_event(
                f"❌ {result['title']}{crit_mark}",
                f"Кубик: {result['roll']} из требуемых {result['chance_required']}%. {result['description']} ({result['score_delta']}% к шансам бункера).{boost_msg}{pity_msg}",
                "danger"
            )

        # Очищаем активное событие (оно разрешено)
        self.active_event = None
        self.current_event_odds = None
        return result

    def host_toggle_events(self, enabled: bool):
        self.last_activity = time.time()
        self.events_enabled = enabled
        state_str = "включена ✅" if enabled else "отключена ❌"
        self.log_event("Случайные события", f"Ведущий установил: система событий {state_str}.")

    def host_trigger_event(self):
        self.last_activity = time.time()
        self.trigger_next_event(force_reroll=True)

    def start_game(
        self, 
        capacity: Optional[int] = None, 
        enable_traitor: bool = False, 
        enable_events: Optional[bool] = None,
        game_mode: str = "STANDARD",
        speech_time: Optional[int] = None,
        debate_time: Optional[int] = None,
        voting_time: Optional[int] = None,
        speech_duration: Optional[int] = None,
        debate_duration: Optional[int] = None,
        voting_duration: Optional[int] = None,
        last_word_duration: Optional[int] = None
    ):
        """Запуск игры: раздача карт, определение катастрофы, режима и бункера"""
        alive = self.get_alive_players()
        if len(alive) < 3:
            raise ValueError("Для начала игры необходимо минимум 3 игрока!")

        s_time = speech_duration or speech_time
        d_time = debate_duration or debate_time
        v_time = voting_duration or voting_time

        self.last_activity = time.time()
        self.game_mode = game_mode.upper() if game_mode else "STANDARD"
        self.enable_traitor = enable_traitor
        if enable_events is not None:
            self.events_enabled = enable_events
        self.traitor_eliminated = False
        self.consecutive_event_failures = 0
        self.exile_vendetta_used = False
        self.veto_used_round = None

        if last_word_duration:
            self.last_word_duration_sec = last_word_duration

        if self.game_mode == "METEORITE":
            self.speech_duration_sec = s_time or 20
            self.debate_duration_sec = d_time or 30
            self.voting_duration_sec = v_time or 30
            # В режиме «Метеорит» мест крайне мало: 2 места на 5-6 игроков, 1 на 3-4
            if capacity:
                self.bunker_capacity = capacity
            else:
                self.bunker_capacity = 2 if len(alive) >= 5 else 1
        else:
            self.speech_duration_sec = s_time or 45
            self.debate_duration_sec = d_time or 60
            self.voting_duration_sec = v_time or 60
            if capacity:
                self.bunker_capacity = capacity
            else:
                # Оптимально для групп из 6 человек: 3 места (50% выживаемость)
                self.bunker_capacity = max(1, len(alive) // 2)

        deck = generate_game_deck(len(alive), self.bunker_capacity, enable_traitor=self.enable_traitor)
        self.catastrophe = deck["catastrophe"]
        self.bunker = deck["bunker"]

        # Раздаем карты игрокам
        for i, player in enumerate(alive):
            player.cards = deck["players_cards"][i]
            player.is_alive = True
            player.has_immunity = False
            player.double_vote = False
            player.is_silenced = False
            player.loot_stolen = False
            player.last_peeked = None

            # В быстром режиме «Метеорит» профессии и здоровье вскрыты сразу
            if self.game_mode == "METEORITE":
                if "profession" in player.cards:
                    player.cards["profession"]["revealed"] = True
                if "health" in player.cards:
                    player.cards["health"]["revealed"] = True

        self.round_number = 1
        self.start_round()

        # В режиме Метеорит сразу вытягиваем кризис
        if self.game_mode == "METEORITE" and self.events_enabled:
            self.trigger_next_event()

        traitor_msg = " [РЕЖИМ ПРЕДАТЕЛЯ АКТИВИРОВАН ☣️]" if self.enable_traitor else ""
        mode_msg = " ☄️ БЫСТРЫЙ РЕЖИМ «МЕТЕОРИТ»" if self.game_mode == "METEORITE" else ""
        self.log_event(
            f"АПОКАЛИПСИС: {self.catastrophe['title']}{mode_msg}{traitor_msg}",
            f"{self.catastrophe['description']} Мест в бункере: {self.bunker_capacity}.",
            "danger"
        )

    def start_round(self):
        """Начало нового раунда"""
        self.last_activity = time.time()
        alive = self.get_alive_players()

        # Блок 3 (Вариант 3Б): Чередование направления хода по раундам
        # Нечетные раунды (1, 3, 5) — прямой порядок (по часовой стрелке)
        # Четные раунды (2, 4, 6) — реверсивный порядок (обратный порядок)
        if self.round_number % 2 == 0:
            self.speakers_order = list(reversed([p.id for p in alive]))
        else:
            self.speakers_order = [p.id for p in alive]

        # Сброс модификаторов на раунд
        for p in alive:
            p.has_immunity = False
            p.double_vote = False
            p.is_silenced = False
            p.vote_target = None

        self.votes.clear()
        self.skip_round_votes.clear()
        self.vote_results = None
        self.veto_used = False
        self.is_tiebreaker_active = False
        self.active_speaker_idx = 0
        self.turn_revealed_categories.clear()

        self.phase = PHASE_SPEECH
        self.timer_seconds_left = self.speech_duration_sec
        self.timer_is_paused = False
        current_speaker = self.get_current_speaker()
        speaker_name = current_speaker.name if current_speaker else "Никто"
        dir_name = "обратный (реверс раунда)" if self.round_number % 2 == 0 else "прямой"
        self.log_event(f"Раунд {self.round_number}", f"Порядок выступлений: {dir_name}. Слово держит: {speaker_name}.", "primary")

    def get_current_speaker(self) -> Optional[Player]:
        if 0 <= self.active_speaker_idx < len(self.speakers_order):
            speaker_id = self.speakers_order[self.active_speaker_idx]
            return self.players.get(speaker_id)
        return None

    def get_round_reveal_quota(self, player: Optional[Player] = None) -> int:
        """Динамическая норма вскрытия характеристик по числу игроков (Вариант 2Б)"""
        curr = player or self.get_current_speaker()
        if not curr or not curr.is_alive:
            return 0
        unrevealed = [k for k, v in curr.cards.items() if k not in ("traitor", "special") and not v.get("revealed", False)]
        unrevealed_at_start = len(unrevealed) + len(self.turn_revealed_categories)
        if unrevealed_at_start == 0:
            return 0
        total_p = len(self.players)
        return get_reveal_quota(total_p, self.round_number, unrevealed_at_start)

    def can_speaker_proceed(self) -> bool:
        """Проверяет, выполнил ли текущий оратор норму вскрытия карт (Вариант 2Б)"""
        curr = self.get_current_speaker()
        if not curr or not curr.is_alive:
            return True

        # В 1-м раунде обязательна Профессия (если еще не открыта)
        if self.round_number == 1 and "profession" in curr.cards and not curr.cards["profession"].get("revealed", False):
            if "profession" not in self.turn_revealed_categories:
                return False

        required = self.get_round_reveal_quota(curr)
        return len(self.turn_revealed_categories) >= required

    def next_speaker(self, force: bool = False):
        """Переход к следующему оратору или к общей фазе коллективного обсуждения"""
        self.last_activity = time.time()
        curr = self.get_current_speaker()

        if not self.can_speaker_proceed():
            required = self.get_round_reveal_quota(curr) if curr else 1
            if not force:
                raise ValueError(f"Текущий оратор должен вскрыть характеристики ({len(self.turn_revealed_categories)} из {required}) перед передачей слова!")
            else:
                # AFK авто-вскрытие при таймауте таймера
                if curr:
                    if self.round_number == 1 and "profession" in curr.cards and not curr.cards["profession"].get("revealed", False):
                        curr.cards["profession"]["revealed"] = True
                        self.turn_revealed_categories.add("profession")
                        self.log_event("Авто-вскрытие (Таймаут)", f"{curr.name} автоматически вскрыл Профессию: {curr.cards['profession'].get('value')}.", "warning")

                    unrevealed = [k for k, v in curr.cards.items() if k not in ("traitor", "special") and not v.get("revealed", False)]
                    needed = max(0, required - len(self.turn_revealed_categories))
                    for cat in unrevealed[:needed]:
                        curr.cards[cat]["revealed"] = True
                        self.turn_revealed_categories.add(cat)
                        self.log_event("Авто-вскрытие (Таймаут)", f"{curr.name} автоматически вскрыл {curr.cards[cat].get('label')}: {curr.cards[cat].get('value')}.", "warning")

        self.turn_revealed_categories.clear()
        self.active_speaker_idx += 1
        if self.active_speaker_idx < len(self.speakers_order):
            self.timer_seconds_left = self.speech_duration_sec
            self.timer_is_paused = False
            speaker = self.get_current_speaker()
            self.log_event("Смена спикера", f"Слово передано: {speaker.name if speaker else ''}.")
        else:
            # Переход к двухэтапному обсуждению (Вариант 4Б)
            self.start_collective_discussion()

    def start_collective_discussion(self):
        """Этап 1 обсуждения: Коллективное обсуждение (60 сек, открытый микрофон) (Вариант 4Б)"""
        self.last_activity = time.time()
        self.phase = PHASE_COLLECTIVE_DISCUSSION
        self.timer_seconds_left = self.discussion_duration_sec
        self.timer_is_paused = False
        self.log_event(
            "Коллективное обсуждение (60 сек)",
            "Врата приоткрыты: 60 секунд свободного микрофона и общего обсуждения для всех выживших!",
            "warning"
        )

    def start_accusation_phase(self):
        """Этап 2 обсуждения: Раунд обвинений и аргументов (по 30 сек на каждого игрока) (Вариант 4Б)"""
        self.last_activity = time.time()
        self.phase = PHASE_ACCUSATION
        alive = self.get_alive_players()
        if self.round_number % 2 == 0:
            self.accusation_speakers_order = list(reversed([p.id for p in alive]))
        else:
            self.accusation_speakers_order = [p.id for p in alive]
        self.debate_speakers_order = list(self.accusation_speakers_order)
        self.active_accusation_speaker_idx = 0
        self.active_debate_speaker_idx = 0
        self.timer_seconds_left = self.accusation_duration_sec
        self.timer_is_paused = False

        # Пропускаем спикеров с обетом молчания
        while self.active_accusation_speaker_idx < len(self.accusation_speakers_order):
            sp = self.get_current_accusation_speaker()
            if sp and sp.is_silenced:
                self.log_event("Обет молчания", f"{sp.name} хранит обет молчания (пропуск раунда обвинений).", "warning")
                self.active_accusation_speaker_idx += 1
            else:
                break
        self.active_debate_speaker_idx = self.active_accusation_speaker_idx

        if self.active_accusation_speaker_idx < len(self.accusation_speakers_order):
            sp = self.get_current_accusation_speaker()
            sp_name = sp.name if sp else "Кандидат"
            self.log_event("Раунд обвинений", f"Слово для обвинений и аргументов держит: {sp_name} (30 сек).", "warning")
        else:
            self.log_event("Обсуждение завершено", "Все высказали свои претензии. Переход к тайному голосованию!", "warning")
            self.start_voting()

    def get_current_accusation_speaker(self) -> Optional[Player]:
        """Возвращает игрока, чья очередь выступать в раунде обвинений"""
        if self.phase == PHASE_ACCUSATION and 0 <= self.active_accusation_speaker_idx < len(self.accusation_speakers_order):
            sid = self.accusation_speakers_order[self.active_accusation_speaker_idx]
            return self.players.get(sid)
        return None

    def get_current_debate_speaker(self) -> Optional[Player]:
        """Алиас для обратной совместимости"""
        return self.get_current_accusation_speaker()

    def next_accusation_speaker(self):
        """Переход к следующему оратору в раунде обвинений или к голосованию"""
        self.last_activity = time.time()
        if self.phase != PHASE_ACCUSATION:
            return
        self.active_accusation_speaker_idx += 1

        while self.active_accusation_speaker_idx < len(self.accusation_speakers_order):
            sp = self.get_current_accusation_speaker()
            if sp and sp.is_silenced:
                self.log_event("Обет молчания", f"{sp.name} хранит обет молчания (пропуск).", "warning")
                self.active_accusation_speaker_idx += 1
            else:
                break
        self.active_debate_speaker_idx = self.active_accusation_speaker_idx

        if self.active_accusation_speaker_idx < len(self.accusation_speakers_order):
            self.timer_seconds_left = self.accusation_duration_sec
            self.timer_is_paused = False
            sp = self.get_current_accusation_speaker()
            sp_name = sp.name if sp else "Кандидат"
            self.log_event("Слово для обвинений", f"Слово передано: {sp_name} (30 сек).", "info")
        else:
            self.log_event("Обсуждение завершено", "Все высказали свои претензии. Переход к тайному голосованию!", "danger")
            self.start_voting()

    def next_debate_speaker(self):
        """Алиас для обратной совместимости"""
        self.next_accusation_speaker()

    def start_debate(self):
        """Алиас для обратной совместимости"""
        self.start_collective_discussion()

    def host_grant_debate_speaker(self, player_id: str):
        """Ведущий принудительно дает слово конкретному живому игроку"""
        self.last_activity = time.time()
        target = self.players.get(player_id)
        if not target or not target.is_alive:
            raise ValueError("Игрок не найден или выбыл!")

        if self.phase == PHASE_COLLECTIVE_DISCUSSION:
            self.start_accusation_phase()

        if player_id in self.accusation_speakers_order:
            self.active_accusation_speaker_idx = self.accusation_speakers_order.index(player_id)
        else:
            self.accusation_speakers_order.append(player_id)
            self.active_accusation_speaker_idx = len(self.accusation_speakers_order) - 1

        self.active_debate_speaker_idx = self.active_accusation_speaker_idx
        self.timer_seconds_left = self.accusation_duration_sec
        self.timer_is_paused = False
        self.log_event("Ведущий передал слово", f"Ведущий предоставил слово для обвинений/защиты: {target.name} (30 сек).", "primary")

    def host_grant_speech_speaker(self, player_id: str):
        """Ведущий принудительно дает слово конкретному живому игроку во время фазы речи"""
        self.last_activity = time.time()
        if self.phase != PHASE_SPEECH:
            raise ValueError("Фаза защитной речи сейчас не активна!")
        target = self.players.get(player_id)
        if not target or not target.is_alive:
            raise ValueError("Игрок не найден или выбыл!")

        if player_id in self.speakers_order:
            self.active_speaker_idx = self.speakers_order.index(player_id)
        else:
            self.speakers_order.append(player_id)
            self.active_speaker_idx = len(self.speakers_order) - 1

        self.timer_seconds_left = self.speech_duration_sec
        self.timer_is_paused = False
        self.turn_revealed_categories.clear()
        self.log_event("Ведущий передал слово", f"Ведущий предоставил слово для речи: {target.name} ({self.speech_duration_sec} сек).", "primary")

    def start_voting(self):
        """Переход к фазе голосования (15 сек таймер, Вариант 5Б)"""
        self.last_activity = time.time()
        self.phase = PHASE_VOTING
        self.votes.clear()
        self.skip_round_votes.clear()
        for p in self.players.values():
            p.vote_target = None
        self.timer_seconds_left = self.voting_duration_sec
        self.timer_is_paused = False
        skip_hint = " В 1-м раунде доступна кнопка «Пропустить изгнание»." if self.round_number == 1 else ""
        self.log_event("Голосование началось", f"У вас {self.voting_duration_sec} секунд! Не проголосовавшие голосуют против себя.{skip_hint}", "danger")

    def cast_vote(self, voter_id: str, target_id: Optional[str]):
        """Игрок отдает голос против target_id, воздерживается или голосует за пропуск в Р1 (Вариант 5Б)"""
        if self.phase not in (PHASE_VOTING, PHASE_REVOTE):
            raise ValueError("Голосование сейчас не активно!")

        self.last_activity = time.time()
        voter = self.players.get(voter_id)
        if not voter or not voter.is_alive:
            raise ValueError("Выбывшие игроки не могут голосовать!")

        alive = self.get_alive_players()

        # 1. Голосование за пропуск изгнания в 1-м раунде (Вариант 5Б)
        if self.phase == PHASE_VOTING and self.round_number == 1 and target_id in ("SKIP_ROUND", "SKIP"):
            self.skip_round_votes.add(voter_id)
            voter.vote_target = "SKIP_ROUND"
            self.votes[voter_id] = "SKIP_ROUND"
            self.log_event("Голос за пропуск", f"{voter.name} проголосовал за пропуск изгнания в 1-м раунде.", "info")
            if len(self.skip_round_votes) > len(alive) // 2:
                self.finish_skip_round()
                return

        elif target_id in ("ABSTAIN", None, "NONE", ""):
            voter.vote_target = "ABSTAIN"
            self.votes[voter_id] = "ABSTAIN"
            self.log_event("Голос учтен", f"{voter.name} воздержался от голосования.", "info")

        else:
            target = self.players.get(target_id)
            if not target or not target.is_alive:
                raise ValueError("Нельзя голосовать за уже изгнанного игрока!")
            if target.has_immunity:
                raise ValueError(f"{target.name} имеет иммунитет на этом голосовании!")

            # На переголосовании голосуют строго среди кандидатов на оправдание
            if self.phase == PHASE_REVOTE and self.justification_candidates:
                if target_id not in self.justification_candidates:
                    raise ValueError("На переголосовании можно голосовать только за кандидатов из оправдательного раунда!")

            voter.vote_target = target_id
            self.votes[voter_id] = target_id
            self.log_event("Голос учтен", f"{voter.name} сделал свой выбор.", "info")

        # Досрочное завершение: если все живые проголосовали
        connected_alive = [p for p in alive if p.connected]
        target_voters = connected_alive if (connected_alive and len(connected_alive) >= 2) else alive

        if all(p.id in self.votes for p in target_voters) or len(self.votes) >= len(alive):
            if self.phase == PHASE_VOTING:
                self.finish_voting()
            elif self.phase == PHASE_REVOTE:
                self.finish_revote()

    def finish_skip_round(self):
        """Пропуск изгнания в 1-м раунде с активацией двойного изгнания во 2-м (Вариант 5Б)"""
        self.last_activity = time.time()
        self.phase = PHASE_VOTE_RESULTS
        self.double_elimination_pending = True
        self.vote_results = {
            "eliminated_id": None,
            "eliminated_name": None,
            "is_tie": False,
            "threshold_failed": False,
            "skipped_round": True,
            "top_candidates": [],
            "detailed_tally": [],
            "veto_possible": False
        }
        self.timer_seconds_left = 6
        self.log_event(
            "ИЗГНАНИЕ ПРОПУЩЕНО!",
            "Большинство выживших проголосовало за пропуск изгнания в 1-м раунде! Все остаются в бункере, но во 2-м раунде произойдет ДВОЙНОЕ изгнание!",
            "warning"
        )

    def finish_voting(self):
        """Подсчет результатов голосования: порог 70%, авто-штраф AFK и оправдательная речь (Вариант 5Б)"""
        self.last_activity = time.time()
        alive = self.get_alive_players()
        total_voters = len(alive)

        # Авто-штраф за таймаут: не проголосовавшие голосуют против СЕБЯ (Вариант 5Б)
        for p in alive:
            if p.id not in self.votes or self.votes[p.id] is None:
                p.vote_target = p.id
                self.votes[p.id] = p.id
                self.log_event("Штрафной голос (Таймаут)", f"{p.name} не успел проголосовать и автоматически проголосовал против себя!", "warning")

        # Проверка скипа 1-го раунда
        if self.round_number == 1 and len(self.skip_round_votes) > total_voters // 2:
            self.finish_skip_round()
            return

        tally: Dict[str, int] = {}
        abstain_count = 0

        for voter_id, target_id in self.votes.items():
            voter = self.players.get(voter_id)
            weight = 2 if voter and voter.double_vote else 1
            if target_id in ("ABSTAIN", "SKIP_ROUND"):
                abstain_count += weight
            elif target_id:
                tally[target_id] = tally.get(target_id, 0) + weight

        detailed_tally = []
        for cid, v in sorted(tally.items(), key=lambda x: x[1], reverse=True):
            p = self.players.get(cid)
            pct = round((v / total_voters) * 100, 1) if total_voters > 0 else 0
            detailed_tally.append({
                "player_id": cid,
                "player_name": p.name if p else "Неизвестно",
                "votes": v,
                "percent": pct
            })

        if not tally:
            self.phase = PHASE_VOTE_RESULTS
            self.vote_results = {
                "eliminated_id": None,
                "eliminated_name": None,
                "is_tie": False,
                "threshold_failed": True,
                "abstain_count": abstain_count,
                "top_candidates": [],
                "detailed_tally": [],
                "veto_possible": False
            }
            self.timer_seconds_left = 6
            self.log_event("Никто не изгнан!", "Все участники воздержались от голосования. Никто не покидает бункер!", "warning")
            return

        sorted_tally = sorted(tally.items(), key=lambda x: x[1], reverse=True)
        max_votes = sorted_tally[0][1]
        top_candidates = [cid for cid, v in sorted_tally if v == max_votes]
        max_percent = (max_votes / total_voters) * 100 if total_voters > 0 else 0

        # Двойное изгнание во 2-м раунде при пропуске в 1-м (Вариант 5Б)
        if self.double_elimination_pending and len(sorted_tally) >= 2:
            first_votes = sorted_tally[0][1]
            second_votes = sorted_tally[1][1]
            ties_for_second = [cid for cid, v in sorted_tally if v == second_votes]
            if len(top_candidates) == 1 and len(ties_for_second) == 1:
                elim_ids = [sorted_tally[0][0], sorted_tally[1][0]]
                elim_names = f"{self.players[elim_ids[0]].name} и {self.players[elim_ids[1]].name}"
                self.phase = PHASE_VOTE_RESULTS
                self.vote_results = {
                    "eliminated_id": elim_ids[0],
                    "eliminated_ids": elim_ids,
                    "eliminated_name": elim_names,
                    "is_tie": False,
                    "threshold_failed": False,
                    "double_elimination": True,
                    "top_candidates": elim_ids,
                    "detailed_tally": detailed_tally,
                    "veto_possible": True
                }
                self.timer_seconds_left = 10
                self.log_event(
                    "ДВОЙНОЕ ИЗГНАНИЕ!",
                    f"По итогам голосования бункер покидают двое: {elim_names}!",
                    "danger"
                )
                return
            else:
                cand_set = list(dict.fromkeys(top_candidates + ties_for_second))
                self.start_justification(cand_set, is_tie=True, detailed_tally=detailed_tally, max_percent=max_percent)
                return

        # Порог 70% голосов (Вариант 5Б):
        # Если кандидат набрал >= 70% и нет ничьей -> моментальное изгнание!
        # Если кандидат набрал < 70% или возникла ничья -> Оправдательная речь 30 сек и переголосование!
        if max_percent >= 70.0 and len(top_candidates) == 1:
            eliminated_id = top_candidates[0]
            elim_name = self.players[eliminated_id].name
            self.phase = PHASE_VOTE_RESULTS
            self.vote_results = {
                "eliminated_id": eliminated_id,
                "eliminated_ids": [eliminated_id],
                "eliminated_name": elim_name,
                "is_tie": False,
                "threshold_failed": False,
                "instant_exile": True,
                "max_percent": round(max_percent, 1),
                "abstain_count": abstain_count,
                "top_candidates": top_candidates,
                "detailed_tally": detailed_tally,
                "veto_possible": True
            }
            self.timer_seconds_left = 10
            self.log_event(
                "МОМЕНТАЛЬНОЕ ИЗГНАНИЕ (≥70%)!",
                f"{elim_name} набрал {max_votes} из {total_voters} голосов ({round(max_percent, 1)}% ≥ 70%)! Изгнание без права на оправдание.",
                "danger"
            )
            return

        # Иначе: запускаем оправдательную речь кандидатам (Вариант 5Б)
        self.start_justification(top_candidates, is_tie=(len(top_candidates) > 1), detailed_tally=detailed_tally, max_percent=max_percent)

    def start_justification(self, candidates: List[str], is_tie: bool, detailed_tally: list, max_percent: float):
        """Фаза оправдательной речи (30 сек кандидатам) (Вариант 5Б)"""
        self.last_activity = time.time()
        self.phase = PHASE_JUSTIFICATION
        self.justification_candidates = list(candidates)
        self.justification_speakers_order = list(candidates)
        self.active_justification_speaker_idx = 0
        self.timer_seconds_left = self.justification_duration_sec
        self.timer_is_paused = False

        c_names = ", ".join([self.players[cid].name for cid in candidates if cid in self.players])
        if is_tie:
            reason = f"Ничья ({c_names})"
        else:
            reason = f"Лидер ({c_names}) набрал {round(max_percent, 1)}% голосов (< 70% для моментального изгнания)"

        curr_sp = self.get_current_justification_speaker()
        curr_name = curr_sp.name if curr_sp else "Кандидат"
        self.log_event(
            "Оправдательная речь (30 сек)!",
            f"{reason}. Слово для защиты держит: {curr_name}.",
            "warning"
        )

    def get_current_justification_speaker(self) -> Optional[Player]:
        if self.phase == PHASE_JUSTIFICATION and 0 <= self.active_justification_speaker_idx < len(self.justification_speakers_order):
            sid = self.justification_speakers_order[self.active_justification_speaker_idx]
            return self.players.get(sid)
        return None

    def next_justification_speaker(self):
        """Переход к следующему спикеру на оправдании или к переголосованию"""
        self.last_activity = time.time()
        if self.phase != PHASE_JUSTIFICATION:
            return
        self.active_justification_speaker_idx += 1
        if self.active_justification_speaker_idx < len(self.justification_speakers_order):
            self.timer_seconds_left = self.justification_duration_sec
            self.timer_is_paused = False
            sp = self.get_current_justification_speaker()
            sp_name = sp.name if sp else "Кандидат"
            self.log_event("Слово для оправдания", f"Слово передано: {sp_name} (30 сек).", "warning")
        else:
            self.start_revote()

    def start_revote(self):
        """Фаза переголосования (15 сек) строго между кандидатами на оправдание (Вариант 5Б)"""
        self.last_activity = time.time()
        self.phase = PHASE_REVOTE
        self.votes.clear()
        for p in self.players.values():
            p.vote_target = None
        self.timer_seconds_left = self.revote_duration_sec
        self.timer_is_paused = False
        c_names = ", ".join([self.players[cid].name for cid in self.justification_candidates if cid in self.players])
        self.log_event(
            "ПЕРЕГОЛОСОВАНИЕ (15 сек)!",
            f"Голосуйте строго между кандидатами: {c_names}. Побеждает простое большинство!",
            "danger"
        )

    def finish_revote(self):
        """Подсчет итогов переголосования (простое большинство) (Вариант 5Б)"""
        self.last_activity = time.time()
        self.phase = PHASE_VOTE_RESULTS
        alive = self.get_alive_players()
        total_voters = len(alive)

        # AFK авто-голос
        for p in alive:
            if p.id not in self.votes or self.votes[p.id] is None:
                p.vote_target = p.id
                self.votes[p.id] = p.id

        tally: Dict[str, int] = {}
        for voter_id, target_id in self.votes.items():
            if target_id in self.justification_candidates:
                voter = self.players.get(voter_id)
                weight = 2 if voter and voter.double_vote else 1
                tally[target_id] = tally.get(target_id, 0) + weight

        detailed_tally = []
        for cid in self.justification_candidates:
            v = tally.get(cid, 0)
            p = self.players.get(cid)
            pct = round((v / total_voters) * 100, 1) if total_voters > 0 else 0
            detailed_tally.append({
                "player_id": cid,
                "player_name": p.name if p else "Неизвестно",
                "votes": v,
                "percent": pct
            })

        detailed_tally.sort(key=lambda x: x["votes"], reverse=True)
        if self.double_elimination_pending and len(detailed_tally) >= 2:
            elim_ids = [detailed_tally[0]["player_id"], detailed_tally[1]["player_id"]]
            elim_names = f"{self.players[elim_ids[0]].name} и {self.players[elim_ids[1]].name}"
            self.vote_results = {
                "eliminated_id": elim_ids[0],
                "eliminated_ids": elim_ids,
                "eliminated_name": elim_names,
                "is_tie": False,
                "threshold_failed": False,
                "revote_completed": True,
                "double_elimination": True,
                "detailed_tally": detailed_tally,
                "top_candidates": elim_ids,
                "veto_possible": True
            }
            elim_name = elim_names
        else:
            eliminated_id = detailed_tally[0]["player_id"] if detailed_tally and detailed_tally[0]["votes"] > 0 else random.choice(self.justification_candidates)
            elim_name = self.players[eliminated_id].name if eliminated_id in self.players else "Кандидат"
            self.vote_results = {
                "eliminated_id": eliminated_id,
                "eliminated_ids": [eliminated_id],
                "eliminated_name": elim_name,
                "is_tie": False,
                "threshold_failed": False,
                "revote_completed": True,
                "detailed_tally": detailed_tally,
                "top_candidates": [eliminated_id],
                "veto_possible": True
            }
        self.timer_seconds_left = 10
        self.log_event("Итоги переголосования", f"По итогам переголосования большинство голосов отдано за изгнание: {elim_name}.", "danger")

    def host_start_tiebreaker(self):
        """Запуск тайбрейка ведущим при необходимости"""
        if self.vote_results and self.vote_results.get("top_candidates"):
            self.start_justification(self.vote_results["top_candidates"], is_tie=True, detailed_tally=self.vote_results.get("detailed_tally", []), max_percent=50.0)

    def confirm_elimination(self, player_id: Optional[str] = None):
        """Окончательное исключение игрока и переход к последнему слову или следующему раунду"""
        self.last_activity = time.time()
        if self.phase != PHASE_VOTE_RESULTS:
            return

        targets = []
        if player_id:
            targets = [player_id]
        elif self.vote_results:
            if self.vote_results.get("eliminated_ids"):
                targets = [pid for pid in self.vote_results["eliminated_ids"] if pid in self.players]
            elif self.vote_results.get("eliminated_id"):
                targets = [self.vote_results["eliminated_id"]]

        if targets:
            for target_id in targets:
                p = self.players.get(target_id)
                if not p or not p.is_alive:
                    continue
                p.is_alive = False

                # Проверяем, был ли изгнанный предателем
                if "traitor" in p.cards:
                    self.traitor_eliminated = True
                    self.log_event("ДИВЕРСАНТ ИЗГНАН!", f"{p.name} оказался агентом с секретной миссией и был выброшен наружу!", "success")
                else:
                    self.log_event("ИЗГНАН НА ПОВЕРХНОСТЬ", f"Гермошлюз открывается для {p.name}. Он остается снаружи.", "danger")

                # Проверка мародерства (спецкарта steal_loot)
                for other in self.players.values():
                    if other.is_alive and other.loot_stolen:
                        loot_card = p.cards.get("backpack") or p.cards.get("big_inventory") or p.cards.get("baggage")
                        if loot_card:
                            other.cards["stolen_baggage"] = loot_card
                            other.loot_stolen = False
                            self.log_event("Мародерство", f"{other.name} присвоил себе снаряжение изгнанного ({loot_card.get('value', '')})!", "warning")

                # Раскрываем ВСЕ оставшиеся карты изгнанного перед всеми
                for cat, card in p.cards.items():
                    if cat != "traitor" or self.enable_traitor:
                        card["revealed"] = True

            self.double_elimination_pending = False

            # Автоматический бросок кубика d100 по текущему испытанию после изгнания
            if self.events_enabled and self.active_event:
                self.recalculate_event_odds()
                if self.current_event_odds:
                    ev_title = self.active_event.get("title", "Испытание")
                    ch = self.current_event_odds.get("final_chance", 50)
                    self.log_event(
                        "ИСПЫТАНИЕ ПОСЛЕ ИЗГНАНИЯ 🎲",
                        f"Изгнание совершено! Кризис «{ev_title}» разрешается с обновленным шансом: {ch}%.",
                        "primary"
                    )
                    self.resolve_active_event()

            # Запускаем фазу «Последнее слово» (15 секунд)
            names_str = ", ".join([self.players[tid].name for tid in targets if tid in self.players])
            first_id = targets[0]
            self.phase = PHASE_LAST_WORD
            self.eliminated_in_last_word_id = first_id
            self.timer_seconds_left = self.last_word_duration_sec
            self.timer_is_paused = False
            self.log_event(
                "ПОСЛЕДНЕЕ СЛОВО 🎙️",
                f"Гермошлюз открыт: {names_str} получает {self.last_word_duration_sec} сек на последнее слово! Все карты раскрыты.",
                "warning"
            )
            return
        else:
            self.log_event("Раунд завершен", "По итогам голосования никто не изгнан. Все выжившие продолжают борьбу!", "info")
            # Если никто не изгнан, испытание также разрешается со всеми выжившими
            if self.events_enabled and self.active_event:
                self.recalculate_event_odds()
                if self.current_event_odds:
                    ev_title = self.active_event.get("title", "Испытание")
                    ch = self.current_event_odds.get("final_chance", 50)
                    self.log_event(
                        "ИСПЫТАНИЕ РАУНДА 🎲",
                        f"Никто не изгнан. Кризис «{ev_title}» разрешается текущим составом выживших: {ch}%.",
                        "primary"
                    )
                    self.resolve_active_event()

        alive = self.get_alive_players()
        if len(alive) <= self.bunker_capacity:
            self.trigger_final()
        else:
            self.round_number += 1
            if self.events_enabled:
                self.trigger_next_event()
            self.start_round()

    def finish_last_word(self):
        """Завершение фазы последнего слова и переход к следующему раунду или финалу"""
        self.last_activity = time.time()
        self.eliminated_in_last_word_id = None
        alive = self.get_alive_players()
        if len(alive) <= self.bunker_capacity:
            self.trigger_final()
        else:
            self.round_number += 1
            if self.events_enabled:
                self.trigger_next_event()
            self.start_round()

    def trigger_final(self):
        """Финал игры: оценка выживания оставшихся в бункере"""
        self.last_activity = time.time()
        self.phase = PHASE_FINAL
        alive = self.get_alive_players()
        survivor_dicts = [p.to_dict(show_all_secret=True) for p in alive]
        self.final_evaluation = evaluate_survival(
            survivor_dicts, 
            self.catastrophe, 
            self.bunker,
            traitor_eliminated=self.traitor_eliminated,
            events_score_delta=self.events_score_delta,
            boosted_profession_tags=self.boosted_profession_tags,
            resolved_events_history=self.resolved_events
        )
        self.log_event(
            "ГЕРМОДВЕРЬ ЗАПЕРТА!",
            f"В бункере спаслись {len(alive)} человек. Шанс на выживание колонии: {self.final_evaluation['survival_percent']}%.",
            "primary"
        )

    # --- Управление картами игроков ---

    def reveal_player_card(self, player_id: str, category: str):
        """Игрок вскрывает свою карту во время своего хода речи"""
        self.last_activity = time.time()
        player = self.players.get(player_id)
        if not player or not player.is_alive:
            raise ValueError("Игрок не найден или выбыл из игры!")

        # 1. Защита по фазе игры: вскрывать черты можно ТОЛЬКО в фазе защитной речи
        if self.phase != PHASE_SPEECH:
            raise ValueError("Вскрывать характеристики разрешено только во время фазы защитной речи (SPEECH)!")

        # 2. Защита по очереди хода: вскрывать может ТОЛЬКО текущий активный спикер
        curr = self.get_current_speaker()
        if not curr or curr.id != player_id:
            speaker_name = curr.name if curr else "другой кандидат"
            raise ValueError(f"Сейчас не ваш ход речи! Слово держит: {speaker_name}.")

        # 3. Служебные и секретные карты нельзя раскрывать через обычное вскрытие
        if category in ("traitor", "special"):
            raise ValueError("Эту карту нельзя вскрыть как обычную характеристику!")

        if category not in player.cards:
            raise ValueError("Неизвестная категория карты!")

        card = player.cards[category]
        if card.get("revealed", False):
            raise ValueError("Эта характеристика уже рассекречена!")

        # 4. Базовое правило: В 1-м раунде всегда первой открывается Профессия
        if self.round_number == 1 and category != "profession":
            prof_card = player.cards.get("profession")
            if prof_card and not prof_card.get("revealed", False):
                raise ValueError("В 1-м раунде сначала необходимо обязательно открыть Профессию!")

        # 5. Защита от раскрытия большего количества черт, чем положено по лимиту хода (Вариант 2Б)
        allowed_quota = self.get_round_reveal_quota(player)

        if len(self.turn_revealed_categories) >= allowed_quota:
            raise ValueError(f"Вы уже открыли максимальное количество характеристик на этот ход ({allowed_quota})!")

        card["revealed"] = True
        self.turn_revealed_categories.add(category)

        self.log_event("Карта раскрыта", f"{player.name} вскрыл {card.get('label')}: {card.get('value')}.", "info")
        if self.active_event:
            self.recalculate_event_odds()

    def use_special_card(self, player_id: str, target_player_id: Optional[str] = None):
        """Активация спецкарты игрока"""
        self.last_activity = time.time()
        player = self.players.get(player_id)
        if not player or not player.is_alive:
            raise ValueError("Игрок не найден или выбыл!")

        special = player.cards.get("special")
        if not special or special.get("used", False):
            raise ValueError("Спецкарта уже использована или отсутствует!")

        card_id = special.get("card_id")
        special["used"] = True
        special["revealed"] = True

        if card_id == "heal_illness":
            target = self.players.get(target_player_id or player_id)
            if target and "health" in target.cards:
                target.cards["health"]["value"] = "Абсолютно здоров (Исцелен)"
                target.cards["health"]["details"] = "Болезнь полностью вылечена специальной картой."
                target.cards["health"]["severity"] = "good"
                target.cards["health"]["revealed"] = True
                self.log_event("Медицинское чудо!", f"{player.name} исцелил болезни игрока {target.name}!", "success")

        elif card_id == "swap_baggage":
            target = self.players.get(target_player_id)
            if target and target.id != player.id and "baggage" in target.cards:
                my_baggage = player.cards["baggage"]
                target_baggage = target.cards["baggage"]
                player.cards["baggage"], target.cards["baggage"] = target_baggage, my_baggage
                player.cards["baggage"]["revealed"] = True
                target.cards["baggage"]["revealed"] = True
                self.log_event("Обмен рюкзаками", f"{player.name} обменялся багажом с {target.name}!", "warning")

        elif card_id == "force_reveal":
            target = self.players.get(target_player_id)
            if target:
                unrevealed = [k for k, v in target.cards.items() if not v.get("revealed", False) and k not in ["special", "traitor"]]
                if unrevealed:
                    cat = random.choice(unrevealed)
                    target.cards[cat]["revealed"] = True
                    self.log_event("Принудительный досмотр", f"{player.name} заставил {target.name} открыть {target.cards[cat]['label']}: {target.cards[cat]['value']}!", "warning")

        elif card_id == "veto_vote":
            if self.phase != PHASE_VOTE_RESULTS:
                raise ValueError("Право Вето можно применить только во время объявления итогов голосования!")
            if not self.vote_results or not self.vote_results.get("eliminated_id"):
                raise ValueError("Сейчас нет кандидата на изгнание, чтобы применить Вето!")
            if self.veto_used_round is not None and (self.round_number - self.veto_used_round) <= 1:
                raise ValueError("Право Вето перезаряжается (кулдаун 1 раунд после использования)!")
            self.veto_used = True
            self.veto_used_round = self.round_number
            self.vote_results["eliminated_id"] = None
            self.vote_results["veto_used"] = True
            self.log_event("ПРАВО ВЕТО!", f"{player.name} применил Право Вето! В этом раунде никто не изгоняется.", "success")

        elif card_id == "extra_bunk":
            self.bunker_capacity += 1
            if self.bunker:
                self.bunker["capacity"] = self.bunker_capacity
            self.log_event("Найдено койко-место!", f"{player.name} нашел дополнительный отсек! Вместимость бункера: {self.bunker_capacity} (перенаселение дает штраф -5% к выживаемости).", "success")

        elif card_id == "double_vote":
            player.double_vote = True
            self.log_event("Двойной мандат", f"{player.name} имеет 2 голоса на текущем голосовании!", "info")

        elif card_id == "round_immunity":
            player.has_immunity = True
            self.log_event("Неприкосновенность", f"{player.name} получил полный иммунитет от голосования в этом раунде!", "success")

        elif card_id == "reroll_profession":
            new_prof = random.choice(PROFESSIONS)
            player.cards["profession"] = {
                "category": "profession",
                "label": "Профессия",
                "icon": "💼",
                "value": f"{new_prof['name']} ({new_prof['exp']})",
                "details": new_prof["desc"],
                "tag": new_prof["tag"],
                "revealed": True
            }
            self.log_event("Переквалификация", f"{player.name} сменил профессию на: {new_prof['name']}.", "info")

        elif card_id == "change_health":
            new_health = random.choice(HEALTH_CONDITIONS)
            player.cards["health"] = {
                "category": "health",
                "label": "Здоровье",
                "icon": "❤️",
                "value": new_health["name"],
                "details": new_health["desc"],
                "severity": new_health["severity"],
                "revealed": True
            }
            self.log_event("Вакцинация и лечение", f"{player.name} обновил карту здоровья: {new_health['name']}.", "success")

        elif card_id == "silence_player":
            target = self.players.get(target_player_id)
            if not target or not target.is_alive:
                raise ValueError("Цель не найдена или уже выбыла!")
            target.is_silenced = True
            self.log_event(
                "ОБЕТ МОЛЧАНИЯ 🔇", 
                f"{player.name} наложил Обет молчания на игрока {target.name}! Игрок обязан вскрывать характеристики в свой ход, но не имеет права говорить голосом или в дебатах в этом раунде!", 
                "warning"
            )

        elif card_id == "threat_fix":
            if self.bunker:
                self.bunker["threat_fixed"] = True
                self.bunker["threat"] = "Нейтрализована ремонтным комплектом!"
                self.log_event("Ремонтный комплект!", f"{player.name} устранил критическую угрозу бункера!", "success")

        elif card_id == "secret_peek":
            target = self.players.get(target_player_id)
            if not target or target.id == player.id:
                raise ValueError("Выберите другого игрока для подглядывания!")
            unrevealed = [c for c in target.cards.values() if not c.get("revealed", False) and c.get("category") not in ["special", "traitor"]]
            if not unrevealed:
                raise ValueError("У выбранного игрока нет закрытых характеристик!")
            peeked = random.choice(unrevealed)
            player.last_peeked = {
                "target_id": target.id,
                "target_name": target.name,
                "category": peeked.get("category", ""),
                "label": peeked.get("label", ""),
                "value": peeked.get("value", ""),
                "details": peeked.get("details", "")
            }
            self.log_event("Тайный шпионаж 🔍", f"{player.name} изучил закрытые данные досье игрока {target.name}!", "info")

        elif card_id == "steal_loot":
            player.loot_stolen = True
            self.log_event("Мародерство активировано", f"{player.name} подготовил мешок для багажа следующего изгнанного.", "warning")

        else:
            self.log_event("Спецкарта сыграна", f"{player.name} использовал: {special.get('title')}.", "info")

    def announce_peeked(self, player_id: str):
        """Игрок, подсмотревший чужую карту через secret_peek, объявляет её вслух и вскрывает для всех"""
        self.last_activity = time.time()
        player = self.players.get(player_id)
        if not player or not player.is_alive:
            raise ValueError("Игрок не найден или выбыл!")
        if not player.last_peeked:
            raise ValueError("У вас нет подсмотренных данных для объявления!")
        target_id = player.last_peeked.get("target_id")
        category = player.last_peeked.get("category")
        target = self.players.get(target_id)
        if not target:
            raise ValueError("Цель шпионажа не найдена!")
        card = target.cards.get(category)
        if card:
            card["revealed"] = True
        self.log_event(
            "ГРОМКОЕ РАЗОБЛАЧЕНИЕ 📢",
            f"{player.name} во всеуслышание рассекретил карту {target.name}! «{player.last_peeked.get('label')}»: {player.last_peeked.get('value')}.",
            "warning"
        )
        player.last_peeked = None

    def trigger_exile_vendetta(self, player_id: str):
        """Изгнанный игрок, выживший на поверхности, может отомстить бункеру (1 раз за игру)"""
        self.last_activity = time.time()
        player = self.players.get(player_id)
        if not player or player.is_alive:
            raise ValueError("Только изгнанные игроки могут совершить вендетту!")
        if self.exile_vendetta_used:
            raise ValueError("Вендетта изгнанных уже была совершена в этой игре!")
        if self.phase in (PHASE_LOBBY, PHASE_FINAL):
            raise ValueError("Вендетту нельзя применить в этой фазе!")
        
        # Проверяем, выжил ли изгнанник на поверхности
        alive_surface, reason = is_exile_alive_on_surface(player.cards, self.catastrophe)
        if not alive_surface:
            raise ValueError(f"Вы не выжили на поверхности ({reason}) и не можете отомстить бункеру!")
        
        self.exile_vendetta_used = True
        self.events_score_delta -= 5
        self.log_event(
            "ВЕНДЕТТА ИЗГНАННЫХ! ⚡☠️",
            f"Выживший на поверхности {player.name} ({reason}) совершил диверсию против бункера снаружи! Шанс выживания бункера снижен на 5%.",
            "danger"
        )

    # --- ПРАВА ВЕДУЩЕГО (HOST CONTROLS) ---

    def host_pause_timer(self, is_paused: Optional[bool] = None):
        self.last_activity = time.time()
        if is_paused is None:
            self.timer_is_paused = not self.timer_is_paused
        else:
            self.timer_is_paused = is_paused
        state = "на паузе ⏸️" if self.timer_is_paused else "возобновлен ▶️"
        self.log_event("Таймер", f"Ведущий установил таймер {state}.")

    def host_add_time(self, seconds: int = 30):
        self.last_activity = time.time()
        self.timer_seconds_left = max(0, self.timer_seconds_left + seconds)
        self.log_event("Добавлено время", f"Ведущий добавил +{seconds} сек к текущему таймеру.")

    def host_restart_phase(self):
        self.last_activity = time.time()
        if self.phase == PHASE_SPEECH:
            self.timer_seconds_left = self.speech_duration_sec
            self.timer_is_paused = False
            self.log_event("Перезапуск речи", "Ведущий перезапустил время защитной речи.")
        elif self.phase == PHASE_DEBATE:
            self.timer_seconds_left = self.debate_duration_sec
            self.timer_is_paused = False
            sp = self.get_current_debate_speaker()
            self.log_event("Перезапуск речи на дебатах", f"Ведущий перезапустил время для спикера {sp.name if sp else ''} ({self.debate_duration_sec} сек).", "info")
        elif self.phase == PHASE_VOTING:
            self.start_voting()
            self.log_event("Переголосование", "Ведущий объявил повторное голосование!", "warning")

    def host_set_phase(self, new_phase: str):
        self.last_activity = time.time()
        if new_phase == PHASE_SPEECH:
            self.phase = PHASE_SPEECH
            self.timer_seconds_left = self.speech_duration_sec
            self.timer_is_paused = False
        elif new_phase == PHASE_DEBATE:
            self.start_debate()
        elif new_phase == PHASE_VOTING:
            self.start_voting()
        elif new_phase == PHASE_VOTE_RESULTS:
            self.finish_voting()
        elif new_phase == PHASE_LAST_WORD:
            self.phase = PHASE_LAST_WORD
            self.timer_seconds_left = self.last_word_duration_sec
            self.timer_is_paused = False
        elif new_phase == PHASE_FINAL:
            self.trigger_final()
        self.log_event("Смена фазы", f"Ведущий принудительно переключил фазу на: {new_phase}.", "primary")

    def host_eliminate_player(self, player_id: str):
        self.confirm_elimination(player_id)

    def host_restore_player(self, player_id: str):
        self.last_activity = time.time()
        if player_id in self.players:
            self.players[player_id].is_alive = True
            self.log_event("Помилование", f"Ведущий вернул {self.players[player_id].name} в список выживших.", "success")

    def host_adjust_capacity(self, new_capacity: int):
        self.last_activity = time.time()
        self.bunker_capacity = max(1, new_capacity)
        if self.bunker:
            self.bunker["capacity"] = self.bunker_capacity
        self.log_event("Вместимость бункера", f"Ведущий изменил лимит мест до {self.bunker_capacity}.")

    def tick_timer(self) -> bool:
        if self.timer_is_paused or self.timer_seconds_left <= 0:
            return False

        self.timer_seconds_left -= 1

        if self.timer_seconds_left <= 0:
            if self.phase == PHASE_SPEECH:
                self.next_speaker(force=True)
            elif self.phase == PHASE_COLLECTIVE_DISCUSSION:
                self.start_accusation_phase()
            elif self.phase == PHASE_ACCUSATION:
                self.next_accusation_speaker()
            elif self.phase == PHASE_DEBATE:
                self.next_debate_speaker()
            elif self.phase == PHASE_VOTING:
                self.finish_voting()
            elif self.phase == PHASE_JUSTIFICATION:
                self.next_justification_speaker()
            elif self.phase == PHASE_REVOTE:
                self.finish_revote()
            elif self.phase == PHASE_VOTE_RESULTS:
                self.confirm_elimination()
            elif self.phase == PHASE_LAST_WORD:
                self.finish_last_word()
            return True

        return False

    def get_state(self, for_player_id: Optional[str] = None) -> dict:
        is_host = (for_player_id == self.host_id)
        current_speaker = self.get_current_speaker()

        players_data = [
            p.to_dict(show_all_secret=(self.phase == PHASE_FINAL), for_player_id=for_player_id)
            for p in self.players.values()
        ]

        alive_players = self.get_alive_players()
        alive_count = len(alive_players)

        revealed_now = len(self.turn_revealed_categories)
        req_reveals = self.get_round_reveal_quota(current_speaker) if current_speaker else 1
        is_current_speaker = (current_speaker.id == for_player_id) if current_speaker else False
        quota_reached = (revealed_now >= req_reveals) if current_speaker else False

        current_debate_speaker = self.get_current_debate_speaker() if self.phase in (PHASE_DEBATE, PHASE_ACCUSATION) else None
        curr_acc = self.get_current_accusation_speaker() if self.phase == PHASE_ACCUSATION else None
        curr_just = self.get_current_justification_speaker() if self.phase == PHASE_JUSTIFICATION else None
        for_player = self.players.get(for_player_id) if for_player_id else None

        # Проверяем вендетту: может ли текущий изгнанник отомстить
        can_trigger_vendetta = False
        if not self.exile_vendetta_used and for_player and not for_player.is_alive and self.phase not in (PHASE_LOBBY, PHASE_FINAL):
            alive_surf, _ = is_exile_alive_on_surface(for_player.cards, self.catastrophe)
            can_trigger_vendetta = alive_surf

        return {
            "room_code": self.room_code,
            "phase": self.phase,
            "game_mode": self.game_mode,
            "round_number": self.round_number,
            "round_direction": "reverse" if (self.round_number % 2 == 0) else "forward",
            "is_reverse_round": (self.round_number % 2 == 0),
            "bunker_capacity": self.bunker_capacity,
            "alive_count": alive_count,
            "total_players": len(self.players),
            "is_host": is_host,
            "is_registered": (for_player_id in self.players),
            "can_claim_host": (self.phase == PHASE_LOBBY or (self.host_id not in self.players or not self.players[self.host_id].connected)),
            "enable_traitor": self.enable_traitor,
            "catastrophe": self.catastrophe,
            "bunker": self.bunker,
            "timers_config": {
                "speech": self.speech_duration_sec,
                "discussion": self.discussion_duration_sec,
                "accusation": self.accusation_duration_sec,
                "debate": self.debate_duration_sec,
                "voting": self.voting_duration_sec,
                "justification": self.justification_duration_sec,
                "revote": self.revote_duration_sec,
                "last_word": self.last_word_duration_sec
            },
            "timer": {
                "seconds_left": self.timer_seconds_left,
                "is_paused": self.timer_is_paused
            },
            "last_word": {
                "active": (self.phase == PHASE_LAST_WORD),
                "speaker_id": self.eliminated_in_last_word_id,
                "speaker_name": self.players[self.eliminated_in_last_word_id].name if (self.eliminated_in_last_word_id and self.eliminated_in_last_word_id in self.players) else None,
                "is_me": (self.eliminated_in_last_word_id == for_player_id) if self.eliminated_in_last_word_id else False
            } if self.phase == PHASE_LAST_WORD else None,
            "exile_vendetta": {
                "used": self.exile_vendetta_used,
                "can_trigger": can_trigger_vendetta
            },
            "current_speaker": {
                "id": current_speaker.id if current_speaker else None,
                "name": current_speaker.name if current_speaker else None,
                "index": self.active_speaker_idx,
                "total": len(self.speakers_order),
                "is_silenced": current_speaker.is_silenced if current_speaker else False
            } if current_speaker else None,
            "discussion_status": {
                "phase": self.phase,
                "collective_discussion": (self.phase == PHASE_COLLECTIVE_DISCUSSION),
                "accusation": (self.phase == PHASE_ACCUSATION)
            },
            "accusation_speaker": {
                "id": curr_acc.id if curr_acc else None,
                "name": curr_acc.name if curr_acc else None,
                "index": self.active_accusation_speaker_idx,
                "total": len(self.accusation_speakers_order),
                "is_current": (curr_acc.id == for_player_id) if curr_acc else False,
                "is_silenced": curr_acc.is_silenced if curr_acc else False
            } if curr_acc else None,
            "debate_speaker": {
                "id": current_debate_speaker.id if current_debate_speaker else None,
                "name": current_debate_speaker.name if current_debate_speaker else None,
                "index": self.active_debate_speaker_idx,
                "total": len(self.debate_speakers_order),
                "is_current": (current_debate_speaker.id == for_player_id) if current_debate_speaker else False,
                "is_silenced": current_debate_speaker.is_silenced if current_debate_speaker else False
            } if self.phase in (PHASE_DEBATE, PHASE_ACCUSATION) and current_debate_speaker else None,
            "debate_order": [
                {"id": pid, "name": self.players[pid].name if pid in self.players else "Игрок"}
                for pid in self.debate_speakers_order
            ] if self.phase in (PHASE_DEBATE, PHASE_ACCUSATION) else [],
            "justification_status": {
                "active": (self.phase == PHASE_JUSTIFICATION),
                "candidates": self.justification_candidates,
                "speaker_id": curr_just.id if curr_just else None,
                "speaker_name": curr_just.name if curr_just else None,
                "is_current": (curr_just.id == for_player_id) if curr_just else False,
                "index": self.active_justification_speaker_idx,
                "total": len(self.justification_speakers_order)
            },
            "revote_status": {
                "active": (self.phase == PHASE_REVOTE),
                "candidates": self.justification_candidates
            },
            "reveal_quota": {
                "required": req_reveals,
                "opened": revealed_now,
                "profession_required": (self.round_number == 1)
            },
            "speech_status": {
                "required_count": req_reveals,
                "revealed_count": revealed_now,
                "can_proceed": self.can_speaker_proceed(),
                "is_current_speaker": is_current_speaker,
                "current_speaker_id": current_speaker.id if current_speaker else None,
                "current_speaker_name": current_speaker.name if current_speaker else None,
                "quota_reached": quota_reached,
                "is_silenced": current_speaker.is_silenced if current_speaker else False
            },
            "speaker_status": {
                "required_count": req_reveals,
                "revealed_count": revealed_now,
                "can_proceed": self.can_speaker_proceed(),
                "is_current_speaker": is_current_speaker,
                "current_speaker_id": current_speaker.id if current_speaker else None,
                "current_speaker_name": current_speaker.name if current_speaker else None,
                "quota_reached": quota_reached,
                "is_silenced": current_speaker.is_silenced if current_speaker else False
            },
            "voting_status": {
                "total_voters": alive_count,
                "votes_cast": len(self.votes),
                "all_voted": len(self.votes) >= alive_count
            },
            "skip_round_info": {
                "can_skip": (self.phase == PHASE_VOTING and self.round_number == 1),
                "skip_votes": len(self.skip_round_votes),
                "needed": (alive_count // 2) + 1,
                "double_elimination_pending": self.double_elimination_pending
            },
            "vote_results": self.vote_results,
            "final_evaluation": self.final_evaluation,
            "players": players_data,
            "events_enabled": self.events_enabled,
            "events_state": {
                "enabled": self.events_enabled,
                "active_event": self.active_event,
                "current_odds": self.current_event_odds,
                "volunteer_id": self.assigned_volunteer_id,
                "assigned_volunteer_id": self.assigned_volunteer_id,
                "last_resolved": self.last_resolved_event,
                "resolved_history": self.resolved_events[-10:],
                "events_score_delta": self.events_score_delta,
                "score_delta": self.events_score_delta,
                "boosted_profession_tags": self.boosted_profession_tags
            },
            "game_log": self.game_log[-16:]
        }


# Alias for backward compatibility
GameRoom = BunkerGameRoom

