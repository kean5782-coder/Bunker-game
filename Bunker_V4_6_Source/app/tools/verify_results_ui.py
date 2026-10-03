#!/usr/bin/env python3
"""V4.3 browser checks using real UI and engine snapshots (offline transport)."""
from __future__ import annotations
import argparse
import copy
import json
import random
from pathlib import Path
from playwright.sync_api import sync_playwright
import verify_visual as visual
from server import deck_data
from server.game_engine import BunkerGameRoom

ROOT=Path(__file__).resolve().parents[1]
CHECKS=[]
LAYOUTS=[]


def check(value,name):
    if not value:raise AssertionError(name)
    CHECKS.append(name)


def make_room(n=6):
    r=visual.room(n);r.start_voting()
    targets=['p1','p1','p2','p2','p3','p3']
    for pid,target in zip(r.players,targets):r.cast_vote(pid,target)
    return r


def finish_review(r):
    while r.result_reviews:r.tick_timer()


def bounds(page,label):
    result=page.evaluate('''() => {
      const box=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}};
      return {screen:[innerWidth,innerHeight],bodyWidth:document.documentElement.scrollWidth,
        card:box(document.querySelector('.result-review-card')),
        footer:box(document.querySelector('.result-review-footer')),
        next:box(document.getElementById('resultReviewNext')),
        contentWidth:document.getElementById('resultReviewContent').scrollWidth,
        availableWidth:document.getElementById('resultReviewContent').clientWidth};
    }''')
    LAYOUTS.append({'scenario':label,**result})
    w,h=result['screen'];b=result['card'];f=result['footer']
    check(b['x']>=-1 and b['y']>=-1 and b['x']+b['w']<=w+1 and b['y']+b['h']<=h+1,label+': result card within viewport')
    check(f['y']>=0 and f['y']+f['h']<=h+1,label+': next-stage footer always visible')
    check(result['bodyWidth']<=w+1 and result['contentWidth']<=result['availableWidth']+1,label+': no horizontal overflow')


