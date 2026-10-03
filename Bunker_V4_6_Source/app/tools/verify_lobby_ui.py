#!/usr/bin/env python3
"""Offline Chromium UI harness using real assets and engine.
Browser HTTP/WebSocket navigation is restricted in the execution environment.
Only transport and asset resolution are replaced by explicit Python bindings.
Real network protocol is tested separately in verify_lobby_network.py.
"""
from __future__ import annotations
import argparse, base64, json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server.game_engine import BunkerGameRoom
from server.lobby import public_catalog
import verify_visual as visual
OUT=ROOT/'lobby_results';OUT.mkdir(exist_ok=True)
CHECKS=[];LAYOUTS=[];ERRORS=[]
def check(v,name):
    if not v:raise AssertionError(name)
    CHECKS.append(name)
def boot(browser,w=1366,h=768):
    p=visual.boot(browser,w,h,OUT,include_lobby=False);p.on('pageerror',lambda e:ERRORS.append(str(e)))
    p.add_style_tag(content=(ROOT/'static/css/lobby.css').read_text())
    p.evaluate('(catalog)=>{window.__lobbyCatalog=catalog;window.fetch=async url=>({ok:true,json:async()=>String(url).includes("lobby-options")?catalog:{local_ip:"127.0.0.1",port:8008}})}',public_catalog())
    p.evaluate('(images)=>window.__lobbyImages=images',{f.stem:'data:image/jpeg;base64,'+base64.b64encode(f.read_bytes()).decode() for f in (ROOT/'static/images/catastrophes').glob('*.jpg')})
    source=(ROOT/'static/js/lobby.js').read_text()
    source=source.replace("url('/static/images/catastrophes/${cat.id}.jpg')", "url('${window.__lobbyImages[cat.id]}')")
    p.add_script_tag(content=source);p.evaluate("window.holdTransport=false")
    return p

def apply(p,r,viewer='host'):
    p.evaluate('''({g,viewer})=>{
      state.roomCode=g.room_code;state.playerId=viewer;state.playerName=g.players.find(p=>p.id===viewer)?.name||'Наблюдатель';state.isHost=g.is_host;
      state.ws={readyState:1,send:raw=>{window.sentCommands.push(JSON.parse(raw));
        if(window.holdTransport)return;
        window.engineCommand(raw,viewer).then(result=>{
          const msg=result.error?{type:'ERROR',action:result.action,message:result.error}:{type:'ACTION_OK',...result.ack};
          window.bunkerLobby.onMessage(msg);
          if(result.error)showToast(result.error,'danger');
          if(result.state)handleStateUpdate(result.state);
        });}};
      document.getElementById('viewWelcome').style.display='none';document.getElementById('viewGame').style.display='block';
      updateConnectionBadge('connected');handleStateUpdate(g);
    }''',{'g':r.get_state(viewer),'viewer':viewer});p.wait_for_timeout(35)

def dispatch(r):
    def run(raw,viewer):
        msg=json.loads(raw);a=msg['action'];v=msg.get('payload',{});ack={'action':a}
        try:
            if a=='UPDATE_LOBBY_SETTINGS':r.update_lobby_settings(viewer,v['settings'],v.get('expected_revision'));ack['revision']=r.lobby_revision
            elif a=='SET_LOBBY_READY':r.set_lobby_ready(viewer,v['ready'],v.get('expected_revision'))
            elif a=='START_GAME':r.start_configured_game(viewer,v.get('expected_revision'));r.host_pause_timer(True)
            elif a=='ADD_BOTS':
                if viewer!=r.host_id:raise ValueError('Только ведущий')
                for i in range(v['count']):r.add_player(f'bot_{len(r.players)}',f'Бот {len(r.players)}')
                ack['added']=v['count']
            elif a=='REMOVE_BOTS':
                if viewer!=r.host_id:raise ValueError('Только ведущий')
                for pid in list(r.players):
                    if pid.startswith('bot_'):r.remove_player(pid)
            elif a=='HOST_KICK':r.remove_player(v['player_id'])
            else:raise ValueError('Unsupported UI-harness command: '+a)
            return {'ack':ack,'state':r.get_state(viewer)}
        except Exception as ex:return {'error':str(ex),'action':a,'state':r.get_state(viewer)}
    return run

