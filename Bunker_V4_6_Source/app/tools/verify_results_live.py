#!/usr/bin/env python3
"""V4.3 live Chromium clients, real HTTP/WebSocket and running server clocks.

A subprocess seeds a deterministic room (no testing endpoint in production).
All subsequent transitions use actual browser controls and the normal server.
No WebSocket/fetch replacements; listeners only record received messages.
"""
from __future__ import annotations
import argparse
import copy
import json
import os
import random
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
CHECKS=[]


def check(value,name):
    if not value:raise AssertionError(name)
    CHECKS.append(name)


def server(port):
    import uvicorn
    from server import app as api, deck_data
    from server.game_engine import BunkerGameRoom
    api.get_external_ip=lambda:None
    api.get_local_ip=lambda:'127.0.0.1'
    api.generate_qr_data_url=lambda *args:'data:image/png;base64,'
    random.seed(443)
    r=BunkerGameRoom('LIVE','p0','Алекс')
    r.add_player('p1','Ирина');r.add_player('p2','Максим')
    r.start_game(capacity=1,enable_events=True,skip_prologue=True)
    r.active_event=copy.deepcopy(next(e for e in deck_data.BUNKER_EVENTS if e['type']=='BUNKER_CRISIS'))
    r.recalculate_event_odds();r.start_voting();r.host_pause_timer(True)
    api.rooms[r.room_code]=r
    uvicorn.run(api.app,host='127.0.0.1',port=port,log_level='warning')


def session(page,pid,base):
    page.add_init_script('''(function(){
      localStorage.setItem('bunker_sound_enabled','false');
      localStorage.setItem('bunker_session',SESSION);
    })();'''.replace('SESSION',json.dumps(json.dumps({'roomCode':'LIVE','playerId':pid,'playerName':pid,'isHost':pid=='p0'}))))
    page.goto(base,wait_until='domcontentloaded')
    page.wait_for_function('state.ws?.readyState===1 && state.gameData?.room_code==="LIVE"')
    page.evaluate('''() => {
      window.liveProtocol=[];
      state.ws.addEventListener('message',event=>{const msg=JSON.parse(event.data);if(msg.type==='STATE_UPDATE'||msg.type==='ERROR'){
        window.liveProtocol.push({at:performance.now(),message:msg});
      }});
    }''')


def state(page):return page.evaluate('state.gameData')


def send(page,action,payload=None):
    page.evaluate('({action,payload})=>sendAction(action,payload)',{'action':action,'payload':payload or {}})


def wait_no_review(page):
    page.wait_for_function('state.gameData && !state.gameData.result_review',timeout=12000)
    page.wait_for_function('document.getElementById("resultReviewModal").hidden',timeout=2000)


def wait_review(page,kind):
    page.wait_for_function('(kind)=>state.gameData?.result_review?.kind===kind',arg=kind,timeout=12000)
    page.wait_for_selector('#resultReviewModal:not([hidden])')


def vote(page,target):
    page.locator(f'[data-candidate="{target}"] [data-select-vote]').click()
    page.locator('[data-confirm-vote]').click()


