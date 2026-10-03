#!/usr/bin/env python3
"""Follow/pinned dossier regressions on real DOM + engine snapshots.
Transport is an explicit offline fixture; use verify_autofollow_network.py
for genuine multi-browser HTTP/WebSocket coverage.
"""
from __future__ import annotations
import argparse
import copy
import json
import random
from pathlib import Path
from playwright.sync_api import sync_playwright
import verify_visual as visual

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[str] = []


def check(ok: bool, name: str) -> None:
    if not ok:
        raise AssertionError(name)
    CHECKS.append(name)


def name(page) -> str:
    return page.locator('.dash-focus-header h2').inner_text()


def auto(page) -> bool:
    return page.locator('#dashFindSpeaker').get_attribute('data-follow-mode') == 'auto'


def select(page, pid: str) -> None:
    page.locator(f'#dashRoster [data-player="{pid}"]').click()


def run(browser, out: Path) -> None:
    p = visual.boot(browser, 1366, 768, out)
    r = visual.room(6)
    r.start_reveal_phase()
    g = r.get_state('p0')
    visual.apply(p, g)
    check(auto(p) and name(p) == 'Алекс', 'Opening starts in auto mode')
    select(p, 'p4')
    check(not auto(p) and name(p) == 'Сергей', 'Non-active roster selection pins the dossier')
    p.screenshot(path=str(out/'manual_1366x768.png'))
    for remaining in (59, 54, 33, 12):
        tick = copy.deepcopy(g)
        tick['timer']['seconds_left'] = remaining
        visual.apply(p, tick)
        check(not auto(p) and name(p) == 'Сергей', f'Manual selection survives timer update {remaining}s')
    r.next_reveal_player(force=True)
    visual.apply(p, r.get_state('p0'))
    check(not auto(p) and name(p) == 'Сергей', 'Manual selection survives next active player')
    p.locator('#dashFindSpeaker').click()
    check(auto(p) and name(p) == 'Ирина', 'Resume button immediately returns to current opening player')
    for expected in ('Максим', 'Дарья', 'Сергей', 'Никита'):
        r.next_reveal_player(force=True)
        visual.apply(p, r.get_state('p0'))
        check(auto(p) and name(p) == expected, f'Automatic opening follows subsequent player {expected}')
    r.next_reveal_player(force=True)
    visual.apply(p, r.get_state('p0'))
    check(r.phase == 'SPEECH' and auto(p) and name(p) == 'Алекс', 'Opening-to-Speech-1 transition preserves auto mode')

    select(p, 'p3')
    select(p, 'p0')
    check(auto(p) and name(p) == 'Алекс', 'REGRESSION: clicking current roster player restores auto, not just their dossier')
    r.next_speaker(force=True)
    visual.apply(p, r.get_state('p0'))
    check(auto(p) and name(p) == 'Ирина', 'REGRESSION: next speech follows after clicking active roster player')
    p.locator('#dashViewAll').click()
    check(p.locator('.player-tile').count() == 6, 'Overview remains available')
    p.locator('.player-tile-main[data-player="p4"]').click()
    check(not auto(p) and name(p) == 'Сергей', 'Non-active overview selection pins the dossier')
    p.locator('#dashViewAll').click()
    p.locator('.player-tile-main[data-player="p1"]').click()
    check(auto(p) and name(p) == 'Ирина', 'Active overview selection also restores automatic following')
    for _ in range(3):
        p.locator('#dashFindSpeaker').click()
    check(auto(p), 'Repeated resume clicks never turn automatic following off')
    p.locator('#dashViewAll').click()
    p.locator('#dashFindSpeaker').click()
    check(auto(p) and name(p) == 'Ирина', 'Resume returns from overview to active dossier')

    select(p, 'p4')
    r.host_grant_speech_speaker('p4')
    visual.apply(p, r.get_state('p0'))
    check(not auto(p) and 'ЗАКРЕПЛЁН' in p.locator('.dash-focus-header .eyebrow').inner_text(),
          'Pinned mode stays clearly labelled even when pinned person becomes active')
    select(p, 'p4')
    check(auto(p), 'Clicking the now-active pinned person resumes following')
    select(p, 'p5')
    p.locator('#dashFindSpeaker').focus()
    p.keyboard.press('Enter')
    check(auto(p) and name(p) == 'Сергей', 'Keyboard Enter resumes follow')
    select(p, 'p5')
    p.locator('#dashFindSpeaker').focus()
    p.keyboard.press('Space')
    check(auto(p), 'Keyboard Space resumes follow')
    p.screenshot(path=str(out/'auto_1366x768.png'))

    r.start_accusation_phase()
    visual.apply(p, r.get_state('p0'))
    check(auto(p) and name(p) == 'Алекс', 'Speech-2 uses the separate accusation speaker field')
    r.next_accusation_speaker()
    visual.apply(p, r.get_state('p0'))
    check(auto(p) and name(p) == 'Ирина', 'Speech-2 follows subsequent turns')
    select(p, 'p4')
    r.start_voting()
    visual.apply(p, r.get_state('p0'))
    check(p.locator('#dashFindSpeaker').is_visible() and p.locator('#dashFindSpeaker').is_enabled(),
          'Return control remains available during voting without an active speaker')
    check(p.locator('#dashPlayers > .dash-panel-title #dashFindSpeaker').count() == 1,
          'Voting places existing control in header, not above candidate grid')
    select(p, 'p2')
    check(p.locator('#modalPlayerDossier').is_visible(), 'Roster opens temporary dossier during voting')
    p.keyboard.press('Escape')
    check(not auto(p), 'Temporary voting dossier preserves pre-existing manual mode')
    p.locator('#dashFindSpeaker').click()
    check(auto(p) and p.locator('#voteCandidatesGrid').is_visible(), 'Can arm auto during voting without replacing candidates')
    select(p, 'p3')
    p.keyboard.press('Escape')
    check(auto(p), 'Temporary voting dossier does not silently disable auto')
    check(p.evaluate('window.sentCommands.length') == 0, 'Navigation does not issue any game command')
    p.screenshot(path=str(out/'voting_auto_1366x768.png'))
    r.start_justification(['p2', 'p4'], True, [], 50)
    visual.apply(p, r.get_state('p0'))
    check(auto(p) and name(p) == 'Максим', 'Armed auto resumes when candidate defense starts')
    r.next_justification_speaker()
    visual.apply(p, r.get_state('p0'))
    check(auto(p) and name(p) == 'Сергей', 'Defense follows second candidate')
    r.next_justification_speaker()
    visual.apply(p, r.get_state('p0'))
    check(r.phase == 'REVOTE' and auto(p) and p.locator('#dashFindSpeaker').is_enabled(), 'Auto survives revote with no speaker')
    r.phase = 'LAST_WORD'
    r.eliminated_in_last_word_id = 'p3'
    r.players['p3'].is_alive = False
    visual.apply(p, r.get_state('p0'))
    check(auto(p) and name(p) == 'Дарья', 'Last word follows the expelled speaker instead of filtering them out')
    r.start_speech_phase()
    r.host_grant_speech_speaker('p0')
    visual.apply(p, r.get_state('p0'))
    select(p, 'p2')
    p.evaluate('window.bunkerDashboard.disconnected()')
    visual.apply(p, r.get_state('p0'))
    check(not auto(p) and name(p) == 'Максим', 'Reconnect snapshot preserves manual mode')
    p.locator('#dashFindSpeaker').click()
    p.evaluate('window.bunkerDashboard.disconnected()')
    r.host_grant_speech_speaker('p4')
    visual.apply(p, r.get_state('p0'))
    check(auto(p) and name(p) == 'Сергей', 'Reconnect snapshot preserves auto and catches up to new speaker')
    select(p, 'p2')
    removed = r.get_state('p0')
    removed['players'] = [x for x in removed['players'] if x['id'] != 'p2']
    visual.apply(p, removed)
    check(auto(p) and name(p) == 'Сергей', 'Removed pinned target recovers to automatic mode')
    select(p, 'p5')
    p.locator('#dashViewAll').click()
    p.evaluate('window.bunkerDashboard.reset()')
    visual.apply(p, r.get_state('p0'))
    check(auto(p) and name(p) == 'Сергей', 'Reset restores focused automatic mode, not stale overview')
    select(p, 'p5')
    r.host_set_phase('FINAL')
    visual.apply(p, r.get_state('p0'))
    fresh = visual.room(6)  # same room code; a new match after FINAL
    visual.apply(p, fresh.get_state('p0'))
    check(auto(p) and name(p) == 'Алекс', 'New match in the same room starts automatic')
    select(p, 'p5')
    other = fresh.get_state('p0')
    other['room_code'] = 'NEW1'
    visual.apply(p, other)
    check(auto(p) and name(p) == 'Алекс', 'A different room starts automatic')
    p.close()

    for width, height in ((1280, 720), (1440, 900), (1920, 1080), (390, 844), (683, 384)):
        p = visual.boot(browser, width, height, out)
        r = visual.room(12)
        visual.apply(p, r.get_state('p0'))
        if width < 1100:
            p.locator('[data-mobile-tab="players"]').click()
        select(p, 'p2')
        check(not auto(p), f'{width}x{height}: manual selection available')
        button = p.locator('#dashFindSpeaker')
        button.click()
        check(auto(p) and name(p) == 'Алекс', f'{width}x{height}: resume button works')
        r.next_speaker(force=True)
        visual.apply(p, r.get_state('p0'))
        check(auto(p) and name(p) == 'Ирина', f'{width}x{height}: future speaker follows')
        check(p.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), f'{width}x{height}: no horizontal overflow')
        box = button.bounding_box()
        check(box is not None and box['x'] >= 0 and box['x']+box['width'] <= width+1, f'{width}x{height}: button not clipped horizontally')
        if width >= 1100:
            check(box['y']+box['height'] <= height, f'{width}x{height}: button in visible workspace')
        r.start_voting()
        visual.apply(p, r.get_state('p0'))
        button.click()
        check(auto(p) and button.is_visible(), f'{width}x{height}: auto accessible during vote')
        check(p.locator('#voteCandidatesGrid .vote-candidate').count() == 11, f'{width}x{height}: all voting candidates retained')
        if width >= 1100:
            grid = p.locator('#voteCandidatesGrid')
            check(grid.evaluate('(e)=>e.scrollHeight<=e.clientHeight+1'), f'{width}x{height}: candidates still fit without pages')
        if width == 390:
            p.screenshot(path=str(out/'auto_mobile_390x844.png'))
        p.close()
    check(not visual.ERRORS, 'No JavaScript errors in targeted browser scenarios')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--chromium', default='/usr/bin/chromium')
    parser.add_argument('--output', type=Path, default=ROOT/'autofollow_results')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    random.seed(41126)
    error = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=args.chromium, headless=True, args=['--no-sandbox'])
            try:
                run(browser, args.output)
            finally:
                browser.close()
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    report = {'passed':error is None, 'checks_passed':len(CHECKS), 'checks':CHECKS,
              'failure':error, 'javascript_errors':visual.ERRORS,
              'mode':'Real HTML/CSS/JS + actual engine snapshots; offline test transport, not a network match.'}
    (args.output/'autofollow_ui.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'checks'}, ensure_ascii=False, indent=2))
    if error:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
