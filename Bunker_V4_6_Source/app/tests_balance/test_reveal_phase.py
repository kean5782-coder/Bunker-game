"""Reveal V3: a full 60-second opening circle precedes both speech circles."""
import asyncio
import copy
import json
import random
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from server.game_engine import BunkerGameRoom, get_reveal_quota
from server.bot_turns import plan_turn
from server.bot_client import CARD_CATEGORIES, BunkerBot
from server.bot_agent import CARD_PRIORITY
from server import app as api
from server import special_cards


def make_room(count=4, duration=60, **kwargs):
    room = BunkerGameRoom('RVL3', 'p0', 'Ведущий')
    for i in range(1, count):
        room.add_player(f'p{i}', f'Игрок {i}')
    room.start_game(capacity=max(1, count // 2), speech_duration=duration,
                    enable_events=False, **kwargs)
    return room


def opened(player):
    return {cat for cat, card in player.cards.items()
            if cat not in ('special', 'traitor') and card.get('revealed')}


def reveal_all(room):
    while room.phase == 'REVEAL':
        room.next_reveal_player(force=True)


def complete_turn(room):
    player = room.get_current_speaker()
    while not room.can_speaker_proceed():
        cmd = plan_turn(room.get_state(player.id), player.id, CARD_CATEGORIES)
        assert cmd['action'] == 'REVEAL_CARD'
        room.reveal_player_card(player.id, cmd['payload']['category'])
    room.next_reveal_player()


@pytest.mark.parametrize('count', [3, 4, 6, 8, 12, 20])
@pytest.mark.parametrize('duration', [30, 60, 90, 180])
def test_everyone_reveals_then_everyone_speaks_then_half_speeches(count, duration):
    room = make_room(count, duration)
    order = list(room.speakers_order)
    assert room.get_state('p0')['timers_config']['reveal'] == 60
    for index, pid in enumerate(order):
        assert room.phase == 'REVEAL'
        assert room.get_current_speaker().id == pid
        assert room.timer_seconds_left == 60
        complete_turn(room)
        if index < count - 1:
            assert room.phase == 'REVEAL'
    before = {pid: copy.deepcopy(p.cards) for pid, p in room.players.items()}
    for pid in order:
        assert room.phase == 'SPEECH'
        assert room.get_current_speaker().id == pid
        assert room.timer_seconds_left == duration
        assert room.get_state(pid)['speech_status']['can_proceed']
        room.next_speaker()
    assert before == {pid: p.cards for pid, p in room.players.items()}
    for pid in order:
        assert room.phase == 'ACCUSATION'
        assert room.get_current_accusation_speaker().id == pid
        assert room.timer_seconds_left == duration // 2
        room.next_accusation_speaker()
    assert room.phase == 'VOTING'


def test_exact_sixty_ticks_and_timeout_auto_reveal_without_speech_reveal():
    room = make_room()
    first = room.get_current_speaker()
    token = room.turn_id
    for _ in range(59):
        assert not room.tick_timer()
        assert room.phase == 'REVEAL' and room.get_current_speaker() is first
    assert not opened(first)
    assert room.timer_seconds_left == 1
    assert room.tick_timer()
    assert room.phase == 'REVEAL' and room.get_current_speaker() is not first
    assert 'profession' in opened(first) and len(opened(first)) == 3
    assert room.timer_seconds_left == 60 and room.turn_id != token
    reveal_all(room)
    before = copy.deepcopy(room.players['p0'].cards)
    for _ in range(60):
        room.tick_timer()
    assert before == room.players['p0'].cards
    assert room.phase == 'SPEECH' and room.get_current_speaker().id == 'p1'


def test_quota_profession_first_no_extra_reveal_and_no_early_finish():
    room = make_room()
    with pytest.raises(ValueError):
        room.reveal_player_card('p0', 'health')
    with pytest.raises(ValueError):
        room.reveal_player_card('p1', 'profession')
    with pytest.raises(ValueError):
        room.next_reveal_player()
    for cat in ('profession', 'health', 'hobby'):
        room.reveal_player_card('p0', cat)
    with pytest.raises(ValueError):
        room.reveal_player_card('p0', 'fact')
    assert room.get_state('p0')['reveal_status']['quota_reached']
    assert room.phase == 'REVEAL' and room.get_current_speaker().id == 'p0'
    room.next_reveal_player()
    assert room.get_state('p1')['reveal_status']['revealed_count'] == 0


@pytest.mark.parametrize('phase', ['SPEECH', 'ACCUSATION', 'VOTING', 'REVOTE', 'LOBBY', 'PROLOGUE', 'FINAL'])
def test_ordinary_reveal_not_allowed_in_other_phases(phase):
    room = make_room()
    room.phase = phase
    before = copy.deepcopy(room.players['p0'].cards)
    with pytest.raises(ValueError):
        room.reveal_player_card('p0', 'profession')
    assert room.players['p0'].cards == before


def test_pause_restart_and_resume_preserve_opened_and_do_not_consume_speech_time():
    room = make_room(duration=90)
    room.reveal_player_card('p0', 'profession')
    room.timer_seconds_left = 12
    room.host_pause_timer(True)
    assert not room.tick_timer() and room.timer_seconds_left == 12
    room.host_restart_phase()
    assert room.timer_seconds_left == 60 and not room.timer_is_paused
    assert room.get_state('p0')['reveal_status']['revealed_count'] == 1
    reveal_all(room)
    assert room.phase == 'SPEECH' and room.timer_seconds_left == 90


@pytest.mark.parametrize('mode', ['closed', 'profession', 'profession_health'])
def test_initial_public_cards_not_reopened(mode):
    room = make_room(lobby_options={'initial_reveal': mode})
    p = room.get_current_speaker()
    before = opened(p)
    required = room.get_state(p.id)['reveal_status']['required_count']
    complete_turn(room)
    assert len(opened(p) - before) == required
    assert before.issubset(opened(p))


def test_no_hidden_cards_can_finish_without_deadlock_and_special_never_auto_opens():
    room = make_room(enable_traitor=True)
    for player in room.players.values():
        for cat, card in player.cards.items():
            if cat not in ('traitor', 'special'):
                card['revealed'] = True
    for _ in room.players:
        assert room.get_state('p0')['reveal_status']['required_count'] == 0
        room.next_reveal_player()
    assert room.phase == 'SPEECH'
    assert all(not p.cards['special'].get('revealed') for p in room.players.values())


def test_last_word_starts_fresh_reveal_circle_in_reverse_order():
    room = make_room(6)
    reveal_all(room)
    room.phase = 'VOTE_RESULTS'
    room.vote_results = {'eliminated_id': 'p5', 'eliminated_ids': ['p5']}
    room.confirm_elimination()
    room.finish_last_word()
    assert room.phase == 'REVEAL' and room.round_number == 2
    assert room.speakers_order == ['p4', 'p3', 'p2', 'p1', 'p0']
    assert room.get_state('p4')['reveal_status']['revealed_count'] == 0
    reveal_all(room)
    assert room.phase == 'SPEECH' and room.get_current_speaker().id == 'p4'


def give(room, pid, cid):
    room.players[pid].cards['special'] = {'card_id': cid, 'used': False, 'revealed': False}


@pytest.mark.parametrize('effect', ['silence_speech', 'silence_player'])
def test_silence_does_not_remove_reveal_right(effect):
    room = make_room()
    give(room, 'p1', effect)
    room.use_special_card('p1', 'p0')
    assert room.phase == 'REVEAL' and room.get_current_speaker().id == 'p0'
    room.reveal_player_card('p0', 'profession')
    reveal_all(room)
    assert room.get_current_speaker().id == ('p1' if effect == 'silence_speech' else 'p0')
    room.start_accusation_phase()
    assert room.get_current_accusation_speaker().id == 'p1'


def test_quarantine_skips_opening_without_forced_reveal():
    room = make_room()
    give(room, 'p1', 'quarantine_lock')
    room.use_special_card('p1', 'p0')
    assert room.get_current_speaker().id == 'p1'
    assert not opened(room.players['p0'])
    reveal_all(room)
    assert room.get_current_speaker().id == 'p1'


def test_disconnected_player_retains_turn_then_auto_reveals():
    room = make_room()
    room.players['p1'].connected = False
    room.next_reveal_player(force=True)
    assert room.get_current_speaker().id == 'p1'
    room.timer_seconds_left = 1
    room.tick_timer()
    assert len(opened(room.players['p1'])) == 3
    assert room.phase == 'REVEAL' and room.get_current_speaker().id == 'p2'


def test_revisit_reveal_does_not_grant_second_quota():
    room = make_room()
    complete_turn(room)
    before = opened(room.players['p0'])
    room.host_set_phase('REVEAL')
    assert room.get_state('p0')['reveal_status']['revealed_count'] == 3
    with pytest.raises(ValueError):
        room.reveal_player_card('p0', 'fact')
    room.next_reveal_player()
    assert opened(room.players['p0']) == before


def test_private_state_and_reconnect_do_not_reset_timer():
    room = make_room(enable_traitor=True)
    room.reveal_player_card('p0', 'profession')
    room.timer_seconds_left = 29
    room.add_player('p0', 'Ведущий')
    for viewer in ('p0', 'p1', None, 'spectator'):
        state = room.get_state(viewer)
        json.dumps(state)
        assert state['phase'] == 'REVEAL' and state['timer']['seconds_left'] == 29
        assert state['reveal_status']['revealed_count'] == 1
        for player in state['players']:
            if player['id'] != viewer:
                assert 'traitor' not in player['cards']
                assert not player['cards']['health']['revealed']
                assert player['cards']['health']['value'] == '🔒 Скрыто'


@pytest.mark.parametrize('priority', [CARD_CATEGORIES, CARD_PRIORITY])
def test_both_bot_planners_complete_all_cards_across_rounds(priority):
    room = make_room()
    for round_number in range(1, 7):
        room.round_number = round_number
        room.start_round()
        guard = 0
        while room.phase == 'REVEAL':
            guard += 1
            assert guard < 80
            pid = room.get_current_speaker().id
            cmd = plan_turn(room.get_state(pid), pid, priority)
            assert cmd
            room.validate_turn_command(cmd['payload']['expected_turn_id'])
            if cmd['action'] == 'REVEAL_CARD':
                room.reveal_player_card(pid, cmd['payload']['category'])
            else:
                assert cmd['action'] == 'NEXT_REVEAL'
                room.next_reveal_player()
        before = {pid: opened(p) for pid, p in room.players.items()}
        while room.phase == 'SPEECH':
            pid = room.get_current_speaker().id
            cmd = plan_turn(room.get_state(pid), pid, priority)
            assert cmd['action'] == 'NEXT_SPEAKER'
            room.next_speaker()
        assert before == {pid: opened(p) for pid, p in room.players.items()}


def test_concurrent_bot_updates_do_not_send_multiple_commands(monkeypatch):
    import server.bot_client as module
    room = make_room()
    bot = BunkerBot('test', 'RVL3', 'http://localhost')
    bot.player_id = 'p0'
    state = room.get_state('p0')
    bot.latest_state = state
    sent = []
    async def send(action, payload): sent.append((action, payload))
    async def no_sleep(_): return None
    monkeypatch.setattr(bot, 'send_action', send)
    monkeypatch.setattr(module.asyncio, 'sleep', no_sleep)
    async def scenario():
        await asyncio.gather(*(bot.handle_game_state(copy.deepcopy(state)) for _ in range(5)))
    asyncio.run(scenario())
    assert len(sent) == 1 and sent[0][0] == 'REVEAL_CARD'


@pytest.mark.parametrize('count', [3, 4, 6, 8, 12, 20])
@pytest.mark.parametrize('seed', [731, 912])
def test_accelerated_full_games_terminate_with_new_phase_every_round(count, seed):
    random.seed(seed)
    room = make_room(count)
    phases = []
    for _ in range(3000):
        if room.phase == 'FINAL':
            break
        phases.append((room.round_number, room.phase))
        # Accelerated server ticks; dedicated tests above exercise the exact 60 ticks.
        room.timer_seconds_left = 1
        room.tick_timer()
    assert room.phase == 'FINAL'
    assert len(room.get_alive_players()) <= room.bunker_capacity
    for rnd in set(r for r, _ in phases):
        sequence = [p for r, p in phases if r == rnd]
        assert sequence[0] == 'REVEAL'
        assert sequence.index('REVEAL') < sequence.index('SPEECH') < sequence.index('ACCUSATION')


def receive(ws, kind):
    for _ in range(60):
        message = ws.receive_json()
        if message.get('type') == kind:
            return message
    raise AssertionError('Missing ' + kind)


def test_websocket_permissions_stale_commands_and_no_reveal_during_speech(monkeypatch):
    monkeypatch.setattr(api, 'get_external_ip', lambda: None)
    monkeypatch.setattr(api, 'get_local_ip', lambda: '127.0.0.1')
    room = make_room(3)
    room.host_pause_timer(True)
    api.rooms[room.room_code] = room
    try:
        with TestClient(api.app) as client, ExitStack() as stack:
            sockets = {pid: stack.enter_context(client.websocket_connect(f'/ws/{room.room_code}/{pid}'))
                       for pid in ('p0', 'p1', 'p2')}
            host, guest = sockets['p0'], sockets['p1']
            receive(guest, 'STATE_UPDATE')
            guest.send_json({'action': 'REVEAL_CARD', 'payload': {'category': 'profession'}})
            assert receive(guest, 'ERROR')['action'] == 'REVEAL_CARD'
            guest.send_json({'action': 'NEXT_REVEAL', 'payload': {}})
            assert receive(guest, 'ERROR')['action'] == 'NEXT_REVEAL'
            stale = room.turn_id
            host.send_json({'action': 'NEXT_REVEAL', 'payload': {'expected_turn_id': stale}})
            while receive(host, 'STATE_UPDATE')['state']['turn_id'] == stale:
                pass
            after = room.turn_id
            host.send_json({'action': 'NEXT_REVEAL', 'payload': {'expected_turn_id': stale}})
            assert receive(host, 'ERROR')['action'] == 'NEXT_REVEAL'
            assert room.turn_id == after and room.get_current_speaker().id == 'p1'
            reveal_all(room)
            before = copy.deepcopy(room.players['p0'].cards)
            host.send_json({'action': 'REVEAL_CARD', 'payload': {'category': 'fact'}})
            receive(host, 'ERROR')
            assert room.players['p0'].cards == before
            host.send_json({'action': 'NEXT_REVEAL', 'payload': {}})
            receive(host, 'ERROR')
            assert room.phase == 'SPEECH' and room.get_current_speaker().id == 'p0'
    finally:
        api.rooms.pop(room.room_code, None)
        api.connections.pop(room.room_code, None)
