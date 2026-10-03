#!/usr/bin/env python3
"""Age V4 browser audit, real engine/assets + offline test transport, not a live match."""
from __future__ import annotations
import argparse, copy, json, random, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server import balance as b
from server.game_engine import BunkerGameRoom
import verify_visual as visual
CHECKS=[];ERRORS=[]

def check(v,message):
    if not v:raise AssertionError(message)
    CHECKS.append(message)

def make_room():
    random.seed(19287);r=BunkerGameRoom('AGE4','p0','Алекс')
    for i,name in enumerate(['Ирина','Максим','Дарья','Сергей','Никита'],1):r.add_player('p'+str(i),name)
    r.start_game(capacity=3,enable_events=True);r.host_pause_timer(True)
    for i,p in enumerate(r.players.values()):
        age=76 if i==0 else 65 if i==1 else 30
        p.cards['gender'].update(age=age,value=f'Персонаж, {age} лет',revealed=False)
        b.decorate_card(p.cards['gender'],'gender')
    return r

def run(browser,out):
    p=visual.boot(browser,1366,768,out);p.on('pageerror',lambda e:ERRORS.append(str(e)))
    r=make_room();visual.apply(p,r.get_state('p0'))
    check(p.locator('#timerDigits').inner_text()=='1:00','Separate 60-second reveal retained')
    p.locator('#myCardsList [data-open-card="gender"]').click()
    check('76 лет' in p.locator('#modalPlayerDossier').inner_text(),'Own structured age shown')
    check('нагрузка ухода' in p.locator('.dossier-mechanics').inner_text(),'Own card explains age mechanic')
    check('не медицинский прогноз' in p.locator('.dossier-mechanics').inner_text(),'Game-model qualification visible')
    p.screenshot(path=str(out/'age_dossier_1366x768.png'));p.keyboard.press('Escape')
    check(not p.locator('#modalPlayerDossier').is_visible(),'Dossier closes with Escape')
    g=r.get_state('p1');visual.apply(p,g,'p1')
    target=next(x for x in g['players'] if x['id']=='p0')
    p.evaluate('(player)=>window.bunkerDashboard.openDossier(player)',target)
    text=p.locator('#modalPlayerDossier').inner_text()
    check('76 лет' not in text and 'нагрузка ухода' not in text,'Guest cannot see hidden age or its mechanic')
    p.keyboard.press('Escape')
    check(p.locator('#finalAgeCare').count()==0,'No final age analysis before final phase')
    for i in range(3,6):r.players['p'+str(i)].is_alive=False
    r.trigger_final();game=r.get_state('p0');visual.apply(p,game)
    age=game['final_evaluation']['breakdown']['age_care']
    check(age['penalty']>0,'Fixture really incurs age penalty')
    check(p.locator('#finalAgeCare').is_visible(),'Final-only age section visible')
    check(p.locator('#finalNeeds progress').count()==5,'All five original needs retained')
    check('балла' in p.locator('.age-care-total').inner_text(),'Penalty labeled in rating points')
    check(str(age['penalty']).replace('.',',') in p.locator('.age-care-total').inner_text(),'UI penalty matches server value')
    check('12' in p.locator('#finalAgeCare').inner_text(),'Team cap disclosed')
    p.screenshot(path=str(out/'age_final_1366x768.png'))
    p.locator('#finalAgeDetails summary').click()
    check(p.locator('.age-care-person').count()==3,'Only survivors in care breakdown')
    text=p.locator('#finalAgeDetails').inner_text()
    check('Алекс' in text and 'Ирина' in text and 'Сергей' not in text,'Correct survivor names, no exiles')
    check('здоровье ×' in text and 'выносливость ×' in text,'Personal discounts explained')
    check('Пол, ориентация и фертильность не штрафуют' in text,'No sex/fertility penalty stated')
    tick=copy.deepcopy(game);tick['timer']['seconds_left']=42;visual.apply(p,tick)
    check(p.locator('#finalAgeDetails').get_attribute('open') is not None,'Timer update preserves expanded analysis')
    p.locator('#finalAgeCare').scroll_into_view_if_needed();p.screenshot(path=str(out/'age_details_1366x768.png'))
    # Escaping is checked against real DOM rendering, not a raw HTML string.
    hostile=copy.deepcopy(game);hostile['final_evaluation']['breakdown']['age_care']['rows'][0]['player_name']='<img src=x onerror="window.ageXss=true">'
    visual.apply(p,hostile);p.locator('#finalAgeDetails summary').click()
    check(p.locator('#finalAgeCare img').count()==0 and not p.evaluate('Boolean(window.ageXss)'),'Names escaped; no executable markup')
    r2=make_room();visual.apply(p,r2.get_state('p0'))
    check(p.locator('#finalAgeCare').count()==0,'Old final age data cleared when starting a new game')
    check(p.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'1366px: no horizontal page overflow')
    p.close()
    for width,height in ((1440,900),(1280,720),(390,844)):
        p=visual.boot(browser,width,height,out);p.on('pageerror',lambda e:ERRORS.append(str(e)))
        visual.apply(p,game)
        check(p.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'{width}px: final has no horizontal overflow')
        p.locator('#finalAgeDetails summary').focus();p.keyboard.press('Enter')
        check(p.locator('#finalAgeDetails').get_attribute('open') is not None,f'{width}px: details keyboard accessible')
        p.locator('#finalAgeCare').scroll_into_view_if_needed()
        check(p.locator('.age-care-person').count()==3,f'{width}px: all care rows available')
        check(p.locator('#finalAgeCare').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1'),f'{width}px: care panel has no internal horizontal clipping')
        check(p.locator('#finalScreenSection').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1'),f'{width}px: final panel has no internal horizontal clipping')
        p.screenshot(path=str(out/f'age_details_{width}x{height}.png'));p.close()
    check(not ERRORS and not visual.ERRORS,'No JavaScript exceptions')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--chromium',default='/usr/bin/chromium')
    parser.add_argument('--output',type=Path,default=ROOT/'age_results');args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    failure=None
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
            try:run(browser,args.output)
            finally:browser.close()
    except Exception as exc:failure=f'{type(exc).__name__}: {exc}'
    result={'passed':failure is None,'checks_passed':len(CHECKS),'checks':CHECKS,
            'javascript_errors':ERRORS+visual.ERRORS,'failure':failure,
            'mode':'Real DOM and engine; offline transport, not a live multi-user browser game.'}
    (args.output/'age_ui.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if failure:raise SystemExit(1)
if __name__=='__main__':main()
