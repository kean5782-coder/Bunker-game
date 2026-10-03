#!/usr/bin/env python3
"""V4.4: actual bundled UI and real engine using explicit in-process transport.

Chromium localhost navigation is restricted in the build environment. This
harness does not alter browser policy. HTTP/WebSocket behavior is independently
covered by tests_balance/test_information_modes_v4_4.py using ASGI TestClient.
"""
from __future__ import annotations
import argparse
import copy
import json
import random
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import verify_visual as visual
import verify_lobby_ui as lobby_ui
from server import deck_data
from server.balance import normalize_event
from server.game_engine import BunkerGameRoom
from playwright.sync_api import sync_playwright

CHECKS, LAYOUTS = [], []

def check(ok, label):
    if not ok:
        raise AssertionError(label)
    CHECKS.append(label)


def new_room(mode='immersion'):
    random.seed(444)
    r = BunkerGameRoom('IM44', 'p0', 'Алекс')
    for i, name in enumerate(visual.NAMES[1:8], 1):
        r.add_player(f'p{i}', name)
    r.update_lobby_settings('p0', {'information_mode': mode, 'show_prologue': False})
    return r


def bind(r):
    def command(raw, viewer):
        msg = json.loads(raw)
        a, p = msg['action'], msg.get('payload', {})
        try:
            if a == 'UPDATE_LOBBY_SETTINGS':
                r.update_lobby_settings(viewer, p['settings'], p.get('expected_revision'))
            elif a == 'START_GAME':
                r.start_configured_game(viewer, p.get('expected_revision'))
                r.host_pause_timer(True)
            elif a == 'ASSIGN_VOLUNTEER':
                r.assign_volunteer(p.get('volunteer_id'))
            elif a == 'SKIP_SORTIE':
                r.skip_sortie(p.get('skip', True))
            elif a == 'RESOLVE_EVENT':
                r.resolve_active_event()
            else:
                raise ValueError('Unsupported test binding action: ' + a)
            return {'ack': {'action': a, 'revision': r.lobby_revision}, 'state': r.get_state(viewer)}
        except Exception as exc:
            return {'action': a, 'error': str(exc), 'state': r.get_state(viewer)}
    return command


def measure(p, label, lobby=False):
    x = p.evaluate('''() => ({viewport:[innerWidth,innerHeight],document:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],settings:document.getElementById('lcSettingsScroll')?{scroll:document.getElementById('lcSettingsScroll').scrollHeight,client:document.getElementById('lcSettingsScroll').clientHeight}:null})''')
    x['label'] = label
    LAYOUTS.append(x)
    check(x['document'][0] <= x['viewport'][0]+1, label+': no horizontal overflow')
    if lobby and x['viewport'][0] >= 1200:
        check(x['settings']['scroll'] <= x['settings']['client']+1, label+': primary lobby settings fit without scrolling')


def assert_narrative(text, label):
    forbidden = ['d100', 'Базовый шанс', 'Численный', 'численного бонуса', 'бросок:', 'Для успеха нужно', 'п.п.', 'баллов', 'Рейтинг устойчивости']
    check(not any(t in text for t in forbidden), label+': no numeric mechanics or individual rankings')


