#!/usr/bin/env python3
"""Repeatable UI verification of the real bundled HTML/CSS/JS.

Browser transport is an explicit in-process test binding; this is not a live
browser WebSocket match. It never changes Chromium policy/network settings.
The actual ASGI/WebSocket protocol is covered separately by tests_balance.
Run: python tools/verify_visual.py --chromium /path/to/chromium
Requires the optional developer dependency playwright.
"""
from __future__ import annotations
import argparse, base64, copy, json, random, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.game_engine import BunkerGameRoom
from server import deck_data

NAMES = ['Алекс', 'Ирина', 'Максим', 'Дарья', 'Сергей', 'Никита',
         'Екатерина', 'Денис', 'Анастасия', 'Константин', 'Евгений', 'Виктория']
CHECKS: list[str] = []
ERRORS: list[str] = []
LAYOUTS: list[dict] = []


def check(condition: bool, name: str) -> None:
    if not condition:
        raise AssertionError(name)
    CHECKS.append(name)


def room(count=8, started=True, prologue=False) -> BunkerGameRoom:
    r = BunkerGameRoom('VIS1', 'p0', NAMES[0])
    for i in range(1, count):
        r.add_player(f'p{i}', NAMES[i])
    for p in r.players.values():
        p.connected = True
    if started:
        r.start_game(capacity=max(1, count//2), enable_events=True,
                     enable_traitor=False, skip_prologue=not prologue)
        if not prologue:
            r.start_speech_phase()
            r.host_grant_speech_speaker('p0')
        r.host_pause_timer(True)
        for i, p in enumerate(r.players.values()):
            if i % 2:
                p.cards['profession']['revealed'] = True
                p.cards['hobby']['revealed'] = True
    return r


def boot(browser, width, height, out, include_lobby=True):
    p = browser.new_page(viewport={'width': width, 'height': height}, device_scale_factor=1)
    p.set_default_timeout(5000)
    p.on('pageerror', lambda e: ERRORS.append(str(e)))
    p.route('**/*', lambda route: route.abort())
    html = (ROOT/'static/index.html').read_text(encoding='utf8')
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.S | re.I)
    html = re.sub(r'<link\b[^>]*>', '', html, flags=re.I)
    p.set_content(html)
    image = 'data:image/jpeg;base64,' + base64.b64encode(
        (ROOT/'static/images/catastrophes/nuclear_winter.jpg').read_bytes()).decode()
    for name in ['style.css', 'animations.css', 'dashboard.css', 'results.css']:
        css = (ROOT/'static/css'/name).read_text(encoding='utf8').replace(
            '/static/images/catastrophes/nuclear_winter.jpg', image)
        p.add_style_tag(content=css)
    p.evaluate("""window.fetch=async()=>({ok:true,json:async()=>({local_ip:'127.0.0.1',external_ip:'',port:8008})});
      for(const name of ['localStorage','sessionStorage']){const data={bunker_sound_enabled:'false'};
        Object.defineProperty(window,name,{value:{getItem:k=>data[k]||null,setItem:(k,v)=>data[k]=String(v),removeItem:k=>delete data[k]}});}
      window.sentCommands=[];window.holdTransport=true;""")
    for name in ['sound_fx.js', 'app.js', 'dashboard.js', 'results.js']:
        p.add_script_tag(content=(ROOT/'static/js'/name).read_text(encoding='utf8'))
    if include_lobby:
        from server.lobby import public_catalog
        p.add_style_tag(content=(ROOT/'static/css/lobby.css').read_text())
        p.evaluate('(catalog)=>{window.fetch=async url=>({ok:true,json:async()=>String(url).includes("lobby-options")?catalog:{local_ip:"127.0.0.1",port:8008}})}',public_catalog())
        p.evaluate('(images)=>window.__lobbyImages=images',{f.stem:'data:image/jpeg;base64,'+base64.b64encode(f.read_bytes()).decode() for f in (ROOT/'static/images/catastrophes').glob('*.jpg')})
        source=(ROOT/'static/js/lobby.js').read_text().replace("url('/static/images/catastrophes/${cat.id}.jpg')", "url('${window.__lobbyImages[cat.id]}')")
        p.add_script_tag(content=source)
    p.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'))")
    p.wait_for_timeout(40)
    return p