def run(browser,out):
    for w,h in [(1366,768),(1440,900),(1920,1080),(1280,720),(390,844),(683,384)]:
        label=f'{w}x{h}'
        p=visual.boot(browser,w,h,out);r=make_room()
        visual.apply(p,r.get_state('p0'))
        check(p.locator('#resultReviewModal').is_visible(),label+': voting result automatically opens centrally')
        check('защита' in p.locator('#resultReviewTitle').inner_text().lower(),label+': interim decision explained')
        check('Защита кандидата' in p.locator('#resultReviewNext').inner_text(),label+': next phase named')
        check('Ирина' in p.locator('#resultReviewNextDetail').inner_text(),label+': next speaker named')
        check(p.locator('.review-tally-row').count()==3,label+': aggregate tally shown')
        check(p.locator('#viewGame').evaluate('(e)=>e.inert'),label+': game controls blocked during automatic review')
        check(not p.locator('#btnCloseResultReview').is_visible(),label+': no individual skip of shared review')
        p.keyboard.press('Escape')
        check(p.locator('#resultReviewModal').is_visible(),label+': Escape cannot skip shared stage')
        bounds(p,label+' vote')
        p.screenshot(path=str(out/f'vote_{w}x{h}.png'))
        p.evaluate('window.retainedResult=document.querySelector(".result-review-card");window.retainedResultBody=document.getElementById("resultReviewContent").firstElementChild;window.retainedCards=[...document.querySelectorAll("#myCardsList .dossier-item")]')
        for seconds in range(5,0,-1):
            visual.apply(p,r.get_state('p0'))
            check(p.locator('#resultReviewClock').inner_text()==str(seconds),label+f': shared countdown {seconds}')
            check(r.timer_seconds_left==30,label+f': full defense timer held at {seconds}')
            check(p.evaluate('window.retainedResultBody===document.getElementById("resultReviewContent").firstElementChild && window.retainedCards.every(c=>c.isConnected)'),label+f': tick {seconds} retains result and dossier nodes')
            r.tick_timer()
        visual.apply(p,r.get_state('p0'))
        check(not p.locator('#resultReviewModal').is_visible(),label+': closes when server completes review')
        check(not p.locator('#viewGame').evaluate('(e)=>e.inert'),label+': gameplay controls restored')
        check(p.locator('#phaseTitle').inner_text()=='Защита кандидата',label+': defense clearly named in permanent header')
        check('Переголосование' in p.locator('#phaseDesc').inner_text() or w==683,label+': next phase available in permanent header')
        p.locator('#btnLastVoteReview').click()
        check(p.locator('#resultReviewModal').is_visible() and p.locator('#btnCloseResultReview').is_visible(),label+': saved vote result can be reopened')
        check('не останавливает' in p.locator('#resultReviewTimerNote').inner_text(),label+': manual view explains timer keeps running')
        p.keyboard.press('Escape');check(not p.locator('#resultReviewModal').is_visible(),label+': manual result dismisses with Escape')
        # Mid-speech/manual event has a full shared review even with no phase change.
        r.start_speech_phase();r.timer_seconds_left=23;r.timer_is_paused=False
        r.active_event=copy.deepcopy(next(e for e in deck_data.BUNKER_EVENTS if e['type']=='BUNKER_CRISIS'))
        r.recalculate_event_odds();result=r.resolve_active_event(force_roll=99)
        visual.apply(p,r.get_state('p0'))
        check(p.locator('#resultReviewTitle').inner_text()=='Критический провал',label+': critical failure unambiguous')
        body=p.locator('#resultReviewContent').inner_text()
        check('99' in body and 'Для успеха нужно' in body,label+': actual d100 and target visible')
        check('ВКЛАД ИСПЫТАНИЙ' in body and 'очков' in body,label+': event points distinguished from normalized rating')
        check('Речь 1' in p.locator('#resultReviewNext').inner_text() and '23 сек' in p.locator('#resultReviewNextDetail').inner_text(),label+': manual event resumes same turn with held time')
        bounds(p,label+' event');p.screenshot(path=str(out/f'event_{w}x{h}.png'))
        finish_review(r);visual.apply(p,r.get_state('p0'))
        check(not p.locator('#resultReviewModal').is_visible(),label+': no old result replay after completion')
        if w<1100:p.locator('[data-mobile-tab="actions"]').click()
        p.locator('#lastEventInline .event-result-link').click()
        check(p.locator('#resultReviewTitle').inner_text()=='Критический провал',label+': prominent event recap directly reopens outcome')
        p.keyboard.press('Escape');p.close()

    p=visual.boot(browser,1366,768,out);r=make_room();r.tick_timer();r.tick_timer()
    visual.apply(p,r.get_state('p1'),'p1')
    check(p.locator('#resultReviewClock').inner_text()=='3','Reconnect/late client sees remaining three seconds, not new five')
    check(not p.locator('#btnPauseResultReview').is_visible(),'Only host can pause automatic result')
    p.keyboard.press('Tab');check(p.evaluate('document.getElementById("resultReviewModal").contains(document.activeElement)'),'Focus cannot leave result even without controls')
    visual.apply(p,r.get_state('observer'),'observer')
    check(p.locator('#resultReviewModal').is_visible(),'Unregistered observer sees same result')
    visual.apply(p,r.get_state('p0'))
    p.locator('#btnPauseResultReview').click()
    check(p.evaluate('window.sentCommands.at(-1).action')=='HOST_PAUSE_TIMER','Pause button sends actual host pause command')
    r.host_pause_timer(True);visual.apply(p,r.get_state('p0'))
    check('ПАУЗЕ' in p.locator('#resultReviewTiming').inner_text(),'Shared pause is explicitly indicated')
    r.players['p0'].connected=False;visual.apply(p,r.get_state('p1'),'p1')
    check(p.locator('#btnClaimReviewHost').is_visible(),'Guests can reclaim host from paused overlay if original host disconnected')
    p.evaluate('window.bunkerResults.disconnected()')
    check('НЕТ СВЯЗИ' in p.locator('#resultReviewTiming').inner_text(),'Disconnection cannot fake countdown or phase advancement')
    r.host_pause_timer(False);finish_review(r);visual.apply(p,r.get_state('p1'),'p1')
    p.locator('#dashRoster [data-player="p0"]').click()
    # This opens pinned dossier, not a modal. Use actual detailed dossier.
    p.evaluate('window.bunkerDashboard.openDossier(state.gameData.players[0])')
    r.events_enabled=True;r.host_trigger_event();r.resolve_active_event(force_roll=1)
    visual.apply(p,r.get_state('p1'),'p1')
    check(not p.locator('#modalPlayerDossier').is_visible() and p.locator('#resultReviewModal').is_visible(),'Result replaces an open detailed dossier instead of being obscured')
    p.keyboard.press('Tab');check(p.evaluate('document.getElementById("resultReviewModal").contains(document.activeElement)'),'Result takes accessible focus from previous modal')
    finish_review(r);r.start_revote();visual.apply(p,r.get_state('p1'),'p1')
    check(p.locator('#phaseTitle').inner_text()=='Переголосование','Revote explicitly differs from original vote')
    check(p.locator('.dash-step.current').inner_text()=='Переголосование','Separate revote step highlighted in phase rail')
    p.close()

    # Skip + abstention weighted totals and an exact provisional-veto transition.
    p=visual.boot(browser,1366,768,out)
    r=visual.room(6);r.start_voting();r.players['p0'].double_vote=True
    for pid,target in zip(r.players,['p1','p1','p2','ABSTAIN','SKIP_ROUND','p3']):r.cast_vote(pid,target)
    visual.apply(p,r.get_state('p0'));text=p.locator('#resultReviewContent').inner_text()
    check('Воздержание' in text and 'За пропуск изгнания' in text and '42,9%' in text,'Weighted skip and abstention shown separately, correct denominator')
    finish_review(r);r.start_revote()
    for pid in r.players:r.cast_vote(pid,'p1')
    visual.apply(p,r.get_state('p0'))
    check('ИТОГИ ПЕРЕГОЛОСОВАНИЯ' in p.locator('#resultReviewEyebrow').inner_text(),'Final tally labeled as revote result')
    check(p.locator('#resultReviewNext').inner_text()=='Далее: Право вето','Result does not call candidate expelled before veto')
    check('10 сек' in p.locator('#resultReviewNextDetail').inner_text(),'Full veto window advertised separately')
    p.screenshot(path=str(out/'revote_1366x768.png'))
    finish_review(r);visual.apply(p,r.get_state('p0'))
    check(p.locator('#phaseTitle').inner_text()=='Право вето','Permanent title changes to real veto stage')
    p.close()

    # Twenty names do not push the countdown below the viewport; long details scroll.
    for w,h in [(1366,768),(390,844),(683,384)]:
        r=BunkerGameRoom('BIG1','p0','Участник 0')
        for i in range(1,20):r.add_player(f'p{i}',f'Очень длинное имя участника № {i}')
        r.start_game(capacity=10,enable_events=False,skip_prologue=True);r.start_voting()
        for person in r.players.values():person.connected=True
        for i in range(20):r.cast_vote(f'p{i}',f'p{(i+1)%20}')
        p=visual.boot(browser,w,h,out);visual.apply(p,r.get_state('p0'))
        check(p.locator('.review-tally-row').count()==20,f'{w}: twenty ballot rows available')
        bounds(p,f'{w} twenty players')
        p.locator('#resultReviewContent').evaluate('(e)=>e.scrollTop=e.scrollHeight')
        check(p.locator('#resultReviewNext').is_visible(),f'{w}: scrolling long tally leaves next phase visible')
        p.close()

    # All event outcomes + escaping + no undesired history replay or privacy leak.
    p=visual.boot(browser,1366,768,out);r=visual.room(6)
    for roll,title in [(1,'Критический успех'),(20,'Успех'),(95,'Провал')]:
        r.active_event=copy.deepcopy(next(e for e in deck_data.BUNKER_EVENTS if e['type']=='BUNKER_CRISIS'))
        r.recalculate_event_odds();r.resolve_active_event(force_roll=roll);visual.apply(p,r.get_state('p0'))
        check(p.locator('#resultReviewTitle').inner_text()==title,title+' is shown explicitly')
        finish_review(r);visual.apply(p,r.get_state('p0'))
    r.active_event=copy.deepcopy(next(e for e in deck_data.BUNKER_EVENTS if e['type']=='SURFACE_EVENT'));r.recalculate_event_odds();r.skip_sortie(True);r.resolve_active_event();visual.apply(p,r.get_state('p0'))
    check('отменена' in p.locator('#resultReviewTitle').inner_text() and 'Броска не было' in p.locator('#resultReviewContent').inner_text(),'Skipped sortie never shows d100 zero as success')
    finish_review(r);r.host_trigger_event();r.resolve_active_event(guaranteed_success=True);visual.apply(p,r.get_state('p0'))
    check('Успех без броска' in p.locator('#resultReviewContent').inner_text(),'Overdrive never invents a random dice result')
    finish_review(r);r.host_trigger_event();r.resolve_active_event(force_roll=1)
    r.result_reviews[0]['data']['event_title']='<img src=x onerror="window.BAD=1">'
    visual.apply(p,r.get_state('p0'));check(p.evaluate('!window.BAD') and p.locator('#resultReviewContent img').count()==0,'Result text safely escapes markup')
    finish_review(r);r.trigger_final();visual.apply(p,r.get_state('p0'))
    check(not p.locator('#resultReviewModal').is_visible(),'Final does not replay old event outcome')
    p.close()
    check(not visual.ERRORS,'No JavaScript exceptions across all result scenarios')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--chromium',default='/usr/bin/chromium');parser.add_argument('--output',default=str(ROOT/'results_v4_3/ui'))
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True);random.seed(443)
    failure=None
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
            try:run(browser,out)
            finally:browser.close()
    except Exception as exc:
        import traceback
        traceback.print_exc();failure=f'{type(exc).__name__}: {exc}'
    report={'passed':failure is None,'mode':'Real DOM + real engine, offline transport (live browser test is separate)',
            'checks_passed':len(CHECKS),'checks':CHECKS,'failure':failure,'javascript_errors':visual.ERRORS,'layouts':LAYOUTS}
    (out/'results_ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('checks','layouts')},ensure_ascii=False,indent=2))
    if failure:raise SystemExit(1)

if __name__=='__main__':main()
