"""
Основной веб-сервер игры «Бункер» на FastAPI + WebSockets.
"""

import os
import sys
import json
import time
import asyncio
import string
import random

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bunker.server")

from contextlib import asynccontextmanager
from typing import Dict, Set, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel


from .game_engine import (
    BunkerGameRoom, 
    PHASE_LOBBY, 
    PHASE_PROLOGUE,
    PHASE_SPEECH, 
    PHASE_COLLECTIVE_DISCUSSION,
    PHASE_ACCUSATION,
    PHASE_DEBATE, 
    PHASE_VOTING, 
    PHASE_JUSTIFICATION,
    PHASE_REVOTE,
    PHASE_VOTE_RESULTS, 
    PHASE_LAST_WORD,
    PHASE_FINAL
)
from .network_utils import (
    get_local_ip, 
    get_external_ip, 
    generate_qr_data_url, 
    get_config, 
    get_domain_info
)

# Хранилище активных комнат
rooms: Dict[str, BunkerGameRoom] = {}

# Хранилище подключений WebSocket: room_code -> {player_id: WebSocket}
connections: Dict[str, Dict[str, WebSocket]] = {}

PORT = int(os.getenv("PORT", get_config().get("port", 8008)))


def generate_room_code() -> str:
    """Генерирует 4-буквенный уникальный код комнаты"""
    chars = string.ascii_uppercase
    for _ in range(100):
        code = "".join(random.choices(chars, k=4))
        if code not in rooms:
            return code
    return f"B{random.randint(100, 999)}"