def apply(p, g, viewer='p0'):
    p.evaluate("""({g,viewer})=>{
      state.roomCode=g.room_code;state.playerId=viewer;state.playerName=g.players.find(p=>p.id===viewer)?.name||'Наблюдатель';
      state.isHost=Boolean(g.is_host);state.prologueShownForRoom=g.phase==='PROLOGUE'?null:g.room_code;
      state.ws={readyState:1,send:(raw)=>{window.sentCommands.push(JSON.parse(raw));
        if(!window.holdTransport && window.engineCommand) window.engineCommand(raw).then(response=>{
          if(response.error){window.bunkerDashboard.actionError();showToast(response.error,'error');return;}
          if(response.ack?.action==='CAST_VOTE')window.bunkerDashboard.voteAck(response.ack);
          if(response.ack?.action==='USE_SPECIAL_CARD')window.bunkerDashboard.specialAck();
          handleStateUpdate(response.state);
        });}};
      document.getElementById('viewWelcome').style.display='none';document.getElementById('viewGame').style.display='block';
      updateConnectionBadge('connected');handleStateUpdate(g);
    }""", {'g': g, 'viewer': viewer})
    p.wait_for_timeout(45)


def layout(p, label):
    data = p.evaluate("""() => ({width:innerWidth,height:innerHeight,bodyWidth:document.documentElement.scrollWidth,
      boxes:Object.fromEntries(['myCardsList','dashWorkspace','allPlayersGrid','voteCandidatesGrid','eventChallengeSection',
      'finalScreenSection','finalNeeds','dashActions'].map(id=>{const e=document.getElementById(id),r=e.getBoundingClientRect();
      return [id,{x:r.x,y:r.y,w:r.width,h:r.height,scroll:e.scrollHeight,client:e.clientHeight,width:e.scrollWidth,clientWidth:e.clientWidth}]}))})""")
    data['label'] = label
    LAYOUTS.append(data)
    check(data['bodyWidth'] <= data['width']+1, label+': no horizontal page overflow')
    return data


def command_for(r):
    def command(raw):
        msg=json.loads(raw);a=msg['action'];v=msg.get('payload',{})
        try:
            if a=='USE_SPECIAL_CARD':r.use_special_card('p0',v.get('target_player_id'),category=v.get('category'),categories=v.get('categories'))
            elif a=='REVEAL_CARD':r.reveal_card('p0',v.get('category'))
            elif a=='CAST_VOTE':r.cast_vote('p0',v.get('target_id'))
            elif a=='HOST_SET_PHASE':r.host_set_phase(v['new_phase'])
            elif a=='ENTER_BUNKER':r.enter_bunker('p0')
            elif a=='RESOLVE_EVENT':r.resolve_event()
            else:raise ValueError('Unimplemented test command: '+a)
            return {'state':r.get_state('p0'),'ack':{'action':a,'target_id':v.get('target_id')}}
        except Exception as e:
            return {'error':str(e)}
    return command


