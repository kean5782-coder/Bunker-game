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
import copy
from .lobby import LobbyMixin
from .results import ResultReviewMixin
from .presentation import public_state
from .balance import CONFIG as BALANCE_CONFIG, normalized_event_score, has_hazard_protection, mechanics_text, VERSION as BALANCE_VERSION
from .special_cards import special_availability, use_special_card as apply_special_card
from .speech_effects import speech_transition, public_effects, send_prompt
from typing import Dict, List, Optional, Any
from .deck_data import (
    generate_game_deck, 
    evaluate_survival, 
    PROFESSIONS, 
    HEALTH_CONDITIONS,
    draw_random_event,
    calculate_event_odds,
    resolve_event_roll,
    is_exile_alive_on_surface,
    get_hazard_health_condition
)

logger = logging.getLogger("bunker.engine")

# Доступные фазы игры
PHASE_LOBBY = "LOBBY"
PHASE_PROLOGUE = "PROLOGUE"                             # Ознакомление с катастрофой перед закрытием шлюза
PHASE_REVEAL = "REVEAL"                                 # Поочерёдное раскрытие карт, 60 сек каждому
PHASE_SPEECH = "SPEECH"                                 # Первый круг индивидуальных речей без обычного раскрытия
PHASE_COLLECTIVE_DISCUSSION = "COLLECTIVE_DISCUSSION"   # Устаревшая фаза: сохранена только для совместимости старых клиентов
PHASE_ACCUSATION = "ACCUSATION"                         # Второй круг индивидуальных речей по 30 сек
PHASE_DEBATE = PHASE_ACCUSATION                         # Алиас совместимости: старые «дебаты» теперь ведут во 2-й круг речей
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
        self.is_speech_silenced = False
        self.is_quarantined = False
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
            "is_speech_silenced": self.is_speech_silenced,
            "is_quarantined": self.is_quarantined,
            "connected": self.connected,
            "last_peeked": self.last_peeked if is_self else None
        }