def saved(p):p.wait_for_function("document.getElementById('lcSync').textContent==='Настройки сохранены'")
def setting(p,key,value):
    el=p.locator('#lc-'+key)
    if el.get_attribute('type')=='checkbox':el.set_checked(value)
    elif el.get_attribute('type')=='number':el.fill(str(value));el.press('Tab')
    else:el.select_option(str(value))
    p.wait_for_function('([k,v])=>state.gameData.lobby.settings[k]===v',arg=[key,value]);saved(p)

def layout(p,name,default=False):
    p.evaluate("document.getElementById('lcMessage').hidden=true;document.getElementById('toastContainer').innerHTML='';document.getElementById('lcSettingsScroll').scrollTop=0")
    m=p.evaluate('''()=>({viewport:[innerWidth,innerHeight],doc:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],footer:document.querySelector('.lc-footer').getBoundingClientRect().toJSON(),scroll:['lcSettingsScroll','lcRoster'].map(id=>{let x=document.getElementById(id);return {id,client:x.clientHeight,scroll:x.scrollHeight}})})''')
    LAYOUTS.append({'name':name,**m});p.screenshot(path=str(OUT/(name+'.png')),full_page=True)
    check(m['doc'][0]<=m['viewport'][0]+1,name+': no horizontal overflow')
    if m['viewport'][0]>=1100 and m['viewport'][1]>=720:
        check(m['doc'][1]<=m['viewport'][1]+1,name+': no desktop page scroll')
        check(m['footer']['bottom']<=m['viewport'][1]+1,name+': launch footer visible')
        if default:check(m['scroll'][0]['scroll']<=m['scroll'][0]['client']+1,name+': all primary settings fit')
    return m

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--chromium',default='/usr/bin/chromium');args=ap.parse_args();error=None
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
        try:
            p=boot(browser);r=BunkerGameRoom('LBV2','host','Алекс');p.expose_function('engineCommand',dispatch(r));apply(p,r)
            check(p.locator('#lc-deal_mode').input_value()=='full_random','Full random is selected by default')
            check('Полный рандом' in p.locator('#lcBriefRules').inner_text(),'Brief shows the actual deal mode')
            setting(p,'deal_mode','balanced')
            check('медик и техник' in p.locator('#lcDealHelp').inner_text(),'Balanced mode explains its guarantees')
            setting(p,'deal_mode','full_random')
            check('Без обязательных профессий' in p.locator('#lcDealHelp').inner_text(),'Random mode explains the lack of guarantees')
            check(p.locator('#lcStart').is_disabled(),'Launch blocked before third player')
            for pid,name in [('p1','Екатерина'),('p2','Максим')]:r.add_player(pid,name)
            apply(p,r);p.locator('#lcFillBots').click();p.wait_for_function('state.gameData.total_players===6');saved(p)
            check(len(r.players)==6,'Fill-to-six button dispatches correct bot count (test binding)')
            p.locator('#lcBotNumber').fill('2');p.locator('#lcAddBots').click();p.wait_for_function('state.gameData.total_players===8');saved(p)
            setting(p,'require_ready',True)
            check(p.locator('#lcStart').is_disabled(),'Ready gate blocks unready guests')
            guest=boot(browser);guest.expose_function('engineCommand',dispatch(r));apply(guest,r,'p1')
            check(guest.locator('#lc-max_players').is_disabled(),'Guest settings read-only')
            check(guest.locator('#lcStart').is_hidden(),'Guest cannot start')
            check(guest.locator('#lcAddBots').is_hidden(),'Guest cannot add bots')
            guest.locator('#lcReady').click();guest.wait_for_function('state.gameData.lobby.ready[state.playerId]');r.set_lobby_ready('p2',True,r.lobby_revision);apply(p,r)
            check(p.locator('#lcStart').is_enabled(),'Actual engine readiness unlocks launch button')
            layout(p,'lobby_general_1366x768',True)
            p.locator('[data-preset="discussion"]').click();p.wait_for_function('state.gameData.lobby.settings.speech_duration===90');saved(p)
            check(not r.lobby_ready,'Preset resets old ready confirmations')
            p.locator('#lc-tab-rules').click();setting(p,'speech_duration',120);setting(p,'voting_duration',45);setting(p,'justification_duration',60);setting(p,'revote_duration',25);setting(p,'last_word_duration',35)
            check(p.locator('#lcSecondSpeech').inner_text().startswith('60'),'Second speech live preview = half first')
            setting(p,'initial_reveal','profession');setting(p,'speaker_order','random');layout(p,'lobby_rules_1366x768')
            p.locator('#lc-tab-scenario').click();setting(p,'catastrophe_id','nuclear_winter');setting(p,'bunker_id','bunker_00');setting(p,'event_difficulty','hard');setting(p,'show_prologue',False)
            apply(guest,r,'p1');check(guest.locator('#lcSceneTitle').inner_text()=='Ядерная зима','Guest preview reflects common scenario snapshot')
            layout(p,'lobby_scenario_1366x768')
            p.locator('#lc-tab-general').click();setting(p,'capacity_mode','manual');setting(p,'capacity',3);setting(p,'max_players',12)
            p.locator('#lcLockRoom').click();p.wait_for_function('state.gameData.lobby.settings.room_locked');saved(p)
            check('закрыт' in p.locator('#lcLockBadge').inner_text(),'Lock button reflects server acknowledgement')
            p.locator('#lcLockRoom').click();p.wait_for_function('!state.gameData.lobby.settings.room_locked');saved(p)
            # Validate profile upload in the actual JavaScript parser, then Python validator.
            profile={'app':'bunker-lobby','schema_version':1,'settings':{**r.lobby_settings,'voting_duration':40}}
            p.locator('#lcProfileFile').set_input_files({'name':'profile.json','mimeType':'application/json','buffer':json.dumps(profile).encode()});p.wait_for_function('state.gameData.lobby.settings.voting_duration===40');saved(p)
            check(r.voting_duration_sec==40,'JSON import is applied to the engine, not only form')
            before=r.lobby_settings.copy()
            p.locator('#lcProfileFile').set_input_files({'name':'invalid.json','mimeType':'application/json','buffer':json.dumps({'app':'bunker-lobby','schema_version':1,'settings':{'speech_duration':5}}).encode()});p.wait_for_function("document.getElementById('lcMessage').classList.contains('is-error')")
            check(r.lobby_settings==before,'Invalid settings import is atomic')
            # Export intercepted at the browser Blob boundary because downloads are restricted.
            p.evaluate("window.savedBlob=null;window.URL.createObjectURL=(blob)=>{window.savedBlob=blob;return 'blob:test';};HTMLAnchorElement.prototype.click=function(){};")
            p.locator('#lcSaveProfile').click();exported=json.loads(p.evaluate('window.savedBlob.text()'))
            check(exported['settings']['voting_duration']==40 and 'room_code' not in exported and 'host_token' not in exported['settings'],'Profile export contains current settings without credentials')
            p.evaluate("document.getElementById('lcMessage').hidden=true")
            for w,h in [(1440,900),(1920,1080),(1280,720)]:p.set_viewport_size({'width':w,'height':h});layout(p,f'lobby_general_{w}x{h}',True)
            apply(guest,r,'p1');layout(guest,'lobby_guest_1366x768')
            p.set_viewport_size({'width':390,'height':844});layout(p,'lobby_mobile_settings_390x844');p.locator('[data-lc-mobile="crew"]').click();layout(p,'lobby_mobile_crew_390x844');p.locator('[data-lc-mobile="brief"]').click();layout(p,'lobby_mobile_brief_390x844')
            p.set_viewport_size({'width':1366,'height':768});p.locator('[data-lc-mobile="settings"]').evaluate('(e)=>e.click()')
            # Escaping of public names protects the roster HTML.
            r.players['p2'].name='<img src=x onerror=alert(1)>';apply(p,r);check(p.locator('#lcRoster img').count()==0,'Player names escaped, never HTML')
            r.players['p2'].name='Максим';apply(p,r)
            p.locator('#lc-tab-rules').focus();p.keyboard.press('Home');check(p.locator('#lc-pane-general').is_visible(),'Keyboard navigation between settings tabs')
            # Holding response validates disabled start and absence of optimistic save.
            p.evaluate('window.holdTransport=true');setting_el=p.locator('#lc-enable_traitor');setting_el.check();check(p.locator('#lcStart').is_disabled(),'Pending settings keep launch disabled');check('Сохраняем' in p.locator('#lcSync').inner_text(),'Unconfirmed edit is not reported as saved')
            p.evaluate("window.bunkerLobby.onMessage({type:'ERROR',action:'UPDATE_LOBBY_SETTINGS',message:'Проверочная ошибка'})");p.evaluate('window.holdTransport=false');apply(p,r)
            # Disconnect state cannot report readiness/start as successful.
            p.evaluate('state.ws.readyState=3;window.bunkerLobby.disconnected()');check(p.locator('#lcStart').is_disabled(),'Disconnected host cannot launch');check('Связь' in p.locator('#lcSync').inner_text(),'Disconnection shown truthfully');apply(p,r)
            r.set_lobby_ready('p1',True,r.lobby_revision);r.set_lobby_ready('p2',True,r.lobby_revision);apply(p,r)
            p.locator('#lcStart').click();p.wait_for_function("state.gameData.phase==='REVEAL'")
            check(r.catastrophe['id']=='nuclear_winter' and r.bunker['name']=='Командный пункт «Гранит»','Engine deal uses selected scenario')
            check((r.speech_duration_sec,r.accusation_duration_sec,r.voting_duration_sec)==(120,60,40),'Timers from UI reach the real engine')
            check((r.justification_duration_sec,r.revote_duration_sec,r.last_word_duration_sec)==(60,25,35),'Extra timers from UI reach engine')
            check(r.bunker_capacity==3,'Capacity reaches the actual deal')
            check(r.match_settings['deal_mode']=='full_random','Selected random mode reaches the actual game')
            check(all(x.cards['profession']['revealed'] for x in r.players.values()),'Initial profession reveal reaches every dealt dossier')
            check(p.locator('#lobbyControlRoom').is_hidden() and p.locator('#myCardsList').is_visible(),'Launch transitions from new lobby to existing game UI')
            p.screenshot(path=str(OUT/'game_after_lobby_1366x768.png'))
            r.start_accusation_phase();apply(p,r)
            check('60' in p.locator('#speakerRevealBadge').inner_text(),'Second-speech explanation uses configured duration')
            r.start_voting();apply(p,r)
            check('40' in p.locator('#timerDigits').inner_text(),'Voting timer displays configured duration')
            r.start_justification(['p1','p2'],True,[],50);apply(p,r)
            check(r.timer_seconds_left==60,'Actual justification phase uses configured duration')
            r.start_revote();apply(p,r)
            check(r.timer_seconds_left==25,'Actual revote phase uses configured duration')
            check(not ERRORS and not visual.ERRORS,'No uncaught JavaScript errors')
        except Exception as exc:
            error=f'{type(exc).__name__}: {exc}'
            try:p.screenshot(path=str(OUT/'failure.png'),full_page=True)
            except Exception:pass
        finally:browser.close()
    (OUT/'browser_ui.json').write_text(json.dumps({'passed':len(CHECKS),'checks':CHECKS,'errors':ERRORS+visual.ERRORS,'failure':error,'layouts':LAYOUTS,'transport':'Explicit test binding to real Python game engine; not a live browser match'},ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passed':len(CHECKS),'errors':ERRORS+visual.ERRORS,'failure':error},ensure_ascii=False,indent=2))
    if error:raise SystemExit(1)
if __name__=='__main__':main()