async def timer_background_worker():
    """Фоновый цикл для отсчета секунд во всех активных комнатах и очистки неактивных комнат"""
    clean_counter = 0
    while True:
        try:
            await asyncio.sleep(1)
            clean_counter += 1
            now = time.time()

            for room_code, room in list(rooms.items()):
                if room.phase not in (PHASE_LOBBY, PHASE_FINAL, PHASE_PROLOGUE):
                    timer_changed = room.tick_timer()
                    if timer_changed or (room.timer_seconds_left > 0 and not room.timer_is_paused):
                        await broadcast_room_state(room_code)

            # Каждые 5 минут проверяем комнаты на TTL (удаляем неактивные > 6 часов)
            if clean_counter >= 300:
                clean_counter = 0
                for r_code, r in list(rooms.items()):
                    has_active_conns = bool(connections.get(r_code))
                    if not has_active_conns and (now - r.last_activity > 21600): # 6 hours
                        del rooms[r_code]
                        if r_code in connections:
                            del connections[r_code]
                        logger.info(f"Room {r_code} cleaned up due to inactivity.")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in timer worker: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    timer_task = asyncio.create_task(timer_background_worker())
    
    local_ip = get_local_ip()
    external_ip = get_external_ip()
    domain_display, domain_punycode = get_domain_info()

    logger.info("=" * 68)
    logger.info("  🚀 СЕРВЕР ИГРЫ «БУНКЕР» УСПЕШНО ЗАПУЩЕН!")
    logger.info(f"  💻 На этом компьютере:              http://localhost:{PORT}")
    logger.info(f"  🏠 Для устройств в сети Wi-Fi:      http://{local_ip}:{PORT}")
    if domain_display:
        logger.info(f"  🌐 Для друзей в Discord (Домен):    http://{domain_display}:{PORT}")
        if domain_display != domain_punycode:
            logger.info(f"     (Punycode адрес для ссылок):     http://{domain_punycode}:{PORT}")
    elif external_ip:
        logger.info(f"  🌐 Для друзей в Discord (Белый IP): http://{external_ip}:{PORT}")
    else:
        logger.info("  🌐 Внешний IP: Не определен автоматически (проверьте интернет)")
    logger.info("=" * 68)
    
    yield
    
    timer_task.cancel()
    # Автоматическое закрытие порта в Брандмауэре Windows при остановке сервера
    try:
        import subprocess
        subprocess.run(
            'netsh advfirewall firewall delete rule name="Bunker Game 8008"', 
            shell=True, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass

app = FastAPI(title="Бункер - Онлайн игра с друзьями", lifespan=lifespan)

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# --- Модели запросов ---

class CreateRoomRequest(BaseModel):
    host_name: str
    enable_traitor: bool = False
    enable_events: bool = True
    game_mode: str = "STANDARD"
    speech_duration: Optional[int] = None
    debate_duration: Optional[int] = None
    voting_duration: Optional[int] = None
    capacity: Optional[int] = None
    room_code: Optional[str] = None

class JoinRoomRequest(BaseModel):
    room_code: str
    player_name: str

class AddBotsRequest(BaseModel):
    count: int = 5

# --- API Endpoints ---

@app.get("/")
async def get_index():
    """Отдает главную страницу игры"""
    index_path = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(index_path)

@app.get("/manifest.json")
async def get_manifest():
    """Manifest для Progressive Web App (PWA)"""
    return JSONResponse({
        "name": "Бункер: Выживание",
        "short_name": "Бункер",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#090c10",
        "theme_color": "#00f0ff",
        "icons": [
            {
                "src": "/static/favicon.ico",
                "sizes": "64x64",
                "type": "image/x-icon"
            }
        ]
    })

@app.get("/api/network-info")
async def get_network_info():
    """Возвращает информацию о локальном и внешнем IP/домене + ссылки"""
    local_ip = get_local_ip()
    external_ip = get_external_ip()
    domain_display, domain_punycode = get_domain_info()
    
    local_url = f"http://{local_ip}:{PORT}"
    
    if domain_punycode:
        ext_url = f"http://{domain_punycode}:{PORT}"
        display_url = f"http://{domain_display}:{PORT}"
    elif external_ip:
        ext_url = f"http://{external_ip}:{PORT}"
        display_url = ext_url
    else:
        ext_url = None
        display_url = None
    
    qr_data = generate_qr_data_url(ext_url or local_url)
    
    return {
        "port": PORT,
        "local_ip": local_ip,
        "external_ip": external_ip,
        "domain": domain_display,
        "domain_punycode": domain_punycode,
        "local_url": local_url,
        "external_url": ext_url,
        "display_url": display_url,
        "qr_code": qr_data
    }

@app.post("/api/room/create")
async def create_room(req: CreateRoomRequest):
    """Создание новой игровой комнаты"""
    room_code = (req.room_code.strip().upper() if req.room_code else None) or generate_room_code()
    
    if room_code in rooms:
        raise HTTPException(status_code=400, detail="Комната с таким кодом уже существует")
        
    host_id = f"host_{random.randint(1000, 9999)}"
    
    room = BunkerGameRoom(room_code, host_id, req.host_name.strip() or "Ведущий")
    room.enable_traitor = req.enable_traitor
    room.events_enabled = req.enable_events
    if req.game_mode:
        room.game_mode = req.game_mode
    if req.speech_duration:
        room.speech_duration_sec = req.speech_duration
    if req.debate_duration:
        room.debate_duration_sec = req.debate_duration
    if req.voting_duration:
        room.voting_duration_sec = req.voting_duration
    if req.capacity:
        room.bunker_capacity = max(1, req.capacity)
    rooms[room_code] = room
    connections[room_code] = {}

    external_ip = get_external_ip()
    local_ip = get_local_ip()
    share_url = f"http://{external_ip}:{PORT}?room={room_code}" if external_ip else f"http://{local_ip}:{PORT}?room={room_code}"
    qr_code = generate_qr_data_url(share_url)

    return {
        "room_code": room_code,
        "host_id": host_id,
        "host_token": room.host_token,
        "share_url": share_url,
        "qr_code": qr_code,
        "enable_traitor": room.enable_traitor,
        "game_mode": room.game_mode
    }

@app.post("/api/room/join")
async def join_room(req: JoinRoomRequest):
    """Подключение игрока к комнате"""
    code = req.room_code.strip().upper()
    if code not in rooms:
        raise HTTPException(status_code=404, detail="Комната с таким кодом не найдена!")

    room = rooms[code]
    if room.phase != PHASE_LOBBY:
        existing = [p for p in room.players.values() if p.name.lower() == req.player_name.strip().lower()]
        if existing:
            return {"room_code": code, "player_id": existing[0].id, "is_host": existing[0].is_host}
        raise HTTPException(status_code=400, detail="Игра уже началась! Новые игроки не могут войти.")

    player_id = f"p_{random.randint(1000, 9999)}"
    room.add_player(player_id, req.player_name.strip() or "Беженец")
    
    await broadcast_room_state(code)
    
    return {
        "room_code": code,
        "player_id": player_id,
        "is_host": False
    }

@app.post("/api/room/{room_code}/add-bots")
async def add_bots_endpoint(room_code: str, req: AddBotsRequest):
    """Добавление ботов в лобби комнаты"""
    code = room_code.strip().upper()
    if code not in rooms:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    room = rooms[code]
    if room.phase != PHASE_LOBBY:
        raise HTTPException(status_code=400, detail="Ботов можно добавлять только в лобби перед стартом игры")

    from .bot_client import BunkerBot, BOT_NAMES
    count = max(1, min(15, req.count))
    existing_names = {p.name for p in room.players.values()}
    available_names = [n for n in BOT_NAMES if n not in existing_names]

    added_count = 0
    for i in range(count):
        name = available_names[i] if i < len(available_names) else f"Бот {len(room.players) + 1}"
        player_id = f"bot_{random.randint(1000, 9999)}"
        while player_id in room.players:
            player_id = f"bot_{random.randint(1000, 9999)}"
        room.add_player(player_id, name)

        bot = BunkerBot(name=name, room_code=code, host_url=f"http://127.0.0.1:{PORT}")
        bot.player_id = player_id

        async def run_bot(b):
            await asyncio.sleep(random.uniform(0.1, 0.4))
            await b.run()

        asyncio.create_task(run_bot(bot))
        added_count += 1

    await broadcast_room_state(code)
    return {"ok": True, "added": added_count, "room_code": code}

class ClaimHostRequest(BaseModel):
    player_name: str = "Ведущий"
    player_id: Optional[str] = None

@app.post("/api/room/{room_code}/claim-host")
async def claim_host(room_code: str, req: ClaimHostRequest):
    """Позволяет игроку занять роль ведущего, если комната в лобби или хост оффлайн"""
    code = room_code.strip().upper()
    if code not in rooms:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    room = rooms[code]

    host_connected = bool(room.host_id in connections.get(code, {}))
    if room.phase != PHASE_LOBBY and host_connected:
        raise HTTPException(status_code=400, detail="Ведущий уже активен в игре!")

    target_id = req.player_id or f"host_{random.randint(1000, 9999)}"
    room.transfer_host(target_id, req.player_name.strip() or "Ведущий")
    await broadcast_room_state(code)

    return {
        "room_code": code,
        "player_id": target_id,
        "player_name": req.player_name.strip() or "Ведущий",
        "is_host": True
    }

@app.get("/api/room/{room_code}")
async def check_room(room_code: str):
    code = room_code.strip().upper()
    if code not in rooms:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    room = rooms[code]
    host_player = room.players.get(room.host_id)
    host_connected = bool(room.host_id in connections.get(code, {}))
    can_claim = (room.phase == PHASE_LOBBY) or not host_connected

    return {
        "room_code": code,
        "phase": room.phase,
        "players_count": len(room.players),
        "enable_traitor": room.enable_traitor,
        "enable_events": room.events_enabled,
        "host_name": host_player.name if host_player else "Ведущий",
        "host_connected": host_connected,
        "can_claim_host": can_claim
    }

# --- WebSocket Трансляция и Диспетчер ---

async def broadcast_room_state(room_code: str):
    """Отправляет актуальное состояние комнаты каждому подключенному клиенту с учетом прав доступа"""
    if room_code not in rooms or room_code not in connections:
        return

    room = rooms[room_code]
    dead_sockets = []

    for player_id, ws in list(connections[room_code].items()):
        try:
            state = room.get_state(for_player_id=player_id)
            await ws.send_text(json.dumps({
                "type": "STATE_UPDATE",
                "state": state
            }))
        except Exception:
            dead_sockets.append(player_id)

    for pid in dead_sockets:
        if pid in connections[room_code]:
            del connections[room_code][pid]

@app.websocket("/ws/{room_code}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, room_code: str, player_id: str):
    room_code = room_code.upper()
    if room_code not in rooms:
        await websocket.accept()
        await websocket.close(code=4004, reason="Room not found")
        return

    room = rooms[room_code]
    await websocket.accept()

    if room_code not in connections:
        connections[room_code] = {}
    connections[room_code][player_id] = websocket

    if player_id in room.players:
        room.players[player_id].connected = True
        room.players[player_id].last_seen = time.time()

    await broadcast_room_state(room_code)

    try:
        while True:
            data_text = await websocket.receive_text()
            data = json.loads(data_text)
            action = data.get("action")
            payload = data.get("payload", {})

            # Heartbeat ping
            if action == "PING":
                if player_id in room.players:
                    room.players[player_id].last_seen = time.time()
                await websocket.send_text(json.dumps({"type": "PONG"}))
                continue

            is_host = (player_id == room.host_id)

            try:
                if action == "START_GAME" and is_host:
                    capacity = payload.get("capacity")
                    enable_traitor = payload.get("enable_traitor", room.enable_traitor)
                    enable_events = payload.get("enable_events", room.events_enabled)
                    game_mode = payload.get("game_mode", room.game_mode)
                    speech_duration = payload.get("speech_duration", room.speech_duration_sec)
                    debate_duration = payload.get("debate_duration", room.debate_duration_sec)
                    voting_duration = payload.get("voting_duration", room.voting_duration_sec)
                    last_word_duration = payload.get("last_word_duration", room.last_word_duration_sec)
                    room.start_game(
                        capacity=capacity,
                        enable_traitor=enable_traitor,
                        enable_events=enable_events,
                        game_mode=game_mode,
                        speech_duration=speech_duration,
                        debate_duration=debate_duration,
                        voting_duration=voting_duration,
                        last_word_duration=last_word_duration,
                        skip_prologue=False
                    )

                elif action in ("ENTER_BUNKER", "FINISH_PROLOGUE"):
                    room.enter_bunker(player_id)
                    await broadcast_room_state(room_code)

                elif action == "ADD_BOTS" and is_host:
                    if room.phase != PHASE_LOBBY:
                        raise ValueError("Ботов можно добавлять только в лобби перед стартом игры!")
                    req_count = int(payload.get("count", 5))
                    from .bot_client import BunkerBot, BOT_NAMES
                    count = max(1, min(15, req_count))
                    existing_names = {p.name for p in room.players.values()}
                    available_names = [n for n in BOT_NAMES if n not in existing_names]

                    for i in range(count):
                        name = available_names[i] if i < len(available_names) else f"Бот {len(room.players) + 1}"
                        bot_pid = f"bot_{random.randint(1000, 9999)}"
                        while bot_pid in room.players:
                            bot_pid = f"bot_{random.randint(1000, 9999)}"
                        room.add_player(bot_pid, name)

                        bot = BunkerBot(name=name, room_code=room_code, host_url=f"http://127.0.0.1:{PORT}")
                        bot.player_id = bot_pid

                        async def run_bot_task(b):
                            await asyncio.sleep(random.uniform(0.1, 0.4))
                            await b.run()

                        asyncio.create_task(run_bot_task(bot))

                    await broadcast_room_state(room_code)

                elif action == "FINISH_LAST_WORD":
                    if is_host or (room.eliminated_in_last_word_id == player_id):
                        room.finish_last_word()
                    else:
                        raise ValueError("Пропустить последнее слово может только выступающий или ведущий!")

                elif action == "ANNOUNCE_PEEKED":
                    room.announce_peeked(player_id)

                elif action == "EXILE_VENDETTA":
                    room.trigger_exile_vendetta(player_id)

                elif action == "REVEAL_CARD":
                    category = payload.get("category")
                    room.reveal_player_card(player_id, category)

                elif action == "HOST_FORCE_NEXT_SPEAKER" and is_host:
                    if room.phase == PHASE_SPEECH:
                        room.next_speaker(force=True)
                    elif room.phase == PHASE_COLLECTIVE_DISCUSSION:
                        room.start_accusation_phase()
                    elif room.phase == PHASE_ACCUSATION:
                        room.next_accusation_speaker()
                    elif room.phase == PHASE_JUSTIFICATION:
                        room.next_justification_speaker()
                    elif room.phase == PHASE_DEBATE:
                        room.next_debate_speaker()
                    elif room.phase == PHASE_LAST_WORD:
                        room.finish_last_word()

                elif action == "NEXT_SPEAKER":
                    if is_host:
                        if room.phase == PHASE_SPEECH:
                            room.next_speaker(force=True)
                        elif room.phase == PHASE_COLLECTIVE_DISCUSSION:
                            room.start_accusation_phase()
                        elif room.phase == PHASE_ACCUSATION:
                            room.next_accusation_speaker()
                        elif room.phase == PHASE_JUSTIFICATION:
                            room.next_justification_speaker()
                        elif room.phase == PHASE_DEBATE:
                            room.next_debate_speaker()
                        elif room.phase == PHASE_LAST_WORD:
                            room.finish_last_word()
                    else:
                        if room.phase == PHASE_SPEECH:
                            current_sp = room.get_current_speaker()
                            if current_sp and current_sp.id == player_id:
                                room.next_speaker(force=False)
                            else:
                                raise ValueError("Передать слово может только текущий оратор или ведущий!")
                        elif room.phase == PHASE_ACCUSATION:
                            current_acc = room.get_current_accusation_speaker()
                            if current_acc and current_acc.id == player_id:
                                room.next_accusation_speaker()
                            else:
                                raise ValueError("Сейчас не ваше слово на раунде обвинений!")
                        elif room.phase == PHASE_JUSTIFICATION:
                            current_just = room.get_current_justification_speaker()
                            if current_just and current_just.id == player_id:
                                room.next_justification_speaker()
                            else:
                                raise ValueError("Сейчас не ваше слово для оправдания!")
                        elif room.phase == PHASE_DEBATE:
                            current_deb = room.get_current_debate_speaker()
                            if current_deb and current_deb.id == player_id:
                                room.next_debate_speaker()
                            else:
                                raise ValueError("Сейчас не ваше слово на дебатах!")

                elif action == "START_COLLECTIVE_DISCUSSION" and is_host:
                    room.start_collective_discussion()

                elif action == "START_ACCUSATION" and is_host:
                    room.start_accusation_phase()

                elif action in ("NEXT_ACCUSATION_SPEAKER", "NEXT_DEBATE_SPEAKER"):
                    if is_host:
                        if room.phase == PHASE_COLLECTIVE_DISCUSSION:
                            room.start_accusation_phase()
                        elif room.phase == PHASE_ACCUSATION:
                            room.next_accusation_speaker()
                        else:
                            room.next_debate_speaker()
                    else:
                        current_deb = room.get_current_accusation_speaker() or room.get_current_debate_speaker()
                        if current_deb and current_deb.id == player_id:
                            if room.phase == PHASE_ACCUSATION:
                                room.next_accusation_speaker()
                            else:
                                room.next_debate_speaker()
                        else:
                            raise ValueError("Сейчас не ваше слово на раунде обвинений / дебатов!")

                elif action == "NEXT_JUSTIFICATION_SPEAKER":
                    current_just = room.get_current_justification_speaker()
                    if is_host or (current_just and current_just.id == player_id):
                        room.next_justification_speaker()
                    else:
                        raise ValueError("Сейчас не ваше слово для оправдания!")

                elif action == "GRANT_DEBATE_SPEAKER" and is_host:
                    target_id = payload.get("target_player_id") or payload.get("target_id")
                    if target_id:
                        if room.phase == PHASE_SPEECH:
                            room.host_grant_speech_speaker(target_id)
                        else:
                            room.host_grant_debate_speaker(target_id)

                elif action == "START_DEBATE" and is_host:
                    room.start_debate()

                elif action == "START_VOTING" and is_host:
                    room.start_voting()

                elif action == "CAST_VOTE":
                    target_id = payload.get("target_id")
                    room.cast_vote(player_id, target_id)

                elif action == "CONFIRM_ELIMINATION" and is_host:
                    target_id = payload.get("target_id")
                    room.confirm_elimination(target_id)

                elif action == "USE_SPECIAL_CARD":
                    target_player_id = payload.get("target_player_id")
                    room.use_special_card(player_id, target_player_id)

                # --- Права Хоста (Админ-панель ведущего) ---
                elif action == "HOST_PAUSE_TIMER" and is_host:
                    is_paused = payload.get("is_paused")
                    room.host_pause_timer(is_paused)

                elif action == "HOST_ADD_TIME" and is_host:
                    seconds = payload.get("seconds", 30)
                    room.host_add_time(seconds)

                elif action == "HOST_RESTART_PHASE" and is_host:
                    room.host_restart_phase()

                elif action == "HOST_SET_PHASE" and is_host:
                    new_phase = payload.get("new_phase")
                    room.host_set_phase(new_phase)

                elif action == "HOST_TIEBREAKER" and is_host:
                    room.host_start_tiebreaker()

                elif action == "HOST_ELIMINATE" and is_host:
                    target_id = payload.get("target_id")
                    room.host_eliminate_player(target_id)

                elif action == "HOST_RESTORE" and is_host:
                    target_id = payload.get("target_id")
                    room.host_restore_player(target_id)

                elif action == "HOST_ADJUST_CAPACITY" and is_host:
                    new_capacity = payload.get("capacity", 4)
                    room.host_adjust_capacity(new_capacity)

                elif action == "HOST_TOGGLE_TRAITOR" and is_host:
                    room.enable_traitor = payload.get("enable_traitor", not room.enable_traitor)

                elif action == "HOST_KICK" and is_host:
                    kick_id = payload.get("player_id")
                    if kick_id:
                        room.remove_player(kick_id)
                        if room_code in connections and kick_id in connections[room_code]:
                            kick_ws = connections[room_code].pop(kick_id, None)
                            if kick_ws:
                                try:
                                    await kick_ws.close(code=4004, reason="Kicked by host")
                                except Exception:
                                    pass

                # --- События и испытания ---
                elif action == "ASSIGN_VOLUNTEER":
                    vol_id = payload.get("volunteer_id")
                    if vol_id:
                        room.assign_volunteer(vol_id)

                elif action == "RESOLVE_EVENT" and is_host:
                    force_roll = payload.get("force_roll")
                    room.resolve_active_event(force_roll=force_roll)

                elif action == "HOST_TOGGLE_EVENTS" and is_host:
                    enabled = payload.get("enabled", not room.events_enabled)
                    room.host_toggle_events(enabled)

                elif action == "HOST_TRIGGER_EVENT" and is_host:
                    room.host_trigger_event()

                elif action == "SKIP_SORTIE" and is_host:
                    skip = payload.get("skip", True)
                    room.skip_sortie(skip)

                elif action == "CLAIM_HOST":
                    new_name = payload.get("name")
                    room.transfer_host(player_id, new_name)

                elif action == "JOIN_LOBBY":
                    name = payload.get("name", "Беженец")
                    room.add_player(player_id, name)

                elif action == "PLAY_SOUND_ALERT" and is_host:
                    sound_name = payload.get("sound", "siren")
                    for ws in connections.get(room_code, {}).values():
                        try:
                            await ws.send_text(json.dumps({
                                "type": "PLAY_SOUND",
                                "sound": sound_name
                            }))
                        except Exception:
                            pass

                await broadcast_room_state(room_code)
            except ValueError as ve:
                await websocket.send_text(json.dumps({
                    "type": "ERROR",
                    "message": str(ve)
                }))

    except WebSocketDisconnect:
        if room_code in connections and player_id in connections[room_code]:
            del connections[room_code][player_id]
        if player_id in room.players:
            room.players[player_id].connected = False
        await broadcast_room_state(room_code)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if room_code in connections and player_id in connections[room_code]:
            del connections[room_code][player_id]