class BunkerGameRoom(ResultReviewMixin, LobbyMixin):
    def __init__(self, room_code: str, host_id: str, host_name: str):
        self.room_code = room_code.upper()
        self.host_id = host_id
        self.host_token = str(uuid.uuid4())[:8]
        self.phase = PHASE_LOBBY
        self.round_number = 1
        self.players: Dict[str, Player] = {}
        self.speech_effects: dict = {}
        self.catastrophe: Optional[dict] = None
        self.bunker: Optional[dict] = None
        
        # Настройки игры и режима
        self.game_mode = "STANDARD"          # STANDARD | METEORITE
        self.reveal_duration_sec = 60        # Отдельный фиксированный таймер, независимо от пресета
        self.speech_duration_sec = 60
        self.discussion_duration_sec = 0     # Общие дебаты отключены
        self.accusation_duration_sec = 30    # Второй круг индивидуальных речей — вдвое короче первого
        self.debate_duration_sec = 30        # Совместимость со старыми клиентами
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
        self.events_score_delta: float = 0
        self.forced_revote_round = None
        self.boosted_profession_tags: Dict[str, int] = {}
        self.last_resolved_event: Optional[dict] = None
        self.consecutive_event_failures: int = 0  # Для системы жалости (pity system)
        self.is_sortie_skipped: bool = False  # Пропуск вылазки ведущим
        self.event_special_bonus: int = 0
        self.volunteer_is_safe: bool = False
        self.sabotage_suppressed: bool = False

        # Механики изгнанных и спецкарт
        self.veto_used_round: Optional[int] = None
        self.exile_vendetta_used: bool = False
        self.eliminated_in_last_word_id: Optional[str] = None

        # Состояние таймера
        self.timer_seconds_left = 0
        self.timer_is_paused = False
        self.prologue_ready_players: set[str] = set()

        # Указатель на текущего говорящего игрока (фаза речи)
        self.active_speaker_idx = 0
        self.speakers_order: List[str] = []
        self.turn_revealed_categories: set[str] = set()
        self.round_revealed_categories: Dict[str, set[str]] = {}
        self.turn_id = 0  # Защита от запоздавших команд предыдущего хода

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

        self.init_result_reviews()
        self.init_lobby()

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

        if self.phase == PHASE_LOBBY and len(self.players) >= self.lobby_settings['max_players']:
            raise ValueError('Достигнут лимит участников комнаты.')
        player = Player(player_id, name, is_host=is_host)
        self.players[player_id] = player
        self.invalidate_lobby_ready()
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

    @speech_transition
    def remove_player(self, player_id: str):
        self.last_activity = time.time()
        if player_id in self.players:
            name = self.players[player_id].name
            del self.players[player_id]
            self.invalidate_lobby_ready()
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
        self.is_sortie_skipped = False
        self.event_special_bonus = 0
        self.volunteer_is_safe = False
        self.sabotage_suppressed = False

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
            f"{ev['description']} Обсудите условия и действия команды.",
            "warning"
        )

    def skip_sortie(self, skip: bool = True):
        """Пропуск вылазки на поверхность: шлюз запечатан, 0% бонусов/штрафов, без риска для здоровья"""
        if not self.active_event or self.active_event.get("type") != "SURFACE_EVENT":
            raise ValueError("Пропустить можно только вылазку на поверхность!")
        self.is_sortie_skipped = skip
        state_str = "ОТМЕНЕНА (гермошлюз запечатан) 🚫" if skip else "ВОЗОБНОВЛЕНА 🪂"
        self.log_event("Вылазка на поверхность", f"Решение бункера: вылазка {state_str}!", "warning" if skip else "info")

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
            pity_bonus=pity,
            special_bonus=self.event_special_bonus,
            sabotage_suppressed=self.sabotage_suppressed
        )

        difficulty = {'easy': 10, 'normal': 0, 'hard': -10}.get(self.event_difficulty, 0)
        if difficulty:
            odds = self.current_event_odds
            odds['unclamped_chance'] = odds.get('unclamped_chance', odds['final_chance']) + difficulty
            odds['final_chance'] = round(max(BALANCE_CONFIG['event_min'], min(BALANCE_CONFIG['event_max'], odds['unclamped_chance'])))
            odds['positive_factors' if difficulty > 0 else 'negative_factors'].append({
                'player_id': 'lobby', 'player_name': 'Параметры партии', 'category': 'difficulty',
                'title': 'Мягкие испытания' if difficulty > 0 else 'Суровые испытания',
                'delta': difficulty, 'card_value': 'Сложность испытаний',
            })

    def assign_volunteer(self, player_id: str):
        """Назначение добровольца из бункера на вылазку на поверхность"""
        p = self.players.get(player_id)
        if not p or not p.is_alive:
            raise ValueError("Добровольцем может быть только живой кандидат в бункере!")
        self.assigned_volunteer_id = player_id
        self.recalculate_event_odds()
        self.log_event("Назначен доброволец", f"{p.name} вызвался совершить вылазку на поверхность!", "primary")

    def resolve_active_event(self, force_roll: Optional[int] = None, *, guaranteed_success: bool = False) -> dict:
        """Хост или таймер бросает кубик d100 и разрешает активное событие"""
        if not self.active_event or not self.current_event_odds:
            raise ValueError("Нет активного события для разрешения!")

        self.recalculate_event_odds()
        review_event = copy.deepcopy(self.active_event)
        rating_before = self.events_score_delta
        review_volunteer = (self.current_event_odds.get("volunteer") or {}).get("id") or self.assigned_volunteer_id
        # 1. Проверка пропуска вылазки на поверхность
        if self.active_event.get("type") == "SURFACE_EVENT" and self.is_sortie_skipped:
            ev = self.active_event
            result = {
                "event_id": ev["id"],
                "event_title": ev["title"],
                "title": f"🚫 Вылазка пропущена: {ev['title']}",
                "is_success": True,
                "is_skipped": True,
                "roll": 0,
                "chance_required": 0,
                "is_crit_success": False,
                "is_crit_failure": False,
                "score_delta": 0,
                "description": "Бункер запечатал гермошлюз. Никто не вышел наружу: выжившие в безопасности, припасы не добыты (нулевой вклад в рейтинг бункера, риск здоровью исключен).",
                "boosted_tags": [],
                "boost_score": 0,
                "boost_reason": "",
                "health_degraded": None,
                "resolved_at": time.time()
            }
            self.last_resolved_event = result
            self.resolved_events.append({
                "timestamp": time.strftime("%H:%M:%S"),
                "round": self.round_number,
                "event": self.active_event,
                "result": result
            })
            self.log_event(
                "🚫 ВЫЛАЗКА ОТМЕНЕНА",
                f"Бункер остался запечатанным. Событие «{ev['title']}» пропущено (нулевой вклад, здоровье добровольца в безопасности).",
                "info"
            )
            self.active_event = None
            self.current_event_odds = None
            self.is_sortie_skipped = False
            self.present_event_result(result, review_event, rating_before, review_volunteer)
            return result

        # 2. Обычный бросок кубика d100
        result = resolve_event_roll(self.active_event, self.current_event_odds, force_roll=force_roll, guaranteed_success=guaranteed_success)

        if result["is_success"]:
            self.consecutive_event_failures = 0
        else:
            self.consecutive_event_failures += 1

        # Если провал — активируем буст профессий
        if not result["is_success"] and result["boosted_tags"]:
            boost_val = result.get("boost_score", 10)
            for tag in result["boosted_tags"]:
                self.boosted_profession_tags[tag] = max(self.boosted_profession_tags.get(tag, 0), boost_val)

        # 3. Механика риска ухудшения здоровья добровольца при вылазке на поверхность
        result["health_degraded"] = None
        if self.active_event.get("type") == "SURFACE_EVENT":
            vol_id = (self.current_event_odds.get("volunteer") or {}).get("id") or self.assigned_volunteer_id
            vol = self.players.get(vol_id) if vol_id else None
            if not vol or not vol.is_alive:
                alive = self.get_alive_players()
                vol = alive[0] if alive else None

            if vol and "health" in vol.cards:
                if self.volunteer_is_safe:
                    danger_chance = 0
                else:
                    danger_chance = 35  # Базовая опасность

                    # Опасность катаклизма
                    cat_id = self.catastrophe.get("id", "") if self.catastrophe else ""
                    cat_title = self.catastrophe.get("title", "") if self.catastrophe else "Катаклизм"
                    cat_text = ((self.catastrophe.get("title", "") if self.catastrophe else "") + " " + 
                                (self.catastrophe.get("description", "") if self.catastrophe else "")).lower()

                    extreme_cats = ["ice_age", "acid_rains", "nanite_swarm", "atmospheric_fire", "global_flood",
                                    "cosmic_radiation", "nuclear_winter", "super_virus", "toxic_bloom", "zombie_outbreak"]
                    if cat_id in extreme_cats or any(w in cat_text for w in ["радиаци", "вирус", "мороз", "кислот", "яд", "токсин", "инфекци", "мутаци", "пыль"]):
                        danger_chance += 15

                    # Исход вылазки
                    if not result["is_success"]:
                        danger_chance += 25
                        if result.get("is_crit_failure"):
                            danger_chance += 15
                    else:
                        danger_chance -= 15
                        if result.get("is_crit_success"):
                            danger_chance = 0  # При критическом успехе доброволец возвращается невредимым

                    # Actual explicit protection, not an incidental word in a description.
                    has_prot = has_hazard_protection(vol.cards, self.catastrophe)
                    if has_prot:
                        danger_chance -= 25

                    # Корректировка на здоровый организм
                    curr_sev = vol.cards["health"].get("severity", "good")
                    if curr_sev == "good":
                        danger_chance -= 10

                    danger_chance = 0 if result.get("is_crit_success") else max(5, min(85, danger_chance))

                # Бросок d100 на здоровье
                health_roll = random.randint(1, 100)
                if danger_chance > 0 and health_roll <= danger_chance:
                    old_name = vol.cards["health"].get("value", "Здоров")
                    old_desc = vol.cards["health"].get("details", "")

                    if curr_sev == "good":
                        # Если полностью здоров: убирается «Абсолютно здоров», появляется легкая стадия болезни
                        new_cond = get_hazard_health_condition(cat_id, cat_text)
                        new_name = new_cond["name"]
                        new_desc = f"{new_cond['desc']} (Получено при вылазке на поверхность при катастрофе «{cat_title}»)."
                        new_sev = new_cond.get("severity", "minor")
                    elif curr_sev == "minor":
                        # Обострение легкой стадии до средней
                        new_name = f"{old_name} (Обострение средней тяжести)"
                        new_desc = f"{old_desc} После воздействия среды на поверхности болезнь обострилась до средней тяжести."
                        new_sev = "medium"
                    elif curr_sev == "medium":
                        # Обострение средней стадии до критической
                        new_name = f"{old_name} (Критическое осложнение)"
                        new_desc = f"{old_desc} Катастрофическое обострение после вылазки: требуется постоянная медпомощь, критическое состояние!"
                        new_sev = "critical"
                    else:
                        # Критическая стадия обостряется до терминальной
                        new_name = f"{old_name} (Терминальная стадия)"
                        new_desc = f"{old_desc} Организм получил смертельную дозу поражения снаружи: состояние на грани гибели!"
                        new_sev = "critical"

                    if curr_sev != "good" and "health_before_treatment" in vol.cards["health"]:
                        # A new setback must not keep saying "recovering".
                        new_name = "Ухудшение здоровья после вылазки"
                        new_desc = ("После вылазки самочувствие ухудшилось. " +
                                    ("Состояние средней тяжести: нужны лечение и отдых."
                                     if new_sev == "medium" else
                                     "Состояние критическое: нужна срочная помощь."))

                    vol.cards["health"]["value"] = new_name
                    vol.cards["health"]["details"] = new_desc
                    vol.cards["health"]["severity"] = new_sev
                    vol.cards["health"]["mechanics"] = {}
                    vol.cards["health"]["mechanics_text"] = mechanics_text(vol.cards["health"], "health")
                    # Здоровье ухудшается втихую: карта НЕ раскрывается автоматически (статус revealed не меняется)!

                    result["health_degraded"] = {
                        "player_id": vol.id,
                        "player_name": vol.name,
                        "old_condition": old_name,
                        "new_condition": new_name,
                        "severity": new_sev,
                        "danger_chance": danger_chance,
                        "roll": health_roll
                    }

        result["resolved_at"] = time.time()
        self.last_resolved_event = result
        self.resolved_events.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "round": self.round_number,
            "event": self.active_event,
            "result": result
        })

        self.refresh_event_score()

        if result["is_success"]:
            crit_mark = " ⭐ КРИТИЧЕСКИЙ УСПЕХ!" if result.get("is_crit_success") else ""
            self.log_event(
                f"✅ {result['title']}{crit_mark}",
                f"{'Гарантированный обычный успех. ' if result.get('guaranteed_success') else ''}{result['description']}",
                "success"
            )
        else:
            boost_msg = f" {result.get('boost_reason', '')}" if result.get("boost_reason") else ""
            crit_mark = " 💥 КРИТИЧЕСКИЙ ПРОВАЛ!" if result.get("is_crit_failure") else ""
            pity_msg = " Активирован бонус сплоченности (+15% к следующему испытанию)!" if self.consecutive_event_failures >= 2 else ""
            self.log_event(
                f"❌ {result['title']}{crit_mark}",
                result['description'],
                "danger"
            )

        # Очищаем активное событие (оно разрешено)
        self.active_event = None
        self.current_event_odds = None
        self.is_sortie_skipped = False
        self.present_event_result(result, review_event, rating_before, review_volunteer)
        return result

    def refresh_event_score(self):
        manual = (self.bunker or {}).get("vendetta_delta", 0)
        self.events_score_delta = max(-12, min(12, normalized_event_score(self.resolved_events) + manual))

    def host_toggle_events(self, enabled: bool):
        self.last_activity = time.time()
        self.events_enabled = enabled
        if not enabled:
            self.active_event = None
            self.current_event_odds = None
        elif self.phase not in (PHASE_LOBBY, PHASE_FINAL) and not self.active_event:
            self.trigger_next_event()
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
        last_word_duration: Optional[int] = None,
        skip_prologue: bool = True,
        lobby_options: Optional[dict] = None
    ):
        """Запуск игры: раздача карт, определение катастрофы, режима и бункера"""
        alive = self.get_alive_players()
        if len(alive) < 3:
            raise ValueError("Для начала игры необходимо минимум 3 игрока!")

        if capacity is not None and (type(capacity) is not int or not 1 <= capacity < len(alive)):
            raise ValueError('Мест должно быть от 1 до числа участников минус один.')
        options = lobby_options or {}
        mode = options.get('information_mode', self.lobby_settings.get('information_mode', 'immersion'))
        if mode not in ('immersion', 'uncertainty'):
            raise ValueError('Недопустимый режим информации.')
        deal_mode = options.get('deal_mode', self.lobby_settings.get('deal_mode', 'full_random'))
        if deal_mode not in ('full_random', 'balanced'):
            raise ValueError('Недопустимый режим раздачи.')
        self.match_settings = {**copy.deepcopy(self.lobby_settings), **copy.deepcopy(options),
                               'information_mode': mode, 'deal_mode': deal_mode}
        self.event_difficulty = options.get('event_difficulty', 'normal')
        self.speaker_order_mode = options.get('speaker_order', 'join')
        self.match_seating = [p.id for p in alive]
        if self.speaker_order_mode == 'random':
            random.shuffle(self.match_seating)
        self.justification_duration_sec = options.get('justification_duration', self.justification_duration_sec)
        self.revote_duration_sec = options.get('revote_duration', self.revote_duration_sec)
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
            self.speech_duration_sec = s_time or 30
            self.accusation_duration_sec = max(15, self.speech_duration_sec // 2)
            self.debate_duration_sec = self.accusation_duration_sec
            self.discussion_duration_sec = 0
            self.voting_duration_sec = v_time or 30
            # В режиме «Метеорит» мест крайне мало: 2 места на 5-6 игроков, 1 на 3-4
            if capacity:
                self.bunker_capacity = capacity
            else:
                self.bunker_capacity = 2 if len(alive) >= 5 else 1
        else:
            self.speech_duration_sec = s_time or 60
            self.accusation_duration_sec = max(15, self.speech_duration_sec // 2)
            self.debate_duration_sec = self.accusation_duration_sec
            self.discussion_duration_sec = 0
            self.voting_duration_sec = v_time or 60
            if capacity:
                self.bunker_capacity = capacity
            else:
                # Оптимально для групп из 6 человек: 3 места (50% выживаемость)
                self.bunker_capacity = max(1, len(alive) // 2)

        deck = generate_game_deck(len(alive), self.bunker_capacity, enable_traitor=self.enable_traitor,
                                  enable_events=self.events_enabled,
                                  catastrophe_id=options.get('catastrophe_id', 'random'),
                                  bunker_id=options.get('bunker_id', 'random'), deal_mode=deal_mode)
        self.catastrophe = deck["catastrophe"]
        self.bunker = deck["bunker"]

        # Раздаем карты игрокам
        self.speech_effects.clear()
        for i, player in enumerate(alive):
            player.cards = deck["players_cards"][i]
            player.is_alive = True
            player.has_immunity = False
            player.double_vote = False
            player.is_silenced = False
            player.is_speech_silenced = False
            player.is_quarantined = False
            player.loot_stolen = False
            player.last_peeked = None

            if not options.get('enable_special_cards', True):
                player.cards.pop('special', None)
            reveal = options.get('initial_reveal', 'mode')
            if reveal == 'mode':
                reveal = 'profession_health' if self.game_mode == 'METEORITE' else 'closed'
            for category in ({'profession': ['profession'], 'profession_health': ['profession', 'health']}.get(reveal, [])):
                if category in player.cards:
                    player.cards[category]['revealed'] = True

        self.init_result_reviews()
        self.resolved_events.clear()
        self.used_event_ids.clear()
        self.events_score_delta = 0
        self.boosted_profession_tags.clear()
        self.last_resolved_event = None
        self.active_event = None
        self.current_event_odds = None
        self.forced_revote_round = None
        self.double_elimination_pending = False
        self.round_number = 1
        self.prologue_ready_players.clear()

        if skip_prologue:
            self.start_round()
        else:
            self.phase = PHASE_PROLOGUE
            self.timer_seconds_left = self.speech_duration_sec
            self.timer_is_paused = True

        # Сразу вытягиваем испытание на 1-й раунд во всех режимах игры
        if self.events_enabled:
            self.trigger_next_event()

        traitor_msg = " [РЕЖИМ ПРЕДАТЕЛЯ АКТИВИРОВАН ☣️]" if self.enable_traitor else ""
        mode_msg = " ☄️ БЫСТРЫЙ РЕЖИМ «МЕТЕОРИТ»" if self.game_mode == "METEORITE" else ""
        self.log_event(
            f"АПОКАЛИПСИС: {self.catastrophe['title']}{mode_msg}{traitor_msg}",
            f"{self.catastrophe['description']} Мест в бункере: {self.bunker_capacity}.",
            "danger"
        )

    def enter_bunker(self, player_id: Optional[str] = None):
        """Игрок нажимает кнопку 'В бункер' в прологе."""
        if self.phase != PHASE_PROLOGUE:
            return
        if player_id:
            self.prologue_ready_players.add(player_id)

        is_host = (player_id == self.host_id or not player_id)
        alive_ids = {p.id for p in self.get_alive_players()}
        human_alive_ids = {pid for pid in alive_ids if not pid.startswith("bot_")}
        all_humans_ready = human_alive_ids.issubset(self.prologue_ready_players)

        if is_host or all_humans_ready:
            self.finish_prologue()

    def finish_prologue(self):
        """Завершение пролога и запуск отдельного круга раскрытия."""
        if self.phase != PHASE_PROLOGUE:
            return
        self.start_round()
        self.log_event(
            "ГЕРМОШЛЮЗ ЗАПЕРТ 🚪",
            "Выжившие вошли в бункер. Врата запечатаны. Сначала каждый по очереди раскрывает карты за 60 секунд, затем начинается первый круг речей!",
            "primary"
        )

    def start_round(self):
        """Начало нового раунда"""
        self.last_activity = time.time()
        alive = self.get_alive_players()

        # Блок 3 (Вариант 3Б): Чередование направления хода по раундам
        # Нечетные раунды (1, 3, 5) — прямой порядок (по часовой стрелке)
        # Четные раунды (2, 4, 6) — реверсивный порядок (обратный порядок)
        if self.round_number % 2 == 0:
            self.speakers_order = list(reversed(self.ordered_alive_ids()))
        else:
            self.speakers_order = self.ordered_alive_ids()

        # Сброс модификаторов на раунд
        for p in alive:
            p.has_immunity = False
            p.double_vote = False
            p.is_silenced = False
            p.is_speech_silenced = False
            p.is_quarantined = False
            p.loot_stolen = False
            p.vote_target = None

        self.votes.clear()
        self.skip_round_votes.clear()
        self.vote_results = None
        self.veto_used = False
        self.is_tiebreaker_active = False
        self.active_speaker_idx = 0
        self.round_revealed_categories.clear()
        self.turn_revealed_categories = set()
        self.event_special_bonus = 0
        self.volunteer_is_safe = False
        self.sabotage_suppressed = False

        self.start_reveal_phase()
        dir_name = "обратный (реверс раунда)" if self.round_number % 2 == 0 else "прямой"
        self.log_event(f"Раунд {self.round_number}", f"Порядок: {dir_name}. Раскрытие по 60 сек каждому → Речь 1 → Речь 2 → голосование.", "primary")

    def _skip_ineligible_turns(self, speech: bool = False):
        """Disconnected players keep their timed turn; eliminated/isolated players do not."""
        while self.active_speaker_idx < len(self.speakers_order):
            player = self.get_current_speaker()
            if (player and player.is_alive and not player.is_quarantined
                    and not (speech and player.is_speech_silenced)):
                break
            self.active_speaker_idx += 1

    def _begin_reveal_turn(self):
        self._skip_ineligible_turns()
        current = self.get_current_speaker()
        if current is None:
            self.start_speech_phase()
            return
        self.turn_revealed_categories = self.round_revealed_categories.setdefault(current.id, set())
        self.turn_id += 1
        self.timer_seconds_left = self.reveal_duration_sec
        self.timer_is_paused = False
        self.log_event("Открытие карточек", f"{current.name} раскрывает характеристики. На ход — {self.reveal_duration_sec} сек. Речи начнутся после всего круга.", "primary")

    @speech_transition
    def start_reveal_phase(self):
        """Start/revisit the reveal circle without resetting already opened quotas."""
        self.last_activity = time.time()
        self.phase = PHASE_REVEAL
        self.active_speaker_idx = 0
        self._begin_reveal_turn()

    def next_reveal_player(self, force: bool = False):
        """Finish this player's reveal turn, then advance; only the LAST starts Speech 1."""
        if self.phase != PHASE_REVEAL:
            raise ValueError("Этап открытия карточек сейчас не активен.")
        self.last_activity = time.time()
        current = self.get_current_speaker()
        if not self.can_speaker_proceed():
            required = self.get_round_reveal_quota(current)
            if not force:
                raise ValueError(f"Сначала откройте положенные карточки ({len(self.turn_revealed_categories)} из {required}).")
            # Same AFK policy as the old combined phase: profession first, then dossier order.
            if current:
                hidden = [k for k, c in current.cards.items()
                          if k not in ("traitor", "special") and not c.get("revealed", False)]
                if self.round_number == 1 and "profession" in hidden:
                    hidden.remove("profession")
                    hidden.insert(0, "profession")
                for category in hidden[:max(0, required - len(self.turn_revealed_categories))]:
                    card = current.cards[category]
                    card["revealed"] = True
                    self.turn_revealed_categories.add(category)
                    self.log_event("Авто-раскрытие", f"{current.name}: {card.get('label', category)} — {card.get('value')}. Время истекло или ведущий завершил ход.", "warning")
        if self.active_event:
            self.recalculate_event_odds()
        self.active_speaker_idx += 1
        self._begin_reveal_turn()

    @speech_transition
    def start_speech_phase(self):
        """A fresh full Speech 1 circle, with its own independent timer and no reveal quota."""
        self.last_activity = time.time()
        self.phase = PHASE_SPEECH
        self.active_speaker_idx = 0
        self.turn_revealed_categories = set()
        self._skip_ineligible_turns(speech=True)
        current = self.get_current_speaker()
        self.turn_id += 1
        if current is None:
            self.start_accusation_phase()
            return
        self.timer_seconds_left = self.speech_duration_sec
        self.timer_is_paused = False
        self.log_event("Первый круг речей", f"Слово держит: {current.name} ({self.speech_duration_sec} сек). Обычное раскрытие карточек завершено.", "primary")

    def validate_turn_command(self, expected_turn_id):
        """Optional for legacy clients; current clients attach this to reveal/advance actions."""
        if expected_turn_id is not None and (type(expected_turn_id) is not int or expected_turn_id != self.turn_id):
            raise ValueError("Ход уже изменился. Дождитесь обновления состояния игры.")

    def get_current_speaker(self) -> Optional[Player]:
        if 0 <= self.active_speaker_idx < len(self.speakers_order):
            speaker_id = self.speakers_order[self.active_speaker_idx]
            return self.players.get(speaker_id)
        return None

    def get_round_reveal_quota(self, player: Optional[Player] = None) -> int:
        """Динамическая норма вскрытия характеристик по числу игроков (Вариант 2Б)"""
        curr = player or self.get_current_speaker()
        if not curr or not curr.is_alive or curr.is_quarantined:
            return 0
        unrevealed = [k for k, v in curr.cards.items() if k not in ("traitor", "special") and not v.get("revealed", False)]
        opened = self.round_revealed_categories.get(curr.id, set())
        unrevealed_at_start = len(unrevealed) + len(opened)
        if unrevealed_at_start == 0:
            return 0
        total_p = len(self.players)
        return get_reveal_quota(total_p, self.round_number, unrevealed_at_start)

    def can_speaker_proceed(self) -> bool:
        """Норма действует только в отдельном круге раскрытия, не в речах."""
        if self.phase != PHASE_REVEAL:
            return True
        curr = self.get_current_speaker()
        if not curr or not curr.is_alive or curr.is_quarantined:
            return True

        # В 1-м раунде обязательна Профессия (если еще не открыта)
        if self.round_number == 1 and "profession" in curr.cards and not curr.cards["profession"].get("revealed", False):
            if "profession" not in self.turn_revealed_categories:
                return False

        required = self.get_round_reveal_quota(curr)
        return len(self.turn_revealed_categories) >= required

    @speech_transition
    def next_speaker(self, force: bool = False):
        """Advance Speech 1 without opening cards. Legacy reveal calls remain supported."""
        if self.phase == PHASE_REVEAL:
            return self.next_reveal_player(force=force)
        if self.phase != PHASE_SPEECH:
            raise ValueError("Первый круг речей сейчас не активен.")
        self.last_activity = time.time()
        self.active_speaker_idx += 1
        self._skip_ineligible_turns(speech=True)
        self.turn_id += 1
        current = self.get_current_speaker()
        if current is not None:
            self.timer_seconds_left = self.speech_duration_sec
            self.timer_is_paused = False
            self.log_event("Речь 1", f"Слово передано: {current.name} ({self.speech_duration_sec} сек).")
        else:
            self.start_accusation_phase()

    def start_collective_discussion(self):
        """Совместимость со старыми клиентами: общий микрофон отключён, сразу запускается 2-й круг речей."""
        self.start_accusation_phase()

    @speech_transition
    def start_accusation_phase(self):
        """Второй круг индивидуальных речей. Каждый живой игрок получает половину времени первого круга."""
        self.last_activity = time.time()
        self.phase = PHASE_ACCUSATION
        self.turn_id += 1
        alive = self.get_alive_players()
        if self.round_number % 2 == 0:
            self.accusation_speakers_order = list(reversed(self.ordered_alive_ids()))
        else:
            self.accusation_speakers_order = self.ordered_alive_ids()
        self.debate_speakers_order = list(self.accusation_speakers_order)
        self.active_accusation_speaker_idx = 0
        self.active_debate_speaker_idx = 0
        self.timer_seconds_left = self.accusation_duration_sec
        self.timer_is_paused = False

        # Пропускаем спикеров с обетом молчания
        while self.active_accusation_speaker_idx < len(self.accusation_speakers_order):
            sp = self.get_current_accusation_speaker()
            if not sp or not sp.is_alive or sp.is_silenced or sp.is_quarantined:
                self.log_event("Обет молчания", f"{sp.name if sp else 'Выбывший участник'} пропускает выступление (пропуск второго круга речей).", "warning")
                self.active_accusation_speaker_idx += 1
            else:
                break
        self.active_debate_speaker_idx = self.active_accusation_speaker_idx

        if self.active_accusation_speaker_idx < len(self.accusation_speakers_order):
            sp = self.get_current_accusation_speaker()
            sp_name = sp.name if sp else "Кандидат"
            self.log_event("Второй круг речей", f"Слово держит: {sp_name} ({self.accusation_duration_sec} сек).", "warning")
        else:
            self.log_event("Второй круг завершён", "Все игроки выступили повторно. Переход к тайному голосованию!", "warning")
            self.start_voting()

    def get_current_accusation_speaker(self) -> Optional[Player]:
        """Возвращает игрока, чья очередь выступать во втором круге речей"""
        if self.phase == PHASE_ACCUSATION and 0 <= self.active_accusation_speaker_idx < len(self.accusation_speakers_order):
            sid = self.accusation_speakers_order[self.active_accusation_speaker_idx]
            return self.players.get(sid)
        return None

    def get_current_debate_speaker(self) -> Optional[Player]:
        """Алиас для обратной совместимости"""
        return self.get_current_accusation_speaker()

    @speech_transition
    def next_accusation_speaker(self):
        """Переход к следующему оратору во втором круге речей или к голосованию"""
        self.last_activity = time.time()
        if self.phase != PHASE_ACCUSATION:
            return
        self.active_accusation_speaker_idx += 1
        self.turn_id += 1

        while self.active_accusation_speaker_idx < len(self.accusation_speakers_order):
            sp = self.get_current_accusation_speaker()
            if not sp or not sp.is_alive or sp.is_silenced or sp.is_quarantined:
                self.log_event("Обет молчания", f"{sp.name if sp else 'Выбывший участник'} пропускает выступление (пропуск).", "warning")
                self.active_accusation_speaker_idx += 1
            else:
                break
        self.active_debate_speaker_idx = self.active_accusation_speaker_idx

        if self.active_accusation_speaker_idx < len(self.accusation_speakers_order):
            self.timer_seconds_left = self.accusation_duration_sec
            self.timer_is_paused = False
            sp = self.get_current_accusation_speaker()
            sp_name = sp.name if sp else "Кандидат"
            self.log_event("Второй круг речей", f"Слово передано: {sp_name} ({self.accusation_duration_sec} сек).", "info")
        else:
            self.log_event("Второй круг завершён", "Все игроки выступили повторно. Переход к тайному голосованию!", "danger")
            self.start_voting()

    def next_debate_speaker(self):
        """Алиас для обратной совместимости"""
        self.next_accusation_speaker()

    def start_debate(self):
        """Алиас для обратной совместимости: запускает второй круг индивидуальных речей."""
        self.start_accusation_phase()

    @speech_transition
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
        self.log_event("Ведущий передал слово", f"Ведущий предоставил слово во втором круге: {target.name} ({self.accusation_duration_sec} сек).", "primary")
        self.turn_id += 1

    @speech_transition
    def host_grant_speech_speaker(self, player_id: str):
        """Ведущий принудительно дает слово конкретному живому игроку во время фазы речи"""
        self.last_activity = time.time()
        if self.phase != PHASE_SPEECH:
            raise ValueError("Фаза защитной речи сейчас не активна!")
        target = self.players.get(player_id)
        if not target or not target.is_alive:
            raise ValueError("Игрок не найден или выбыл!")

        if target.is_quarantined or target.is_speech_silenced:
            raise ValueError("Игрок не может выступать до конца раунда.")

        if player_id in self.speakers_order:
            self.active_speaker_idx = self.speakers_order.index(player_id)
        else:
            self.speakers_order.append(player_id)
            self.active_speaker_idx = len(self.speakers_order) - 1

        self.turn_id += 1
        self.timer_seconds_left = self.speech_duration_sec
        self.timer_is_paused = False
        self.turn_revealed_categories = set()
        self.log_event("Ведущий передал слово", f"Ведущий предоставил слово для речи: {target.name} ({self.speech_duration_sec} сек).", "primary")

    @speech_transition
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
        from .voting import cast_vote
        return cast_vote(self, voter_id, target_id)

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
            "eliminated_ids": [],
            "top_candidates": [],
            "detailed_tally": self.current_ballot_tally(),
            "veto_possible": False
        }
        self.timer_seconds_left = 0
        self.timer_is_paused = False
        self.present_vote_summary(self.vote_results, after="confirm_no_exile")
        self.log_event(
            "ИЗГНАНИЕ ПРОПУЩЕНО!",
            "Большинство выживших проголосовало за пропуск изгнания в 1-м раунде! Все остаются в бункере, но во 2-м раунде произойдет ДВОЙНОЕ изгнание!",
            "warning"
        )

    def finish_voting(self):
        from .voting import finish_voting
        return finish_voting(self)

    @speech_transition
    def start_justification(self, candidates: List[str], is_tie: bool, detailed_tally: list, max_percent: float):
        """Фаза оправдательной речи (30 сек кандидатам) (Вариант 5Б)"""
        self.last_activity = time.time()
        self.phase = PHASE_JUSTIFICATION
        self.turn_id += 1
        self.justification_candidates = list(candidates)
        self.justification_speakers_order = list(candidates)
        self.active_justification_speaker_idx = 0
        self.timer_seconds_left = self.justification_duration_sec
        self.timer_is_paused = False

        c_names = ", ".join([self.players[cid].name for cid in candidates if cid in self.players])
        if is_tie:
            reason = f"Ничья ({c_names})"
        else:
            reason = f"Кандидату ({c_names}) не хватило голосов для решения без защиты"

        curr_sp = self.get_current_justification_speaker()
        curr_name = curr_sp.name if curr_sp else "Кандидат"
        self.log_event(
            f"Оправдательная речь ({self.justification_duration_sec} сек)!",
            f"{reason}. Слово для защиты держит: {curr_name}.",
            "warning"
        )

    def get_current_justification_speaker(self) -> Optional[Player]:
        if self.phase == PHASE_JUSTIFICATION and 0 <= self.active_justification_speaker_idx < len(self.justification_speakers_order):
            sid = self.justification_speakers_order[self.active_justification_speaker_idx]
            return self.players.get(sid)
        return None

    @speech_transition
    def next_justification_speaker(self):
        """Переход к следующему спикеру на оправдании или к переголосованию"""
        self.last_activity = time.time()
        if self.phase != PHASE_JUSTIFICATION:
            return
        self.active_justification_speaker_idx += 1
        self.turn_id += 1
        if self.active_justification_speaker_idx < len(self.justification_speakers_order):
            self.timer_seconds_left = self.justification_duration_sec
            self.timer_is_paused = False
            sp = self.get_current_justification_speaker()
            sp_name = sp.name if sp else "Кандидат"
            self.log_event("Слово для оправдания", f"Слово передано: {sp_name} ({self.justification_duration_sec} сек).", "warning")
        else:
            self.start_revote()

    @speech_transition
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
            f"ПЕРЕГОЛОСОВАНИЕ ({self.revote_duration_sec} сек)!",
            f"Голосуйте строго между кандидатами: {c_names}. Побеждает простое большинство!",
            "danger"
        )

    def finish_revote(self):
        from .voting import finish_revote
        return finish_revote(self)

    def host_start_tiebreaker(self):
        """Запуск тайбрейка ведущим при необходимости"""
        if self.vote_results and self.vote_results.get("top_candidates"):
            self.start_justification(self.vote_results["top_candidates"], is_tie=True, detailed_tally=self.vote_results.get("detailed_tally", []), max_percent=50.0)

    @speech_transition
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

        if self.veto_used or (self.vote_results or {}).get("veto_used"):
            targets = []
        targets = [pid for pid in dict.fromkeys(targets) if pid in self.players and self.players[pid].is_alive and not self.players[pid].has_immunity]
        targets = targets[:max(0, len(self.get_alive_players()) - self.bunker_capacity)]
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

                # Transfer actual ownership once; neither duplicate the item
                # nor let it count as exile weapon after it was confiscated.
                for other in self.players.values():
                    if other.is_alive and other.loot_stolen and other.id not in targets:
                        source = next((k for k in ("backpack", "big_inventory", "baggage") if k in p.cards and not p.cards[k].get("destroyed")), None)
                        if source:
                            loot = p.cards.pop(source)
                            loot["source_category"] = source
                            loot["category"] = "stolen_baggage"
                            loot["label"] = "Трофей"
                            loot["revealed"] = True
                            other.cards["stolen_baggage"] = loot
                            other.loot_stolen = False
                            self.log_event("Мародерство", f"{other.name} забрал снаряжение изгнанного: {loot.get('value', '')}.", "warning")
                        break

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
                    self.log_event(
                        "ИСПЫТАНИЕ ПОСЛЕ ИЗГНАНИЯ 🎲",
                        f"Изгнание совершено! Оставшиеся в убежище столкнулись с кризисом «{ev_title}».",
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
                    self.log_event(
                        "ИСПЫТАНИЕ РАУНДА 🎲",
                        f"Никто не изгнан. Кризис «{ev_title}» разрешается текущим составом выживших.",
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
        if self.events_enabled and self.active_event:
            self.resolve_active_event()
        alive = self.get_alive_players()
        if len(alive) <= self.bunker_capacity:
            self.trigger_final()
        else:
            self.round_number += 1
            if self.events_enabled:
                self.trigger_next_event()
            self.start_round()

    @speech_transition
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
            f"В бункере остались {len(alive)} человек. {self.final_evaluation['title']}.",
            "primary"
        )

    # --- Управление картами игроков ---

    def reveal_player_card(self, player_id: str, category: str):
        """Обычная карточка открывается только в свой ход этапа REVEAL."""
        self.last_activity = time.time()
        player = self.players.get(player_id)
        if not player or not player.is_alive:
            raise ValueError("Игрок не найден или выбыл из игры!")

        if player.is_quarantined:
            raise ValueError("В изоляторе нельзя раскрывать карты до конца раунда.")
        # Речи используют уже открытые данные; обычное раскрытие — отдельная фаза.
        if self.phase != PHASE_REVEAL:
            raise ValueError("Карточки открываются только в отдельном этапе открытия, не во время речи.")

        # Лимит вскрытий относится только к текущему оратору.
        if self.phase == PHASE_REVEAL:
            curr = self.get_current_speaker()
            if not curr or curr.id != player_id:
                speaker_name = curr.name if curr else "другой кандидат"
                raise ValueError(f"Сейчас не ваш ход открытия! Карточки открывает: {speaker_name}.")

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

    def use_special_card(self, player_id: str, target_player_id: Optional[str] = None,
                         category: Optional[str] = None, categories: Optional[list] = None,
                         option_text: Optional[str] = None):
        return apply_special_card(self, player_id, target_player_id, category, categories, option_text)

    def send_speech_prompt(self, player_id, target_id, effect_id, index, word):
        return send_prompt(self, player_id, target_id, effect_id, index, word)

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
        surface = is_exile_alive_on_surface(player, self.catastrophe)
        alive_surface, reason = surface["is_alive_surface"], surface["reason"]
        if not alive_surface:
            raise ValueError(f"Вы не выжили на поверхности ({reason}) и не можете отомстить бункеру!")
        
        self.exile_vendetta_used = True
        if self.bunker is not None:
            self.bunker["vendetta_delta"] = -5
        self.refresh_event_score()
        self.log_event(
            "ВЕНДЕТТА ИЗГНАННЫХ! ⚡☠️",
            f"Выживший на поверхности {player.name} ({reason}) совершил диверсию против бункера снаружи! Последствия диверсии осложнят жизнь оставшихся в убежище.",
            "danger"
        )

    # --- ПРАВА ВЕДУЩЕГО (HOST CONTROLS) ---

    def host_pause_timer(self, is_paused: Optional[bool] = None):
        self.last_activity = time.time()
        if self.result_reviews:
            review = self.result_reviews[0]
            review['is_paused'] = not review['is_paused'] if is_paused is None else bool(is_paused)
            return
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
        if self.phase == PHASE_PROLOGUE:
            self.finish_prologue()
        elif self.phase == PHASE_REVEAL:
            self.timer_seconds_left = self.reveal_duration_sec
            self.timer_is_paused = False
            self.log_event("Перезапуск открытия", "На текущий ход вновь выделено 60 секунд. Норма и уже открытые карточки сохранены.")
        elif self.phase == PHASE_SPEECH:
            self.timer_seconds_left = self.speech_duration_sec
            self.timer_is_paused = False
            self.log_event("Перезапуск речи", "Ведущий перезапустил время защитной речи.")
        elif self.phase == PHASE_DEBATE:
            self.timer_seconds_left = self.debate_duration_sec
            self.timer_is_paused = False
            sp = self.get_current_debate_speaker()
            self.log_event("Перезапуск второй речи", f"Ведущий перезапустил время для спикера {sp.name if sp else ''} ({self.accusation_duration_sec} сек).", "info")
        elif self.phase == PHASE_VOTING:
            self.start_voting()
            self.log_event("Переголосование", "Ведущий объявил повторное голосование!", "warning")

    @speech_transition
    def host_set_phase(self, new_phase: str):
        self.last_activity = time.time()
        if new_phase == PHASE_PROLOGUE:
            self.phase = PHASE_PROLOGUE
            self.timer_seconds_left = self.speech_duration_sec
            self.timer_is_paused = True
        elif new_phase == PHASE_REVEAL:
            self.start_reveal_phase()
        elif new_phase == PHASE_SPEECH:
            self.start_speech_phase()
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
        if self.tick_result_review():
            return True
        if self.timer_is_paused or self.timer_seconds_left <= 0 or self.phase in (PHASE_PROLOGUE, PHASE_LOBBY, PHASE_FINAL):
            return False

        self.timer_seconds_left -= 1

        if self.timer_seconds_left <= 0:
            if self.phase == PHASE_REVEAL:
                self.next_reveal_player(force=True)
            elif self.phase == PHASE_SPEECH:
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

        for data in players_data:
            if data["id"] == for_player_id and "special" in data["cards"]:
                data["cards"]["special"] = {**data["cards"]["special"], **special_availability(self, for_player_id)}
        alive_players = self.get_alive_players()
        alive_count = len(alive_players)
        voters = [p for p in alive_players if not p.is_quarantined]
        total_vote_weight = sum(2 if p.double_vote else 1 for p in voters)
        skip_vote_weight = sum(2 if p.double_vote else 1 for p in voters if self.votes.get(p.id) == "SKIP_ROUND")

        in_reveal = self.phase == PHASE_REVEAL
        revealed_now = len(self.turn_revealed_categories) if in_reveal else 0
        req_reveals = self.get_round_reveal_quota(current_speaker) if current_speaker and in_reveal else 0
        is_current_speaker = (current_speaker.id == for_player_id) if current_speaker else False
        quota_reached = (revealed_now >= req_reveals) if current_speaker else False

        current_debate_speaker = self.get_current_debate_speaker() if self.phase in (PHASE_DEBATE, PHASE_ACCUSATION) else None
        curr_acc = self.get_current_accusation_speaker() if self.phase == PHASE_ACCUSATION else None
        curr_just = self.get_current_justification_speaker() if self.phase == PHASE_JUSTIFICATION else None
        for_player = self.players.get(for_player_id) if for_player_id else None

        # Проверяем вендетту: может ли текущий изгнанник отомстить
        can_trigger_vendetta = False
        if not self.exile_vendetta_used and for_player and not for_player.is_alive and self.phase not in (PHASE_LOBBY, PHASE_FINAL):
            can_trigger_vendetta = is_exile_alive_on_surface(for_player, self.catastrophe)["is_alive_surface"]

        raw = {
            "room_code": self.room_code,
            "balance_version": BALANCE_VERSION,
            "lobby": self.lobby_state(for_player_id) if self.phase == PHASE_LOBBY else None,
            "match_settings": copy.deepcopy(self.match_settings),
            "phase": self.phase,
            "phase_context": self.phase_context(),
            "result_review": self.review_state_for(for_player_id),
            "last_vote_summary": copy.deepcopy(self.last_vote_summary),
            "game_mode": self.game_mode,
            "round_number": self.round_number,
            "turn_id": self.turn_id,
            "speech_effects": public_effects(self, for_player_id),
            "round_direction": "reverse" if (self.round_number % 2 == 0) else "forward",
            "is_reverse_round": (self.round_number % 2 == 0),
            "bunker_capacity": self.effective_lobby_capacity() if self.phase == PHASE_LOBBY else self.bunker_capacity,
            "alive_count": alive_count,
            "total_players": len(self.players),
            "is_host": is_host,
            "is_registered": (for_player_id in self.players),
            "can_claim_host": (self.host_id not in self.players or not self.players[self.host_id].connected),
            "enable_traitor": self.enable_traitor,
            "catastrophe": self.catastrophe,
            "bunker": self.bunker,
            "timers_config": {
                "reveal": self.reveal_duration_sec,
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
                "is_silenced": (current_speaker.is_speech_silenced or current_speaker.is_quarantined) if current_speaker else False
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
            "reveal_status": {
                "active": in_reveal,
                "required_count": req_reveals,
                "revealed_count": revealed_now,
                "can_proceed": self.can_speaker_proceed() if in_reveal else False,
                "is_current_speaker": is_current_speaker and in_reveal,
                "current_speaker_id": current_speaker.id if current_speaker and in_reveal else None,
                "current_speaker_name": current_speaker.name if current_speaker and in_reveal else None,
                "quota_reached": quota_reached if in_reveal else False,
                "duration_sec": self.reveal_duration_sec
            },
            "reveal_quota": {
                "active": in_reveal,
                "required": req_reveals,
                "opened": revealed_now,
                "profession_required": (in_reveal and self.round_number == 1 and bool(current_speaker) and not current_speaker.cards.get("profession", {}).get("revealed", False))
            },
            "speech_status": {
                "required_count": req_reveals,
                "revealed_count": revealed_now,
                "can_proceed": self.can_speaker_proceed(),
                "is_current_speaker": is_current_speaker,
                "current_speaker_id": current_speaker.id if current_speaker else None,
                "current_speaker_name": current_speaker.name if current_speaker else None,
                "quota_reached": quota_reached,
                "is_silenced": (current_speaker.is_speech_silenced or current_speaker.is_quarantined) if current_speaker else False
            },
            "speaker_status": {
                "required_count": req_reveals,
                "revealed_count": revealed_now,
                "can_proceed": self.can_speaker_proceed(),
                "is_current_speaker": is_current_speaker,
                "current_speaker_id": current_speaker.id if current_speaker else None,
                "current_speaker_name": current_speaker.name if current_speaker else None,
                "quota_reached": quota_reached,
                "is_silenced": (current_speaker.is_speech_silenced or current_speaker.is_quarantined) if current_speaker else False
            },
            "voting_status": {
                "my_vote": self.votes.get(for_player_id) if for_player else None,
                "total_voters": len(voters),
                "total_vote_weight": total_vote_weight,
                "votes_cast": sum(p.id in self.votes for p in voters),
                "all_voted": all(p.id in self.votes for p in voters)
            },
            "skip_round_info": {
                "can_skip": (self.phase == PHASE_VOTING and self.round_number == 1 and self.forced_revote_round != self.round_number and not (for_player and for_player.is_quarantined)),
                "skip_votes": skip_vote_weight,
                "needed": (total_vote_weight // 2) + 1,
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
                "is_sortie_skipped": self.is_sortie_skipped,
                "last_resolved": self.event_result_for(self.last_resolved_event, for_player_id),
                "resolved_history": self.events_history_for(for_player_id),
                "events_score_delta": self.events_score_delta,
                "score_delta": self.events_score_delta,
                "boosted_profession_tags": self.boosted_profession_tags
            },
            "game_log": self.game_log[-16:]
        }
        return public_state(self, raw)


# Alias for backward compatibility
GameRoom = BunkerGameRoom
