"""
Модуль виртуальных ботов-игроков для тестирования игры «Бункер».
Подключает заданное количество ботов к указанной комнате, поддерживает постоянное WebSocket-соединение,
автоматически вскрывает характеристики в свой ход речи и голосует в фазе голосования.
"""

import asyncio
import json
import random
import sys
import time
import urllib.request
from typing import List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import websockets

BOT_NAMES_POOL = [
    "🤖 Алексей (Бот)",
    "🤖 София (Бот)",
    "🤖 Дмитрий (Бот)",
    "🤖 Елена (Бот)",
    "🤖 Максим (Бот)",
    "🤖 Дарья (Бот)",
    "🤖 Артём (Бот)",
    "🤖 Полина (Бот)",
    "🤖 Роман (Бот)",
    "🤖 Ксения (Бот)"
]

CARD_PRIORITY = ["profession", "biology", "health", "baggage", "hobby", "fact", "special"]


class BunkerBot:
    def __init__(self, room_code: str, name: str, base_url: str = "http://127.0.0.1:64738", ws_url: str = "ws://127.0.0.1:64738/ws"):
        self.room_code = room_code.upper()
        self.name = name
        self.base_url = base_url
        self.ws_url = ws_url
        self.player_id: Optional[str] = None
        self.ws = None
        self.latest_state: Optional[dict] = None
        self.is_running = True
        self.last_revealed_round = 0
        self.has_revealed_in_current_speech = False
        self.has_spoken_in_debate = False

    def join_room(self, max_retries: int = 45) -> bool:
        """Регистрирует бота в комнате через HTTP API, ожидая создания комнаты при необходимости"""
        url = f"{self.base_url}/api/room/join"
        payload = json.dumps({"room_code": self.room_code, "player_name": self.name}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.player_id = data["player_id"]
                    print(f"[{self.name}] Успешно вошел в лобби комнаты {self.room_code} (ID: {self.player_id})")
                    return True
            except Exception as e:
                if attempt == 0:
                    print(f"[{self.name}] Комната {self.room_code} еще не создана. Ожидание запуска ведущим...")
                time.sleep(2)
        print(f"[{self.name}] Превышено время ожидания комнаты {self.room_code}.")
        return False

    async def run(self):
        """Основной цикл бота: подключение WebSocket и реакция на фазы игры"""
        if not self.player_id:
            if not self.join_room():
                return

        endpoint = f"{self.ws_url}/{self.room_code}/{self.player_id}"
        
        while self.is_running:
            try:
                print(f"[{self.name}] Подключение WebSocket к {endpoint}...")
                async with websockets.connect(endpoint) as ws:
                    self.ws = ws
                    print(f"[{self.name}] WebSocket подключен и активен ✅")
                    
                    # Запускаем фоновые задачи для пинга и принятия решений
                    receiver_task = asyncio.create_task(self._receive_loop())
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    ai_task = asyncio.create_task(self._ai_decision_loop())
                    
                    done, pending = await asyncio.wait(
                        [receiver_task, heartbeat_task, ai_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        task.cancel()
                        
            except asyncio.CancelledError:
                print(f"[{self.name}] Остановлен.")
                break
            except Exception as e:
                print(f"[{self.name}] Связь потеряна ({e}), переподключение через 3 сек...")
                await asyncio.sleep(3)

    async def _receive_loop(self):
        """Прием обновлений от сервера"""
        while self.is_running and self.ws:
            try:
                raw = await self.ws.recv()
                msg = json.loads(raw)
                if msg.get("type") == "STATE_UPDATE":
                    self.latest_state = msg.get("state", {})
            except Exception:
                break

    async def _heartbeat_loop(self):
        """Пинг сервера для предотвращения таймаута"""
        while self.is_running and self.ws:
            try:
                await asyncio.sleep(4)
                await self.ws.send(json.dumps({"action": "PING"}))
            except Exception:
                break

    async def _ai_decision_loop(self):
        """Автоматические действия бота в зависимости от фазы игры"""
        last_phase = None
        voted_in_voting_phase = False

        while self.is_running and self.ws:
            await asyncio.sleep(1.0)
            if not self.latest_state:
                continue

            phase = self.latest_state.get("phase")
            if phase != last_phase:
                last_phase = phase
                self.has_revealed_in_current_speech = False
                voted_in_voting_phase = False
                # print(f"[{self.name}] Замечена смена фазы на {phase}")

            # Находим свои данные в списке игроков
            players = self.latest_state.get("players", [])
            my_info = next((p for p in players if p["id"] == self.player_id), None)
            if not my_info or not my_info.get("is_alive", True):
                # Бот выбыл или не найден
                continue

            my_cards = my_info.get("cards", {})

            # 1. Фаза индивидуальной речи (SPEECH)
            if phase == "SPEECH":
                self.has_spoken_in_debate = False
                curr_spk = self.latest_state.get("current_speaker") or {}
                if curr_spk.get("id") == self.player_id:
                    if not self.has_revealed_in_current_speech:
                        self.has_revealed_in_current_speech = True
                        await asyncio.sleep(random.uniform(1.0, 2.0))
                        
                        round_num = self.latest_state.get("round_number", 1)
                        target_cats = []
                        if round_num == 1:
                            prof_card = my_cards.get("profession")
                            if prof_card and not prof_card.get("revealed", False):
                                target_cats.append("profession")
                        else:
                            # Во 2-м и последующих раундах вскрываем по 2 характеристики
                            for cat in CARD_PRIORITY:
                                card = my_cards.get(cat)
                                if card and not card.get("revealed", False):
                                    target_cats.append(cat)
                                    if len(target_cats) >= 2:
                                        break
                        
                        for target_cat in target_cats:
                            print(f"[{self.name}] 🗣️ Мой ход речи! Вскрываю характеристику: {target_cat}")
                            await self.ws.send(json.dumps({
                                "action": "REVEAL_CARD",
                                "payload": {"category": target_cat}
                            }))
                            await asyncio.sleep(0.5)

                        # После вскрытия даем 2 секунды паузу и передаем слово следующему
                        await asyncio.sleep(random.uniform(1.8, 3.2))
                        try:
                            await self.ws.send(json.dumps({"action": "NEXT_SPEAKER"}))
                        except Exception:
                            pass
                else:
                    self.has_revealed_in_current_speech = False

            # 2. Фаза поочередных дебатов (DEBATE)
            elif phase == "DEBATE":
                self.has_revealed_in_current_speech = False
                deb_spk = self.latest_state.get("debate_speaker") or {}
                if deb_spk.get("id") == self.player_id:
                    if not self.has_spoken_in_debate:
                        self.has_spoken_in_debate = True
                        # Бот выступает 3-5 секунд в Discord/чат и передает слово
                        await asyncio.sleep(random.uniform(2.5, 4.5))
                        print(f"[{self.name}] 🎙️ Мое слово на дебатах! Выступаю в защиту своей кандидатуры и передаю слово.")
                        try:
                            await self.ws.send(json.dumps({"action": "NEXT_DEBATE_SPEAKER"}))
                        except Exception:
                            pass
                else:
                    self.has_spoken_in_debate = False

            # 3. Фаза голосования (VOTING)
            elif phase == "VOTING":
                self.has_revealed_in_current_speech = False
                self.has_spoken_in_debate = False
                if not voted_in_voting_phase and not my_info.get("has_voted", False):
                    voted_in_voting_phase = True
                    # Задержка 2-4 секунды перед голосованием для естественности
                    await asyncio.sleep(random.uniform(1.5, 4.0))
                    
                    if self.latest_state.get("phase") != "VOTING":
                        continue

                    alive_players = [
                        p for p in players 
                        if p["is_alive"] and p["id"] != self.player_id and not p.get("has_immunity", False)
                    ]

                    # Проверяем, активен ли тайбрейк
                    vote_res = self.latest_state.get("vote_results") or {}
                    is_tie = bool(vote_res.get("is_tie") and vote_res.get("top_candidates"))
                    if is_tie:
                        tie_pool = [p for p in alive_players if p["id"] in vote_res["top_candidates"]]
                        if tie_pool:
                            alive_players = tie_pool

                    # Возможность воздержаться (20% вероятность, кроме тайбрейка)
                    should_abstain = (random.random() < 0.20) and not is_tie
                    if should_abstain:
                        print(f"[{self.name}] ⚪ Воздерживаюсь от голосования (ABSTAIN)")
                        await self.ws.send(json.dumps({
                            "action": "CAST_VOTE",
                            "payload": {"target_id": "ABSTAIN"}
                        }))
                    elif alive_players:
                        target = random.choice(alive_players)
                        print(f"[{self.name}] 🗳️ Голосую против: {target['name']} ({target['id']})")
                        await self.ws.send(json.dumps({
                            "action": "CAST_VOTE",
                            "payload": {"target_id": target["id"]}
                        }))


async def spawn_bots_for_room(room_code: str, count: int = 6, base_url: str = "http://127.0.0.1:64738", ws_url: str = "ws://127.0.0.1:64738/ws"):
    """Запускает группу ботов для указанной комнаты"""
    print(f"\n==================================================")
    print(f"  🤖 ЗАПУСК {count} ТЕСТОВЫХ БОТОВ В КОМНАТУ: {room_code}")
    print(f"==================================================")
    
    names = BOT_NAMES_POOL[:count]
    if len(names) < count:
        for i in range(len(names) + 1, count + 1):
            names.append(f"🤖 Бот-{i}")

    bots = [BunkerBot(room_code, name, base_url=base_url, ws_url=ws_url) for name in names]
    
    # Подключаем ботов последовательно с маленькой паузой
    tasks = []
    for bot in bots:
        tasks.append(asyncio.create_task(bot.run()))
        await asyncio.sleep(0.4)

    print(f"\n✅ Все {count} ботов запущены и находятся в комнате {room_code}!")
    print("Боты будут автоматически вскрывать характеристики в свой ход и голосовать.\n")

    await asyncio.gather(*tasks)


def main():
    room_code = "WDBE"
    count = 6
    if len(sys.argv) > 1:
        room_code = sys.argv[1].strip().upper()
    if len(sys.argv) > 2:
        try:
            count = int(sys.argv[2])
        except ValueError:
            count = 6

    asyncio.run(spawn_bots_for_room(room_code, count=count))


if __name__ == "__main__":
    main()
