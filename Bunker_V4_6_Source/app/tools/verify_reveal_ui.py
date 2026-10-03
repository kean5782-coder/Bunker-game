#!/usr/bin/env python3
"""Chromium checks of Reveal V3 using real assets/engine, with explicit offline transport.
The companion verify_reveal_network.py uses actual loopback HTTP/WebSockets.
"""
from __future__ import annotations
import argparse
import copy
import json
import random
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.game_engine import BunkerGameRoom
import verify_visual as visual

OUT = ROOT / 'reveal_results'
CHECKS = []
ERRORS = []


def check(value, text):
    if not value:
        raise AssertionError(text)
    CHECKS.append(text)


def room(count=6, duration=90):
    r = BunkerGameRoom('RVL3', 'p0', 'Алекс')
    names = ['Ирина', 'Максим', 'Дарья', 'Сергей', 'Никита', 'Анна', 'Денис']
    for i in range(1, count):
        r.add_player(f'p{i}', names[(i-1) % len(names)])
    r.start_game(capacity=count//2, enable_events=True, speech_duration=duration)
    return r


def command_for(r, viewer):
    def command(raw):
        message = json.loads(raw)
        action, payload = message['action'], message.get('payload', {})
        try:
            r.validate_turn_command(payload.get('expected_turn_id'))
            if action == 'REVEAL_CARD':
                r.reveal_player_card(viewer, payload['category'])
            elif action in ('NEXT_REVEAL', 'NEXT_SPEAKER'):
                current = r.get_current_speaker()
                if viewer != r.host_id and (not current or current.id != viewer):
                    raise ValueError('Not this player’s turn')
                if action == 'NEXT_REVEAL':
                    r.next_reveal_player(force=viewer == r.host_id)
                else:
                    r.next_speaker(force=viewer == r.host_id)
            else:
                raise ValueError(action)
            return {'state': r.get_state(viewer), 'ack': {'action': action}}
        except Exception as exc:
            return {'error': str(exc)}
    return command


def run(browser):
    p = visual.boot(browser, 1366, 768, OUT)
    p.on('pageerror', lambda e: ERRORS.append(str(e)))
    r = room(6)
    visual.apply(p, r.get_state('p0'))
    check(p.locator('#phaseTitle').inner_text() == 'Открытие карточек', 'Separate reveal phase title')
    check(p.locator('#timerDigits').inner_text() == '1:00', 'Reveal shows 60s even with a 90s first speech')
    check(p.locator('.dash-step.current').inner_text() == 'Открытие', 'Phase rail highlights opening before Speech 1')
    check(p.locator('#speakerProgress').inner_text() == 'ОТКРЫТИЕ · 1 из 6', 'Reveal turn counter is visible')
    check(p.locator('[data-reveal]').count() == 1, 'Only required profession reveal initially available')
    check('ОТКРЫВАЕТ' in p.locator('.dash-focus-header').inner_text(), 'Active dossier says opening, not speaking')
    check('60 секунд' in p.locator('#dashTurnHelp').inner_text(), 'Instructions explain reveal time and subsequent full circle')
    p.screenshot(path=str(OUT/'reveal_1366x768.png'))
    # A non-active guest cannot reveal or skip someone else's opening.
    visual.apply(p, r.get_state('p1'), 'p1')
    check(p.locator('[data-reveal]').count() == 0, 'Waiting guest cannot reveal')
    check(not p.locator('#btnNextSpeaker').is_visible(), 'Waiting guest cannot end someone else’s turn')
    r.next_reveal_player(force=True)
    visual.apply(p, r.get_state('p1'), 'p1')
    p.expose_function('engineCommand', command_for(r, 'p1'))
    p.evaluate('window.holdTransport=false')
    check(p.locator('#btnNextSpeaker').is_disabled(), 'Guest cannot end before completing quota')
    p.locator('[data-reveal="profession"]').click()
    p.wait_for_function('state.gameData.reveal_status.revealed_count===1')
    for target, total in [('health', 2), ('hobby', 3)]:
        p.locator(f'[data-reveal="{target}"]').click()
        p.wait_for_function('(n)=>state.gameData.reveal_status.revealed_count===n', arg=total)
    check(not p.locator('#btnNextSpeaker').is_disabled(), 'Complete quota enables explicit end-opening button')
    check(p.locator('[data-reveal]').count() == 0, 'No extra reveal after quota')
    check(r.phase == 'REVEAL' and r.get_current_speaker().id == 'p1', 'Quota completion does not automatically consume remaining time')
    p.locator('#btnNextSpeaker').click()
    p.wait_for_function("state.gameData.current_speaker.id==='p2'")
    check(r.phase == 'REVEAL', 'End-opening moves to next opening, not Speech 1')
    check(p.evaluate("window.sentCommands.some(c=>c.action==='NEXT_REVEAL'&&Number.isInteger(c.payload.expected_turn_id))"), 'Client sends explicit phase-scoped command with stale-turn token')
    while r.phase == 'REVEAL':
        r.next_reveal_player(force=True)
    visual.apply(p, r.get_state('p1'), 'p1')
    check(p.locator('#timerDigits').inner_text() == '1:30', 'All finished: first speech gets full independent configured timer')
    check(p.locator('.dash-step.current').inner_text() == 'Речь 1', 'Speech phase rail updates')
    check(p.locator('[data-reveal]').count() == 0, 'First speech has no ordinary reveal buttons')
    r.next_speaker()
    visual.apply(p, r.get_state('p1'), 'p1')
    check(not p.locator('#btnNextSpeaker').is_disabled(), 'Speech can end without any new reveal quota')
    check('Завершить речь' in p.locator('#btnNextSpeaker').inner_text(), 'Speech button no longer says opening')
    before = copy.deepcopy(r.players['p1'].cards)
    p.locator('#btnNextSpeaker').click()
    p.wait_for_function("state.gameData.current_speaker.id==='p2'")
    check(before == r.players['p1'].cards, 'Speech end never opens extra cards')
    p.screenshot(path=str(OUT/'speech1_1366x768.png'))
    while r.phase == 'SPEECH':
        r.next_speaker()
    visual.apply(p, r.get_state('p1'), 'p1')
    check(p.locator('#timerDigits').inner_text() == '0:45', 'Second speech remains half of the configured first')
    check(p.locator('.dash-step.current').inner_text() == 'Речь 2', 'Second speech stage unchanged')
    p.close()
    for width, height in [(1366,768),(1440,900),(1280,720),(390,844)]:
        p = visual.boot(browser, width, height, OUT)
        p.on('pageerror', lambda e: ERRORS.append(str(e)))
        r = room(8)
        visual.apply(p, r.get_state('p0'))
        geom = visual.layout(p, f'reveal {width}x{height}')
        check(geom['bodyWidth'] <= width + 1, f'{width}: no horizontal page overflow')
        check(p.locator('#timerDigits').is_visible(), f'{width}: reveal timer visible')
        check(p.locator('[data-reveal="profession"]').is_visible(), f'{width}: active player can access own reveal')
        if width >= 1100:
            b = geom['boxes']['myCardsList']
            check(b['scroll'] <= b['client'] + 1, f'{width}: eleven positions fit vertically')
            box = p.locator('#btnNextSpeaker').bounding_box()
            check(box and box['y']+box['height'] <= height, f'{width}: end-opening action stays on screen')
        else:
            p.locator('[data-mobile-tab="actions"]').click()
            check(p.locator('#btnNextSpeaker').is_visible(), 'Mobile action tab contains end-opening control')
        p.screenshot(path=str(OUT/f'reveal_{width}x{height}.png'))
        # Reconnect state keeps same phase/time/quota and restores own actionable UI.
        r.reveal_player_card('p0', 'profession')
        r.timer_seconds_left = 24
        visual.apply(p, r.get_state('p0'))
        check(p.locator('#timerDigits').inner_text() == '0:24', f'{width}: refresh/reconnect snapshot preserves remaining time')
        r.phase = 'LOBBY'
        visual.apply(p, r.get_state('p0'))
        p.locator('#lc-tab-rules').click()
        if width >= 1100:
            check('60 сек каждому' in p.locator('#lcRevealTiming').inner_text(), f'{width}: lobby explains fixed independent reveal duration')
            p.screenshot(path=str(OUT/f'lobby_timing_{width}x{height}.png'))
        p.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--chromium', default='/usr/bin/chromium')
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    failure = None
    random.seed(20611)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.chromium, headless=True, args=['--no-sandbox'])
            try:
                run(browser)
                check(not ERRORS and not visual.ERRORS, 'No JavaScript exceptions')
            finally:
                browser.close()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        failure = f'{type(exc).__name__}: {exc}'
    report = {'passed': failure is None, 'checks_passed': len(CHECKS), 'checks': CHECKS,
              'javascript_errors': ERRORS + visual.ERRORS, 'failure': failure,
              'transport': 'Real bundled assets and engine; offline Python binding in place of browser WebSocket.'}
    (OUT/'reveal_ui.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failure:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