def run(browser,base,out):
    errors=[];contexts=[];pages=[]
    try:
        for pid in ['p0','p1','p2']:
            context=browser.new_context(viewport={'width':1366,'height':768})
            contexts.append(context);page=context.new_page();pages.append(page)
            page.on('pageerror',lambda error:errors.append(str(error)))
            session(page,pid,base)
        host=pages[0]
        host.wait_for_function('state.gameData.players.every(p=>p.connected)')
        check(all(state(p)['phase']=='VOTING' for p in pages),'Three isolated browsers joined same actual room')
        check(host.locator('#voteCandidatesGrid .vote-candidate').count()==2,'Real vote candidate controls loaded from server')
        # Open a foreign dossier to prove a result is not hidden behind it.
        pages[2].locator('[data-candidate="p0"] [data-vote-details]').click()
        check(pages[2].locator('#modalPlayerDossier').is_visible(),'Real guest can inspect a dossier before voting')
        pages[2].keyboard.press('Escape')
        vote(pages[0],'p1');vote(pages[1],'p2');vote(pages[2],'p0')
        for page in pages:wait_review(page,'vote')
        review_id=state(host)['result_review']['id']
        check(all(state(p)['result_review']['id']==review_id for p in pages),'Same review ID broadcast to all three real sockets')
        check(all(p.locator('#resultReviewTitle').is_visible() for p in pages),'All browsers automatically show central result')
        check(all('Защита' in p.locator('#resultReviewNext').inner_text() for p in pages),'All clients agree defense is next')
        check(state(host)['timer']['seconds_left']==30,'Defense timer has not been spent during vote review')
        send(host,'NEXT_JUSTIFICATION_SPEAKER')
        host.wait_for_function('liveProtocol.some(x=>x.message.type==="ERROR" && x.message.action==="NEXT_JUSTIFICATION_SPEAKER")')
        check(state(host)['justification_status']['index']==0,'Real server rejects premature next-speaker action')
        # Pause/resume applies only to presentation, and is delivered to peers.
        host.locator('#btnPauseResultReview').click()
        for page in pages:page.wait_for_function('state.gameData.result_review?.is_paused')
        remaining=state(host)['result_review']['seconds_left']
        time.sleep(1.2)
        check(all(state(p)['result_review']['seconds_left']==remaining for p in pages),'Shared review pause freezes all browser countdowns')
        # Reconnect during pause: no replay/reset; same ID and same remaining time.
        pages[2].reload(wait_until='domcontentloaded')
        pages[2].wait_for_function('state.gameData?.result_review?.is_paused')
        back=state(pages[2])['result_review']
        check(back['id']==review_id and back['seconds_left']==remaining,'Real reconnect resumes same paused review')
        check(pages[2].locator('#resultReviewModal').is_visible(),'Reconnected browser immediately sees active result')
        host.locator('#btnPauseResultReview').click()
        wait_no_review(host)
        for page in pages[1:]:wait_no_review(page)
        check(all(state(p)['phase']=='JUSTIFICATION' for p in pages),'All real clients proceed to defense after countdown')
        records=host.evaluate('liveProtocol')
        resumed=[row for row in records if row['message'].get('type')=='STATE_UPDATE' and row['message']['state']['phase']=='JUSTIFICATION' and not row['message']['state'].get('result_review')]
        check(resumed[0]['message']['state']['timer']['seconds_left']==30,'First unblocked defense state retains entire 30 seconds')
        check(not host.locator('#viewGame').evaluate('(e)=>e.inert'),'Overlay releases real browser controls')
        # Three tied candidates each defend; use the normal host next button.
        for index in range(3):
            host.wait_for_function('(index)=>state.gameData.justification_status.index===index',arg=index)
            host.locator('#btnPassJustification').click()
        for page in pages:page.wait_for_function('state.gameData.phase==="REVOTE"')
        check(all(p.locator('#phaseTitle').inner_text()=='Переголосование' for p in pages),'Actual revote distinctly labeled in each browser')
        check(host.locator('.dash-step.current').inner_text()=='Переголосование','Revote has its own highlighted rail step')
        vote(pages[0],'p1');vote(pages[1],'p0');vote(pages[2],'p1')
        for page in pages:wait_review(page,'vote')
        r=state(host)['result_review'];second_id=r['id']
        check(second_id!=review_id and r['data']['source']=='REVOTE','New final tally is a different review, not old interim result')
        check(all('Право вето' in p.locator('#resultReviewNext').inner_text() for p in pages),'Next-stage label preserves veto opportunity')
        check(all(next(v for v in state(p)['players'] if v['id']=='p1')['is_alive'] for p in pages),'Candidate is not marked expelled before confirmation')
        host.screenshot(path=str(out/'live_revote_1366x768.png'))
        wait_no_review(host)
        for page in pages[1:]:wait_no_review(page)
        records=host.evaluate('liveProtocol')
        notices=[row for row in records if row['message'].get('type')=='STATE_UPDATE' and (row['message']['state'].get('result_review') or {}).get('id')==second_id]
        complete=next(row for row in records if row['at']>notices[0]['at'] and row['message'].get('type')=='STATE_UPDATE' and row['message']['state']['phase']=='VOTE_RESULTS' and not row['message']['state'].get('result_review'))
        duration=(complete['at']-notices[0]['at'])/1000
        check(4.9<=duration<=6.5,f'Actual unpaused shared review lasted {duration:.3f}s')
        check(complete['message']['state']['timer']['seconds_left']==10,'Entire ten-second veto timer starts after final tally')
        check(host.locator('#phaseTitle').inner_text()=='Право вето','Underlying current phase after summary is named correctly')
        host.locator('#btnHostNextRoundNow').click()
        for page in pages:wait_review(page,'event')
        event_id=state(host)['result_review']['id']
        check(all(state(p)['result_review']['id']==event_id for p in pages),'Automatic event result is shared after host confirms expulsion')
        check(all(not next(v for v in state(p)['players'] if v['id']=='p1')['is_alive'] for p in pages),'Expulsion confirmed before event result shown')
        check(all('Последнее слово' in p.locator('#resultReviewNext').inner_text() for p in pages),'Event clearly hands off to last word, not a new vote')
        check(all(state(p)['timer']['seconds_left']==15 for p in pages),'Event overlay does not consume last-word time')
        check(all('Для успеха нужно' not in p.locator('#resultReviewContent').inner_text() and p.locator('#resultReviewContent').inner_text().strip() for p in pages),'Actual event outcome visible on all clients without d100 threshold')
        host.screenshot(path=str(out/'live_event_1366x768.png'))
        wait_no_review(host)
        for page in pages[1:]:wait_no_review(page)
        records=host.evaluate('liveProtocol')
        first_last=next(row for row in records if row['message'].get('type')=='STATE_UPDATE' and row['message']['state']['phase']=='LAST_WORD' and not row['message']['state'].get('result_review'))
        check(first_last['message']['state']['timer']['seconds_left']==15,'First playable last-word state has all fifteen seconds')
        check(all(p.locator('#phaseTitle').inner_text()=='Последнее слово' for p in pages),'All clients display final-word stage explicitly')
        # Recap is available directly in the main game; manual viewing does not pause others.
        host.locator('#lastEventInline .event-result-link').click()
        check(host.locator('#btnCloseResultReview').is_visible(),'Actual event recap opens a dismissible manual view')
        check(not pages[2].locator('#resultReviewModal').is_visible(),'Manual recap is local, not broadcast as a new result')
        check('не останавливает' in host.locator('#resultReviewTimerNote').inner_text(),'Manual recap warns that shared time continues')
        host.keyboard.press('Escape')
        send(host,'FINISH_LAST_WORD')
        for page in pages:page.wait_for_function('state.gameData.phase==="REVEAL" && state.gameData.round_number===2')
        check(all(not p.locator('#resultReviewModal').is_visible() for p in pages),'Next round does not replay old event or vote review')
        # Resolve a new event mid-turn through the actual right-panel button.
        send(host,'HOST_PAUSE_TIMER',{'is_paused':True})
        host.wait_for_function('state.gameData.timer.is_paused')
        before=state(host)['timer']['seconds_left']
        host.locator('[data-event-action="resolve"]').click()
        for page in pages:wait_review(page,'event')
        check(state(host)['result_review']['next_label']=='Открытие карточек','Manual event predicts return to current phase')
        wait_no_review(host)
        check(state(host)['timer']['seconds_left']==before and state(host)['timer']['is_paused'],'Original paused turn remains paused with same time after result')
        check(not errors,'No JavaScript exceptions across real multi-browser match')
        (out/'live_protocol_host.json').write_text(json.dumps(host.evaluate('liveProtocol'),ensure_ascii=False,indent=2),encoding='utf8')
    finally:
        for context in contexts:context.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--server',type=int);parser.add_argument('--chromium',default='/usr/bin/chromium');parser.add_argument('--output',default=str(ROOT/'results_v4_3/live'))
    args=parser.parse_args()
    if args.server:server(args.server);return
    import httpx
    from playwright.sync_api import sync_playwright
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    failure=None
    with (out/'live_server.log').open('w') as log:
        process=subprocess.Popen([sys.executable,__file__,'--server',str(port)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    if httpx.get(base+'/api/room/LIVE',timeout=.4).status_code==200:break
                except Exception:pass
                time.sleep(.1)
            else:raise RuntimeError('Server not started')
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
                try:run(browser,base,out)
                finally:browser.close()
        except Exception as exc:
            traceback.print_exc();failure=f'{type(exc).__name__}: {exc}'
        finally:
            process.terminate()
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    report={'passed':failure is None,'mode':'Three Chromium browser contexts + real localhost HTTP/WebSocket + running production timer worker',
            'checks_passed':len(CHECKS),'checks':CHECKS,'failure':failure}
    (out/'results_live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if failure:raise SystemExit(1)

if __name__=='__main__':main()