def run(browser, out):
    p=boot(browser,1366,768,out)
    p.screenshot(path=str(out/'welcome_1366.png'))
    check(p.locator('#btnCreateRoom').is_visible(),'Welcome: create form visible')
    p.locator('#accessJoin').click()
    check(p.locator('#btnJoinRoom').is_visible() and not p.locator('#btnCreateRoom').is_visible(),'Welcome: join/create switches')
    check(p.locator('link[href*="google"]').count()==0,'No dependency on remote Google fonts')
    r=room(started=False);apply(p,r.get_state('p0'))
    check(p.locator('#lcStart').is_visible() and p.locator('#lcAddBots').is_visible(),'Host lobby: start and bots visible')
    layout(p,'lobby 1366x768');p.screenshot(path=str(out/'lobby_1366.png'))
    apply(p,r.get_state('p1'),'p1')
    check(p.locator('#lc-max_players').is_disabled() and p.locator('#lcGuestNote').is_visible(),'Guest lobby: correct permissions and real waiting status')
    apply(p,r.get_state('observer'),'observer')
    check(p.locator('#spectatorJoinBanner').is_visible(),'Unregistered spectator can join from lobby')
    r=room();r.host_trigger_event();g=r.get_state('p0');apply(p,g)
    check(p.locator('#myCardsList .dossier-item').count()==11,'Eleven own positions are rendered')
    m=layout(p,'speech 1366x768')
    check(m['boxes']['myCardsList']['scroll']<=m['boxes']['myCardsList']['client']+1,'1366x768: all own cards fit without scrolling')
    p.screenshot(path=str(out/'speech_1366.png'))
    p.locator('#dashRoster [data-player="p1"]').click()
    check('Ирина' in p.locator('.dash-focus-header h2').inner_text(),'Manual participant selection')
    tick=copy.deepcopy(g);tick['timer']['seconds_left']=47;apply(p,tick)
    check('Ирина' in p.locator('.dash-focus-header h2').inner_text(),'Selected participant persists across server timer updates')
    p.locator('#dashFindSpeaker').click()
    check('Алекс' in p.locator('.dash-focus-header h2').inner_text(),'Return to current speaker')
    p.locator('#dashViewAll').click()
    check(p.locator('.player-tile').count()==8,'All-participant overview without pages')
    p.locator('#dashViewFocus').click()
    # Malformed presentation fixture intentionally includes values the server normally strips.
    secret=copy.deepcopy(g)
    target=next(x for x in secret['players'] if x['id']=='p1')
    target['cards']['health'].update(value='НЕВИДИМАЯ_КАРТА',details='НЕВИДИМОЕ_ОПИСАНИЕ',mechanics_text='НЕВИДИМАЯ_МЕХАНИКА',revealed=False)
    target['cards']['traitor']={'value':'НЕВИДИМАЯ_РОЛЬ','revealed':False,'details':'SECRET_ROLE'}
    apply(p,secret);p.locator('#dashRoster [data-player="p1"]').click()
    check('НЕВИДИМ' not in p.locator('#allPlayersGrid').inner_html(),'Hidden opponent data never rendered in center')
    p.locator('[data-full-dossier]').click();p.wait_for_timeout(50)
    check('НЕВИДИМ' not in p.locator('#modalPlayerDossier').inner_html(),'Hidden opponent descriptions/mechanics/role not in modal markup')
    check(p.locator('#viewGame').evaluate('(e)=>e.inert'),'Modal makes background inert')
    p.keyboard.press('Tab');check(p.evaluate("document.getElementById('modalPlayerDossier').contains(document.activeElement)"),'Keyboard focus stays in active dialog')
    p.keyboard.press('Escape');p.wait_for_timeout(40)
    check(not p.locator('#modalPlayerDossier').is_visible() and not p.locator('#viewGame').evaluate('(e)=>e.inert'),'Escape closes dialog and unlocks background')
    check(p.evaluate("document.activeElement.hasAttribute('data-full-dossier')"),'Focus returns to invoking button')
    # Timer-only update does not reconstruct existing card element.
    apply(p,g);p.evaluate("window.savedCard=document.querySelector('#myCardsList .dossier-item')")
    apply(p,tick)
    check(p.evaluate("window.savedCard===document.querySelector('#myCardsList .dossier-item')"),'Timer updates preserve card DOM nodes')
    # Event details stay expanded and anchored across relevant updates.
    details=p.locator('#eventChallengeSection details')
    if details.count():
        details.first.evaluate('(e)=>e.open=true');p.locator('.event-scroll').evaluate('(e)=>e.scrollTop=60')
        apply(p,tick)
        check(details.first.evaluate('(e)=>e.open'),'Expanded event factors persist across ticks')
    # Real engine application through UI category picker, with final confirmation.
    r=room();src=next(c for c in deck_data.SPECIAL_CARDS if c['id']=='reroll_dossier_card')
    r.players['p0'].cards['special']={'card_id':src['id'],'value':src['title'],'details':src['desc'],'used':False,'revealed':False}
    apply(p,r.get_state('p0'));p.expose_function('engineCommand',command_for(r));p.evaluate('window.holdTransport=false')
    old=r.players['p0'].cards['hobby']['value']
    p.evaluate("handleUseSpecial(state.gameData.players.find(p=>p.id==='p0').cards.special)")
    p.locator('#targetPickerList .modal-candidate-item').filter(has_text='Хобби').first.click()
    p.locator('#btnTargetPickerConfirm').click()
    check(not r.players['p0'].cards['special']['used'],'Special card waits for explicit final confirmation')
    check('Применить' in p.locator('#btnTargetPickerConfirm').inner_text(),'Special confirmation shows actual destructive/apply action')
    p.locator('#btnTargetPickerConfirm').click()
    p.wait_for_function("state.gameData.players.find(p=>p.id==='p0').cards.special.used")
    check(r.players['p0'].cards['hobby']['value']!=old and not r.players['p0'].cards['hobby']['revealed'],'Category picker applies real server effect; changed hobby remains private')
    p.evaluate("openPlayerDossierModal(state.gameData.players.find(p=>p.id==='p0'))")
    check(p.locator('.dossier-mechanics').count()>=7,'Detailed dossier separates real mechanics from description')
    p.screenshot(path=str(out/'dossier_1366.png'));p.keyboard.press('Escape')
    # Real vote with pending state and response; other voters are not simulated here.
    r.start_voting();r.host_pause_timer(True);r.players['p2'].is_quarantined=True
    apply(p,r.get_state('p0'));p.evaluate('window.holdTransport=true;window.sentCommands=[]')
    check(p.locator('#voteCandidatesGrid .vote-candidate').count()==7,'All seven legal candidates visible, including quarantined target (original rule)')
    p.locator('[data-candidate="p1"] [data-select-vote]').click()
    check(p.evaluate('window.sentCommands.length')==0,'Selecting a candidate never casts the vote')
    p.locator('[data-confirm-vote]').click()
    check('Отправка' in p.locator('.vote-receipt').inner_text() and 'Голос принят' not in p.locator('.vote-receipt').inner_text(),'No optimistic vote success before server acknowledgement')
    check(p.locator('[data-confirm-vote]').is_disabled(),'Pending vote disables duplicate submission')
    check(p.evaluate("window.sentCommands.filter(c=>c.action==='CAST_VOTE').length")==1,'One click produces one command')
    p.evaluate("window.bunkerDashboard.actionError()")
    check(not p.locator('[data-confirm-vote]').is_disabled(),'Server error clears pending state for retry')
    p.evaluate('window.holdTransport=false');p.locator('[data-confirm-vote]').click()
    p.wait_for_function("document.querySelector('.vote-receipt').textContent.includes('Голос принят')")
    check(r.votes['p0']=='p1','Confirmed vote is the actual engine vote')
    apply(p,r.get_state('p0'))
    check('Голос принят: Ирина' in p.locator('.vote-receipt').inner_text(),'Private own-vote receipt survives state refresh / reconnect')
    check('Ирина' not in p.locator('#votingProgressBanner').inner_text(),'Public progress does not reveal vote targets')
    p.screenshot(path=str(out/'voting_1366.png'))
    # Phase transition cancels old modal instead of using stale phase action.
    p.locator('[data-candidate="p1"] [data-vote-details]').click()
    r.host_set_phase('SPEECH');apply(p,r.get_state('p0'))
    check(not p.locator('#modalPlayerDossier').is_visible(),'Phase change closes stale modal')
    # User preference and OS preference.
    p.locator('#dashSettingsButton').click();p.locator('#visualMotion').select_option('minimal')
    check(p.locator('body').get_attribute('data-motion')=='minimal','Minimal-motion preference applies immediately')
    p.locator('#visualMotion').select_option('full');p.emulate_media(reduced_motion='reduce');p.wait_for_timeout(30)
    check(p.locator('body').get_attribute('data-motion')=='calm','Operating-system reduced motion overrides full effects')
    p.emulate_media(reduced_motion='no-preference');p.keyboard.press('Escape')
    # A running game never shows prologue on reconnect.
    p.evaluate('state.prologueShownForRoom=null');apply(p,r.get_state('p0'))
    check(not p.locator('#cinematicPrologueModal').is_visible(),'Reconnect to active speech never replays prologue')
    # Existing prologue rule: host ready starts all; other players only mark ready.
    intro=room(prologue=True);apply(p,intro.get_state('p0'))
    check(p.locator('#cinematicPrologueModal').is_visible(),'Prologue shown only for actual PROLOGUE state')
    p.screenshot(path=str(out/'prologue_1366.png'))
    p.evaluate('window.holdTransport=true');p.locator('#btnPrologueEnter').click()
    check(not p.locator('#cinematicPrologueModal').is_visible(),'Prologue can be skipped without blocking controls')
    p.close()

    # Layout matrix uses actual engine state at each party size; artificial long strings
    # are explicitly stress fixtures, not rebalanced deck content.
    for width,height,count in [(1366,768,12),(1440,900,8),(1920,1080,12),(1280,720,8),(390,844,8),(390,844,12),(683,384,8)]:
        p=boot(browser,width,height,out);rr=room(count);rr.host_trigger_event();game=rr.get_state('p0')
        # Stress realistic long Russian trait value without changing the game deck.
        game['players'][0]['cards']['profession']['value']='Инженер по обслуживанию систем жизнеобеспечения и аварийного электроснабжения'
        game['players'][1]['name']='Александра-Екатерина'
        apply(p,game);label=f'{width}x{height}, {count} players'
        metric=layout(p,'speech '+label)
        if width>=1300:
            c=metric['boxes']['myCardsList'];check(c['scroll']<=c['client']+1,label+': all eleven own cards fit')
            c=metric['boxes']['allPlayersGrid'];check(c['scroll']<=c['client']+1,label+': full center grid fits')
        if width>=1100:
            p.locator('#dashViewAll').click();check(p.locator('.player-tile').count()==count,label+': complete overview')
            overview=layout(p,'overview '+label)
            check(overview['boxes']['allPlayersGrid']['scroll']<=overview['boxes']['allPlayersGrid']['client']+1,label+': overview has no pages/scroll')
            p.screenshot(path=str(out/f'overview_{width}_{count}.png'));p.locator('#dashViewFocus').click()
        else:
            p.locator('[data-mobile-tab="mine"]').click()
            check(p.locator('#dashMine').is_visible() and not p.locator('#dashPlayers').is_visible(),label+': mobile navigation shows one main area')
            check(p.locator('#myCardsList .dossier-item').count()==11,label+': own cards remain one list, no category pages')
        p.screenshot(path=str(out/f'speech_{width}_{count}.png'))
        rr.start_voting();rr.host_pause_timer(True);apply(p,rr.get_state('p0'))
        vm=layout(p,'vote '+label)
        check(p.locator('#voteCandidatesGrid .vote-candidate').count()==count-1,label+': all candidates present')
        check(p.locator('.candidate-details').evaluate_all('(items)=>items.every(e=>{const a=e.getBoundingClientRect(),b=e.parentElement.getBoundingClientRect();return a.bottom<=b.bottom+1&&a.height>=24})'),label+': candidate dossier buttons are fully inside cards')
        if width>=1300:
            c=vm['boxes']['voteCandidatesGrid'];check(c['scroll']<=c['client']+1,label+': all candidates fit with no pages')
            # Event action footer bounds, not just parent visibility.
            footer=p.locator('#eventChallengeSection .event-controls')
            if footer.count():
                b=footer.bounding_box();check(b['y']+b['height']<=height+1,label+': event actions visible within screen')
        p.screenshot(path=str(out/f'voting_{width}_{count}.png'))
        if width<1100:
            p.locator('[data-candidate="p1"] [data-select-vote]').click()
            check(p.locator('[data-confirm-vote]').is_visible(),label+': selecting mobile candidate exposes confirmation')
        # Real final evaluation with intended survivor count, no forced overcapacity.
        for i in range(count//2,count):rr.players[f'p{i}'].is_alive=False
        rr.host_set_phase('FINAL');apply(p,rr.get_state('p0'))
        fm=layout(p,'final '+label)
        check(p.locator('#finalNeeds progress').count()==5,label+': all five needs rendered')
        check(p.locator('#finalSurvivors .final-player').count()==count//2,label+': correct surviving composition')
        if width>=1300:
            n=fm['boxes']['finalNeeds'];check(n['y']+n['h']<=height+1,label+': score and all needs in first screen')
        p.screenshot(path=str(out/f'final_{width}_{count}.png'))
        p.close()

    check(not ERRORS,'No JavaScript exceptions in all verified screens')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--chromium',default='/usr/bin/chromium');parser.add_argument('--output',default=str(ROOT/'visual_results'))
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True);random.seed(90224)
    failure=None
    try:
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
            try:run(b,out)
            finally:b.close()
    except Exception as exc:
        failure=f'{type(exc).__name__}: {exc}'
    report={'passed':failure is None,'mode':'Offline real DOM + real engine in-process actions; NOT a live browser WebSocket match',
            'checks_passed':len(CHECKS),'checks':CHECKS,'javascript_errors':ERRORS,'failure':failure,'layouts':LAYOUTS}
    (out/'visual_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['checks','layouts']},ensure_ascii=False,indent=2))
    if failure:raise SystemExit(1)

if __name__=='__main__':main()
