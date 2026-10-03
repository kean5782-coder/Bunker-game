"""
Bunker Game Bot Runner
Spawns autonomous AI bot clients that connect via WebSockets and play the game.
"""

import argparse
import asyncio
import json
import logging
import random
import sys
import urllib.request
import websockets
try:
    from .bot_turns import plan_turn
except ImportError:  # Also supports python server/bot_client.py
    from bot_turns import plan_turn

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
        sys.stdin.reconfigure(encoding='utf-8')
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bunker.bot")

BOT_NAMES = [
    "Бот Алексей",
    "Бот Марина",
    "Бот Виктор",
    "Бот Елена",
    "Бот Дмитрий",
    "Бот София",
    "Бот Михаил",
    "Бот Анна",
    "Бот Артем",
    "Бот Полина",
    "Бот Роман",
    "Бот Ксения",
    "Бот Денис",
    "Бот Дарья",
    "Бот Игорь",
    "Бот Алиса"
]

CARD_CATEGORIES = [
    "profession", "health", "gender", "body", "trait", 
    "phobia", "big_inventory", "backpack", "hobby", "fact"
]


class BunkerBot:
    def __init__(self, name: str, room_code: str, host_url: str):
        self.name = name
        self.room_code = room_code.upper()
        self.host_url = host_url.rstrip("/")
        self.ws_url = self.host_url.replace("http://", "ws://").replace("https://", "wss://")
        self.player_id = None
        self.ws = None
        self.running = True
        self.last_action_phase = None
        self.has_voted_this_round = False
        self.has_voted_this_revote = False
        self.current_round = 0
        self.latest_state = None
        self._last_turn_command = None

    def join_room(self) -> bool:
        url = f"{self.host_url}/api/room/join"
        payload = json.dumps({
            "room_code": self.room_code,
            "player_name": self.name
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.player_id = data.get("player_id")
                logger.info(f"{self.name} успешно присоединился к комнате {self.room_code} (ID: {self.player_id})")
                return True
        except Exception as e:
            logger.error(f"{self.name} ошибка при входе в комнату: {e}")
            return False

    async def send_action(self, action: str, payload: dict = None):
        if not self.ws or (self.latest_state or {}).get("result_review"):
            return
        msg = {
            "action": action,
            "payload": payload or {}
        }
        await self.ws.send(json.dumps(msg))
        logger.info(f"[{self.name}] -> {action} {payload or ''}")

    async def handle_game_state(self, state: dict):
        if state.get("result_review"):
            self._last_turn_command = None
            self.has_voted_this_round = False
            self.has_voted_this_revote = False
            return
        phase = state.get("phase")
        round_num = state.get("round_number", 1)

        # Reset round tracking
        if round_num != self.current_round:
            self.current_round = round_num
            self.has_voted_this_round = False
            self.has_voted_this_revote = False

        if phase != self.last_action_phase:
            self.last_action_phase = phase
            if phase == "VOTING":
                self.has_voted_this_round = False
            elif phase in ("JUSTIFICATION", "REVOTE"):
                self.has_voted_this_revote = False

        players = state.get("players", [])
        me = next((p for p in players if p["id"] == self.player_id), None)
        if not me:
            return

        is_alive = me.get("is_alive", True)

        if phase in ("PROLOGUE", "LOBBY"):
            return

        # 1. Separate reveal and first-speech circles. Reserve a command before
        # awaiting: several STATE_UPDATE tasks can arrive for the same turn.
        if phase in ("REVEAL", "SPEECH") and is_alive:
            priority = random.sample(CARD_CATEGORIES, len(CARD_CATEGORIES))
            command = plan_turn(state, self.player_id, priority)
            if command:
                key = (state.get("turn_id"), command["action"],
                       (state.get("reveal_status") or {}).get("revealed_count"))
                if key == self._last_turn_command:
                    return
                self._last_turn_command = key
                await asyncio.sleep(random.uniform(1.0, 2.0))
                latest = self.latest_state or state
                if (latest.get("turn_id") != state.get("turn_id")
                        or latest.get("phase") != phase
                        or (latest.get("current_speaker") or {}).get("id") != self.player_id):
                    return
                await self.send_action(command["action"], command["payload"])

        # 2. ACCUSATION / DEBATE PHASE
        elif phase in ("ACCUSATION", "DEBATE") and is_alive:
            acc_speaker = state.get("accusation_speaker") or state.get("debate_speaker")
            if acc_speaker and acc_speaker.get("id") == self.player_id:
                await asyncio.sleep(random.uniform(2.5, 4.5))
                await self.send_action("NEXT_ACCUSATION_SPEAKER", {})

        # 3. VOTING PHASE
        elif phase == "VOTING" and is_alive:
            has_voted = me.get("has_voted", False)
            if not has_voted and not self.has_voted_this_round:
                self.has_voted_this_round = True
                await asyncio.sleep(random.uniform(2.0, 5.0))
                
                # Round 1 skip voting check (Option 5Б)
                skip_info = state.get("skip_round_info", {})
                if skip_info.get("can_skip") and random.random() < 0.25:
                    await self.send_action("CAST_VOTE", {"target_id": "SKIP_ROUND"})
                    return

                alive_others = [p["id"] for p in players if p["is_alive"] and p["id"] != self.player_id]
                if alive_others:
                    # 92% vote against someone, 8% abstain
                    if random.random() < 0.92:
                        vote_target = random.choice(alive_others)
                    else:
                        vote_target = None
                    await self.send_action("CAST_VOTE", {"target_id": vote_target})

        # 4. JUSTIFICATION PHASE
        elif phase == "JUSTIFICATION" and is_alive:
            just_status = state.get("justification_status", {})
            if just_status.get("speaker_id") == self.player_id:
                await asyncio.sleep(random.uniform(2.0, 4.0))
                await self.send_action("NEXT_JUSTIFICATION_SPEAKER", {})

        # 5. REVOTE PHASE
        elif phase == "REVOTE" and is_alive:
            if not self.has_voted_this_revote:
                self.has_voted_this_revote = True
                await asyncio.sleep(random.uniform(1.5, 4.0))
                revote_status = state.get("revote_status", {})
                candidates = revote_status.get("candidates", [])
                other_candidates = [cid for cid in candidates if cid != self.player_id]
                target_cand = random.choice(other_candidates) if other_candidates else (candidates[0] if candidates else None)
                if target_cand:
                    await self.send_action("CAST_VOTE", {"target_id": target_cand})

        # 6. LAST WORD PHASE
        elif phase == "LAST_WORD":
            last_word = state.get("last_word")
            if last_word and last_word.get("speaker_id") == self.player_id:
                await asyncio.sleep(random.uniform(3.0, 5.0))
                await self.send_action("FINISH_LAST_WORD", {})

        # 7. EXILE VENDETTA
        elif not is_alive:
            vendetta = state.get("exile_vendetta", {})
            if vendetta.get("can_trigger") and not vendetta.get("used"):
                if random.random() < 0.60:
                    await asyncio.sleep(random.uniform(3.0, 8.0))
                    await self.send_action("EXILE_VENDETTA", {})

    async def run(self):
        if not self.player_id:
            if not self.join_room():
                return

        ws_endpoint = f"{self.ws_url}/ws/{self.room_code}/{self.player_id}"
        logger.info(f"[{self.name}] Подключение к WebSocket: {ws_endpoint}")

        while self.running:
            try:
                async with websockets.connect(ws_endpoint) as ws:
                    self.ws = ws
                    self._last_turn_command = None
                    logger.info(f"[{self.name}] WebSocket соединен!")

                    # Ping task
                    async def ping_loop():
                        while self.running:
                            try:
                                await asyncio.sleep(10)
                                if self.ws:
                                    await self.ws.send(json.dumps({"action": "PING"}))
                            except Exception:
                                break

                    ping_task = asyncio.create_task(ping_loop())

                    try:
                        async for message in ws:
                            try:
                                data = json.loads(message)
                                msg_type = data.get("type")
                                if msg_type == "STATE_UPDATE":
                                    game_state = data.get("state", {})
                                    self.latest_state = game_state
                                    asyncio.create_task(self.handle_game_state(game_state))
                                elif msg_type == "ERROR":
                                    self._last_turn_command = None
                            except Exception as parse_err:
                                logger.warning(f"[{self.name}] Ошибка обработки сообщения: {parse_err}")
                    finally:
                        ping_task.cancel()

            except websockets.exceptions.ConnectionClosed as e:
                if getattr(e, 'code', None) in (1000, 4004) or not self.running:
                    logger.info(f"[{self.name}] Соединение завершено ({getattr(e, 'code', '')}). Остановка бота.")
                    break
                logger.warning(f"[{self.name}] Потеря соединения ({e}). Переподключение через 2 сек...")
                await asyncio.sleep(2)
            except (ConnectionRefusedError, OSError) as e:
                logger.warning(f"[{self.name}] Ошибка сети ({e}). Переподключение через 2 сек...")
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"[{self.name}] Неожиданная ошибка: {e}")
                await asyncio.sleep(2)


async def main():
    parser = argparse.ArgumentParser(description="Запуск ботов для игры «Бункер»")
    parser.add_argument("--room", type=str, default=None, help="Код комнаты")
    parser.add_argument("--count", type=int, default=None, help="Количество ботов")
    parser.add_argument("--host", type=str, default="http://localhost:8008", help="URL сервера")
    args = parser.parse_args()

    room = (args.room or "").strip().upper()
    while not room:
        try:
            val = input("Введите 4-значный код комнаты (например, FBYI): ").strip().upper()
            if val:
                room = val
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)

    count = args.count
    if count is None:
        try:
            c_str = input("Количество ботов [по умолчанию 5]: ").strip()
            count = int(c_str) if c_str.isdigit() and int(c_str) > 0 else 5
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)

    names = BOT_NAMES[:count]
    while len(names) < count:
        names.append(f"Бот #{len(names) + 1}")

    bots = [BunkerBot(name=name, room_code=room, host_url=args.host) for name in names]
    logger.info(f"Запуск {len(bots)} ботов в комнату {room}...")

    tasks = [asyncio.create_task(bot.run()) for bot in bots]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Работа ботов остановлена пользователем.")
