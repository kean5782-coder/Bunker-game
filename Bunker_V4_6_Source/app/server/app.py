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


from .lobby import public_catalog

from .game_engine import (
    BunkerGameRoom, 
    PHASE_LOBBY, 
    PHASE_PROLOGUE,
    PHASE_REVEAL,
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
    get_domain_info, get_connection_info
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
    """One-second gameplay timers, plus an independent shared review clock.

    Frequent polling only publishes when a displayed second changes. Starting a
    review between regular ticks still grants all five seconds; after the review
    the next gameplay timer receives its full first second.
    """
    last_room_tick = {}
    last_cleanup = time.monotonic()
    while True:
        try:
            await asyncio.sleep(0.1)
            now = time.monotonic()
            for room_code, room in list(rooms.items()):
                if room.result_reviews:
                    changed = room.advance_review_clock(now)
                    last_room_tick[room_code] = now
                    if changed:
                        await broadcast_room_state(room_code)
                elif now - last_room_tick.setdefault(room_code, now) >= 1:
                    last_room_tick[room_code] = now
                    if room.phase not in (PHASE_LOBBY, PHASE_FINAL, PHASE_PROLOGUE):
                        changed = room.tick_timer()
                        if changed or (room.timer_seconds_left > 0 and not room.timer_is_paused):
                            await broadcast_room_state(room_code)
            if now - last_cleanup >= 300:
                last_cleanup = now
                wall_time = time.time()
                for room_code, room in list(rooms.items()):
                    if not connections.get(room_code) and wall_time - room.last_activity > 21600:
                        del rooms[room_code]
                        connections.pop(room_code, None)
                        last_room_tick.pop(room_code, None)
                        logger.info(f"Room {room_code} cleaned up due to inactivity.")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error(f"Error in timer worker: {exc}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    timer_task = asyncio.create_task(timer_background_worker())
    
    info = get_connection_info(PORT)
    logger.info("Bunker V4.5 server: %s | %s", info["host_url"], info["connection_label"])
    logger.info("Invitation base: %s", info["share_url"] or "not configured")

    yield
    
    timer_task.cancel()
    # V4.5 never changes Windows Firewall or router settings automatically.

app = FastAPI(title="Бункер - Онлайн игра с друзьями", lifespan=lifespan)

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# --- Модели запросов ---

class CreateRoomRequest(BaseModel):
    host_name: str
    enable_traitor: bool = False
    enable_events: bool = True
    game_mode: str = "STANDARD"
    deal_mode: str = "full_random"
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
    host_token: Optional[str] = None

# --- API Endpoints ---

@app.get("/")
async def get_index():
    """Отдает главную страницу игры"""
    index_path = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(index_path)

@app.get("/api/lobby-options")
async def get_lobby_options():
    from .presentation import MODE_INFO, public_catastrophe, public_bunker
    catalog = public_catalog()
    catalog['catastrophes'] = [public_catastrophe(c) for c in catalog['catastrophes']]
    catalog['bunkers'] = [public_bunker(b) for b in catalog['bunkers']]
    catalog['information_modes'] = list(MODE_INFO.values())
    return catalog


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
    """Selected local connection settings; no public-IP discovery."""
    return get_connection_info(PORT)

@app.get("/api/health")
async def desktop_health():
    return {"application": "bunker", "version": "4.6.0", "status": "ok", "port": PORT,
            "instance": os.getenv("BUNKER_INSTANCE_ID", "") }

@app.get("/help")
async def connection_help():
    return FileResponse(os.path.join(STATIC_DIR, "connection-help.html"))


@app.post("/api/room/create")
async def create_room(req: CreateRoomRequest):
    """Создание новой игровой комнаты"""
    room_code = (req.room_code.strip().upper() if req.room_code else None) or generate_room_code()
    
    if room_code in rooms:
        raise HTTPException(status_code=400, detail="Комната с таким кодом уже существует")
        
    host_id = f"host_{random.randint(1000, 9999)}"
    
    room = BunkerGameRoom(room_code, host_id, req.host_name.strip() or "Ведущий")
    patch = {'enable_traitor': req.enable_traitor, 'enable_events': req.enable_events,
             'game_mode': req.game_mode, 'deal_mode': req.deal_mode, 'preset': 'custom'}
    for key in ('speech_duration', 'voting_duration', 'capacity'):
        value = getattr(req, key)
        if value is not None:
            patch[key] = value
    if req.capacity is not None:
        patch['capacity_mode'] = 'manual'
    if not req.enable_traitor and req.enable_events and req.game_mode == 'STANDARD' and req.deal_mode == 'full_random' and all(
            getattr(req, k) is None for k in ('speech_duration', 'voting_duration', 'capacity')):
        patch['preset'] = 'classic'
    try:
        room.update_lobby_settings(host_id, patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    room.players[host_id].connected = False  # HTTP reservation is not a live socket.
    rooms[room_code] = room
    connections[room_code] = {}

    info = get_connection_info(PORT)
    base = info["share_url"] or info["local_url"]
    share_url = f"{base}/?room={room_code}"
    qr_code = generate_qr_data_url(share_url) if info["connection_mode"] != "porthole" else None

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

    try:
        room.can_join_lobby()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    player_id = f"p_{random.randint(1000, 9999)}"
    while player_id in room.players:
        player_id = f"p_{random.randint(1000, 9999)}"
    participant = room.add_player(player_id, req.player_name.strip() or "Беженец")
    participant.connected = False  # Set True only on actual WebSocket connection.
    
    await broadcast_room_state(code)
    
    return {
        "room_code": code,
        "player_id": player_id,
        "is_host": False
    }

async def add_room_bots(room, count):
    if room.phase != PHASE_LOBBY:
        raise ValueError('Ботов можно добавлять только перед стартом.')
    if type(count) is not int or not 1 <= count <= 19:
        raise ValueError('Можно добавить от 1 до 19 ботов за раз.')
    free = room.lobby_settings['max_players'] - len(room.players)
    if count > free:
        raise ValueError(f'Свободных мест в комнате: {free}. Уменьшите число ботов или увеличьте лимит.')
    from .bot_client import BunkerBot, BOT_NAMES
    names = [n for n in BOT_NAMES if n not in {p.name for p in room.players.values()}]
    for i in range(count):
        name = names[i] if i < len(names) else f'Бот {len(room.players) + 1}'
        pid = f'bot_{random.randint(1000, 9999)}'
        while pid in room.players:
            pid = f'bot_{random.randint(1000, 9999)}'
        p = room.add_player(pid, name)
        p.connected = False  # A task scheduled is not a connected bot yet.
        bot = BunkerBot(name=name, room_code=room.room_code, host_url=f'http://127.0.0.1:{PORT}')
        bot.player_id = pid
        async def run_bot(b):
            await asyncio.sleep(random.uniform(.1, .4))
            await b.run()
        asyncio.create_task(run_bot(bot))
    return count


@app.post("/api/room/{room_code}/add-bots")
async def add_bots_endpoint(room_code: str, req: AddBotsRequest):
    code = room_code.strip().upper()
    if code not in rooms:
        raise HTTPException(status_code=404, detail='Комната не найдена')
    room = rooms[code]
    if not req.host_token or req.host_token != room.host_token:
        raise HTTPException(status_code=403, detail='Добавлять ботов может только ведущий.')
    try:
        added = await add_room_bots(room, req.count)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await broadcast_room_state(code)
    return {'ok': True, 'added': added, 'room_code': code}

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
    if host_connected:
        raise HTTPException(status_code=400, detail="Ведущий уже подключён к комнате.")

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
    can_claim = not host_connected

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
                room.require_review_finished(action)
                lobby_actions = {'UPDATE_LOBBY_SETTINGS', 'SET_LOBBY_READY', 'REMOVE_BOTS', 'START_GAME', 'ADD_BOTS'}
                if action in lobby_actions | {'USE_SPECIAL_CARD', 'SPEECH_PROMPT'} and not isinstance(payload, dict):
                    raise ValueError('Некорректный формат команды.')
                if action in {'UPDATE_LOBBY_SETTINGS', 'REMOVE_BOTS', 'START_GAME', 'ADD_BOTS', 'HOST_KICK'} and not is_host:
                    raise ValueError('Это действие доступно только ведущему.')
                if action == 'UPDATE_LOBBY_SETTINGS':
                    room.update_lobby_settings(player_id, payload.get('settings'), payload.get('expected_revision'))
                    await websocket.send_json({'type': 'ACTION_OK', 'action': action, 'revision': room.lobby_revision})
                elif action == 'SET_LOBBY_READY':
                    room.set_lobby_ready(player_id, payload.get('ready'), payload.get('expected_revision'))
                    await websocket.send_json({'type': 'ACTION_OK', 'action': action})
                elif action == 'REMOVE_BOTS':
                    if room.phase != PHASE_LOBBY:
                        raise ValueError('Удаление ботов доступно только в лобби.')
                    bot_ids = [pid for pid in room.players if pid.startswith('bot_') and pid != room.host_id]
                    for pid in bot_ids:
                        room.remove_player(pid)
                        sock = connections.get(room_code, {}).pop(pid, None)
                        if sock:
                            await sock.close(code=4004, reason='Removed by host')
                    await websocket.send_json({'type': 'ACTION_OK', 'action': action, 'removed': len(bot_ids)})
                elif action == 'START_GAME':
                    # Old clients may send a small legacy settings payload.
                    # It is validated by the same path; it cannot bypass readiness.
                    legacy = {k: v for k, v in payload.items() if k in room.lobby_settings and k != 'preset'}
                    if legacy:
                        if 'capacity' in legacy:
                            legacy['capacity_mode'] = 'manual'
                        legacy['preset'] = 'custom'
                        room.update_lobby_settings(player_id, legacy, payload.get('expected_revision'))
                        revision = room.lobby_revision
                    else:
                        revision = payload.get('expected_revision')
                    room.start_configured_game(player_id, revision)
                    logger.info(f'GAME STARTED room={room_code}')
                    await broadcast_room_state(room_code)
                    await websocket.send_json({'type': 'ACTION_OK', 'action': action})

                elif action in ("ENTER_BUNKER", "FINISH_PROLOGUE"):
                    room.enter_bunker(player_id)
                    await broadcast_room_state(room_code)

                elif action == 'ADD_BOTS':
                    added = await add_room_bots(room, payload.get('count', 5))
                    await websocket.send_json({'type': 'ACTION_OK', 'action': action, 'added': added})

                elif action == "FINISH_LAST_WORD":
                    if is_host or (room.eliminated_in_last_word_id == player_id):
                        room.finish_last_word()
                    else:
                        raise ValueError("Пропустить последнее слово может только выступающий или ведущий!")

                elif action == "ANNOUNCE_PEEKED":
                    room.announce_peeked(player_id)

                elif action == "EXILE_VENDETTA":
                    room.trigger_exile_vendetta(player_id)

                elif action == "NEXT_REVEAL":
                    current = room.get_current_speaker()
                    if not is_host and (not current or current.id != player_id):
                        raise ValueError("Завершить открытие может только текущий участник или ведущий.")
                    room.validate_turn_command(payload.get("expected_turn_id"))
                    room.next_reveal_player(force=is_host)

                elif action == "REVEAL_CARD":
                    room.validate_turn_command(payload.get("expected_turn_id"))
                    category = payload.get("category")
                    room.reveal_player_card(player_id, category)

                elif action == "HOST_FORCE_NEXT_SPEAKER" and is_host:
                    room.validate_turn_command(payload.get("expected_turn_id"))
                    if room.phase in (PHASE_REVEAL, PHASE_SPEECH):
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
                    room.validate_turn_command(payload.get("expected_turn_id"))
                    if is_host:
                        if room.phase in (PHASE_REVEAL, PHASE_SPEECH):
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
                        if room.phase in (PHASE_REVEAL, PHASE_SPEECH):
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
                                raise ValueError("Сейчас не ваше слово во втором круге речей!")
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
                                raise ValueError("Сейчас не ваше слово во втором круге речей!")

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
                            raise ValueError("Сейчас не ваше слово во втором круге речей!")

                elif action == "NEXT_JUSTIFICATION_SPEAKER":
                    current_just = room.get_current_justification_speaker()
                    if is_host or (current_just and current_just.id == player_id):
                        room.next_justification_speaker()
                    else:
                        raise ValueError("Сейчас не ваше слово для оправдания!")

                elif action == "GRANT_DEBATE_SPEAKER" and is_host:
                    target_id = payload.get("target_player_id") or payload.get("target_id")
                    if target_id:
                        if room.phase == PHASE_REVEAL:
                            raise ValueError("Во время открытия используется очередь участников. Завершите текущий ход кнопкой «Далее».")
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
                    await websocket.send_text(json.dumps({"type":"ACTION_OK","action":"CAST_VOTE","target_id":target_id,"phase":room.phase,"round_number":room.round_number}))

                elif action == "CONFIRM_ELIMINATION" and is_host:
                    target_id = payload.get("target_id")
                    room.confirm_elimination(target_id)

                elif action == "USE_SPECIAL_CARD":
                    target_player_id = payload.get("target_player_id")
                    room.validate_turn_command(payload.get('expected_turn_id'))
                    room.use_special_card(player_id, target_player_id, category=payload.get("category"), categories=payload.get("categories"), option_text=payload.get('option_text'))
                    await websocket.send_text(json.dumps({"type": "ACTION_OK", "action": "USE_SPECIAL_CARD"}))

                elif action == 'SPEECH_PROMPT':
                    room.send_speech_prompt(player_id, payload.get('target_id'), payload.get('effect_id'), payload.get('index'), payload.get('word'))
                    await websocket.send_json({'type': 'ACTION_OK', 'action': 'SPEECH_PROMPT'})

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
                    if room.phase == PHASE_LOBBY:
                        room.update_lobby_settings(player_id, {'capacity_mode': 'manual', 'capacity': new_capacity, 'preset': 'custom'})
                    else:
                        room.host_adjust_capacity(new_capacity)

                elif action == "HOST_TOGGLE_TRAITOR" and is_host:
                    enabled = payload.get('enable_traitor', not room.enable_traitor)
                    if room.phase == PHASE_LOBBY:
                        room.update_lobby_settings(player_id, {'enable_traitor': enabled, 'preset': 'custom'})
                    else:
                        room.enable_traitor = enabled

                elif action == "HOST_KICK" and is_host:
                    kick_id = payload.get("player_id")
                    if kick_id == room.host_id:
                        raise ValueError('Ведущий не может удалить себя.')
                    if kick_id not in room.players:
                        raise ValueError('Участник уже покинул комнату.')
                    if kick_id:
                        room.remove_player(kick_id)
                        if room_code in connections and kick_id in connections[room_code]:
                            kick_ws = connections[room_code].pop(kick_id, None)
                            if kick_ws:
                                try:
                                    await kick_ws.close(code=4004, reason="Kicked by host")
                                except Exception:
                                    pass
                    await websocket.send_json({'type': 'ACTION_OK', 'action': action, 'player_id': kick_id})

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
                    if room.phase == PHASE_LOBBY:
                        room.update_lobby_settings(player_id, {'enable_events': enabled, 'preset': 'custom'})
                    else:
                        room.host_toggle_events(enabled)

                elif action == "HOST_TRIGGER_EVENT" and is_host:
                    room.host_trigger_event()

                elif action == "SKIP_SORTIE" and is_host:
                    skip = payload.get("skip", True)
                    room.skip_sortie(skip)

                elif action == "CLAIM_HOST":
                    if room.host_id != player_id and room.host_id in connections.get(room_code, {}):
                        raise ValueError('Ведущий уже подключён к комнате.')
                    if player_id not in room.players:
                        room.can_join_lobby()
                    new_name = payload.get("name")
                    room.transfer_host(player_id, new_name)

                elif action == "JOIN_LOBBY":
                    if player_id not in room.players:
                        room.can_join_lobby()
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
                    "action": action,
                    "message": str(ve)
                }))
                if room.phase == PHASE_LOBBY:
                    await broadcast_room_state(room_code)

    except WebSocketDisconnect:
        if connections.get(room_code, {}).get(player_id) is websocket:
            del connections[room_code][player_id]
            if player_id in room.players:
                room.players[player_id].connected = False
                room.lobby_ready.discard(player_id)
            await broadcast_room_state(room_code)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if connections.get(room_code, {}).get(player_id) is websocket:
            del connections[room_code][player_id]
            if player_id in room.players:
                room.players[player_id].connected = False
                room.lobby_ready.discard(player_id)
            await broadcast_room_state(room_code)