def run(browser, out):
    p = lobby_ui.boot(browser)
    r = new_room()
    p.expose_function('engineCommand', bind(r))
    lobby_ui.apply(p, r, 'p0')
    check(p.locator('#lc-information_mode').input_value() == 'immersion', 'Default: immersion')
    check(p.locator('#lc-information_mode option').count() == 2, 'Exactly two selectable information modes')
    for w,h in [(1366,768),(1280,720),(1920,1080),(390,844)]:
        p.set_viewport_size({'width':w,'height':h}); p.wait_for_timeout(80)
        measure(p, f'lobby {w}x{h}', lobby=True)
        p.screenshot(path=str(out/f'lobby_{w}x{h}.png'))
    p.set_viewport_size({'width':1366,'height':768})
    lobby_ui.setting(p, 'information_mode', 'uncertainty')
    check('Шансы скрыты' in p.locator('#lcInformationHelp').inner_text(), 'Host selector updates mode explanation')
    p.locator('[data-preset="blitz"]').click(); lobby_ui.saved(p)
    check(r.lobby_settings['information_mode'] == 'uncertainty', 'Preset selection preserves chosen information mode')
    p.locator('[data-preset="classic"]').click(); lobby_ui.saved(p)
    check(r.lobby_settings['information_mode'] == 'uncertainty', 'Returning to classic preserves information mode')
    # The profile file contains the setting and import passes through host validation.
    with p.expect_download() as dl:
        p.locator('#lcSaveProfile').click()
    profile_file = out/'settings_profile.json'
    dl.value.save_as(profile_file)
    profile = json.loads(profile_file.read_text())
    check(profile['settings']['information_mode'] == 'uncertainty', 'Saved JSON profile contains mode')
    lobby_ui.setting(p, 'information_mode', 'immersion')
    p.locator('#lcProfileFile').set_input_files(str(profile_file))
    p.wait_for_function('state.gameData.lobby.settings.information_mode==="uncertainty"'); lobby_ui.saved(p)
    check(r.lobby_settings['information_mode'] == 'uncertainty', 'Import restores mode through actual file input')
    lobby_ui.apply(p, r, 'p1')
    check(p.locator('#lc-information_mode').is_disabled(), 'Guests cannot edit mode')
    check(p.locator('#lc-information_mode').input_value() == 'uncertainty', 'Guest sees common selected mode')
    p.screenshot(path=str(out/'lobby_guest.png'))
    lobby_ui.apply(p, r, 'p0')
    p.locator('#lcStart').click()
    p.wait_for_function('state.gameData.phase!=="LOBBY"')
    check(r.match_settings['information_mode']=='uncertainty', 'Actual Start button freezes confirmed mode')
    p.close()

    for mode in ['immersion','uncertainty']:
        p=visual.boot(browser,1366,768,out)
        r=new_room(mode); r.start_configured_game('p0',r.lobby_revision)
        r.start_speech_phase(); r.host_grant_speech_speaker('p0'); r.host_pause_timer(True)
        r.active_event=normalize_event(next(e for e in deck_data.BUNKER_EVENTS if e['type']=='SURFACE_EVENT'))
        r.assigned_volunteer_id='p1'; r.recalculate_event_odds()
        visual.apply(p,r.get_state('p0'))
        text=p.locator('#eventChallengeSection').inner_text()
        assert_narrative(text,mode+' event')
        if mode=='immersion':
            check(any(label in text for label in ['Низкий шанс','Средний шанс','Высокий шанс']), 'Immersion: server qualitative chance visible')
        else:
            check(not any(label in text for label in ['Низкий шанс','Средний шанс','Высокий шанс']), 'Uncertainty: no qualitative odds')
            check(r.get_state('p0')['events_state']['current_odds'] is None, 'Uncertainty: odds not sent in state')
        check(p.locator('#eventChallengeSection .event-meter').count()==0,mode+': no exact chance bar')
        check('Ирина' in text,mode+': assigned volunteer remains visible')
        p.expose_function('engineCommand', bind(r))
        lobby_ui.apply(p, r, 'p0'); p.evaluate('window.holdTransport=false')
        p.locator('#selectEventVolunteer').select_option('p2')
        p.wait_for_function('state.gameData.events_state.volunteer_id==="p2" || state.gameData.events_state.assigned_volunteer_id==="p2"')
        check(r.assigned_volunteer_id=='p2',mode+': volunteer control updates engine')
        p.locator('[data-event-action="skip"]').click()
        p.wait_for_function('state.gameData.events_state.is_sortie_skipped')
        check('Вылазка отменена' in p.locator('#eventChallengeSection').inner_text(),mode+': canceled sortie explicit')
        p.locator('[data-event-action="skip"]').click()
        p.wait_for_function('!state.gameData.events_state.is_sortie_skipped')
        check(not r.is_sortie_skipped,mode+': sortie can be resumed')
        measure(p,mode+' event 1366x768')
        p.screenshot(path=str(out/f'{mode}_event.png'))
        # Card UI and in-game journal use public data; foreign secrets stay masked.
        p.locator('[data-open-card="gender"]').click()
        check(p.locator('#modalPlayerDossier').is_visible(),mode+': own dossier opens')
        assert_narrative(p.locator('#modalPlayerDossier').inner_text(),mode+' dossier')
        p.keyboard.press('Escape')
        r.resolve_active_event(force_roll=100)
        visual.apply(p,r.get_state('p0'))
        check(p.locator('#resultReviewModal').is_visible(),mode+': result opens automatically')
        check(r.get_state('p0')['result_review']['seconds_left']==5,mode+': five-second review preserved')
        assert_narrative(p.locator('#resultReviewContent').inner_text(),mode+' outcome')
        check(p.locator('#resultReviewNext').inner_text().strip(),mode+': next phase remains visible')
        p.screenshot(path=str(out/f'{mode}_result.png'))
        before=r.timer_seconds_left
        for _ in range(5): r.tick_result_review()
        visual.apply(p,r.get_state('p0'))
        check(not p.locator('#resultReviewModal').is_visible(),mode+': review closes after five server ticks')
        check(r.timer_seconds_left==before,mode+': review did not consume speech timer')
        p.evaluate('openEventHistoryModal()')
        assert_narrative(p.locator('#modalEventHistory').inner_text(),mode+' history')
        p.keyboard.press('Escape')
        r.trigger_final(); visual.apply(p,r.get_state('p0'))
        check(p.locator('#finalScreenSection').is_visible(),mode+': narrative final renders')
        assert_narrative(p.locator('#finalScreenSection').inner_text(),mode+' final')
        p.screenshot(path=str(out/f'{mode}_final.png'))
        p.close()
    check(not visual.ERRORS and not lobby_ui.ERRORS,'No JavaScript exceptions')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--chromium',default='/usr/bin/chromium');parser.add_argument('--output',default=str(ROOT/'information_v4_4/ui'))
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    failure=None
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
            try: run(browser,out)
            finally: browser.close()
    except Exception as exc:
        traceback.print_exc();failure=f'{type(exc).__name__}: {exc}'
    report={'passed':failure is None,'mode':'Real bundled Chromium UI + explicit in-process engine binding; network tested separately using ASGI WebSockets','checks_passed':len(CHECKS),'checks':CHECKS,'layouts':LAYOUTS,'page_errors':visual.ERRORS+lobby_ui.ERRORS,'failure':failure}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if failure: raise SystemExit(1)

if __name__=='__main__':main()
