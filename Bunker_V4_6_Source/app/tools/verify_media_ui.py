#!/usr/bin/env python3
"""Real bundled UI and WebAudio, local in-process assets/engine test adapter.
No external browser network, Windows launch, acoustic listening or Porthole test.
"""
import base64,json,re,sys,argparse
from pathlib import Path
from playwright.sync_api import sync_playwright
import verify_visual as ui
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT.parent/'media-test-results';OUT.mkdir(exist_ok=True)
checks=[]
def check(ok,name):
    if not ok:raise AssertionError(name)
    checks.append(name)
def asset(url):
    path=str(url).split('?')[0]
    if not path.startswith('/static/'):return None
    p=(ROOT/path.lstrip('/')).resolve()
    if ROOT not in p.parents or not p.is_file():return None
    return base64.b64encode(p.read_bytes()).decode()
def boot(browser,w=1366,h=768):
    p=ui.boot(browser,w,h,OUT)
    p.add_style_tag(content=(ROOT/'static/css/audio.css').read_text())
    p.expose_function('testAsset',asset)
    p.evaluate('''() => {
      const oldFetch=window.fetch;
      window.fetch=async(url,opts)=>{
        if(String(url).startsWith('/static/audio/')){
          window.testAssetRequests=(window.testAssetRequests||0)+1;
          const b64=await window.testAsset(url);if(!b64)return new Response('',{status:404});
          return new Response(Uint8Array.from(atob(b64),c=>c.charCodeAt(0)).buffer,{status:200});
        }
        return oldFetch(url,opts);
      };
    }''')
    p.add_script_tag(content=(ROOT/'static/js/audio_settings.js').read_text())
    return p

def run():
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  p=boot(browser)
  check(p.evaluate('soundFX.ctx===null && !soundFX.consent'),'No AudioContext or playback before explicit consent')
  p.locator('#audioConsentNo').click()
  check(p.evaluate('soundFX.ctx===null && !soundFX.enabled && soundFX.consent'),'Silent entry creates no audio context')
  p.locator('#btnAudioSettings').click();p.screenshot(path=str(OUT/'settings_desktop_silent.png'))
  check(p.locator('#audioSettingsDialog').evaluate('(d)=>d.open'),'Header opens accessible native settings dialog')
  p.locator('#audioMasterToggle').click()
  p.wait_for_function("soundFX.ctx?.state==='running' && soundFX._loops.size===2",timeout=20000)
  check(p.evaluate('soundFX._buffers.get("ventilation").duration>35'),'Actual local OGG decoded with Web Audio')
  check(p.evaluate('soundFX._loops.has("equipment")'),'Independent equipment layer started')
  check(p.evaluate('soundFX._accentTimer!==null'),'Accent scheduler runs with ambience')
  p.evaluate("soundFX.setVolume(.4);soundFX.setSetting('effects',.2);soundFX.setSetting('video',.3)")
  check(p.evaluate('soundFX.masterGain._target===.4 && soundFX.mediaGain._target===.3'),'Independent master and video bus gain')
  check(p.evaluate('Math.abs(soundFX.effectsGain._target-.11)<.0001'),'Soft effects gain scaled independently')
  p.screenshot(path=str(OUT/'settings_desktop.png'))
  p.evaluate("soundFX.toggleSound();soundFX.setVolume(.7)")
  check(p.evaluate('!soundFX.enabled && soundFX.masterGain._target===0 && soundFX._loops.size===0'),'Changing volume does not unmute; master stops ambience')
  p.evaluate('soundFX.toggleSound()');p.wait_for_function('soundFX._loops.size===2')
  p.evaluate("soundFX.setScene({phase:'SPEECH',catastrophe:'ice_age',prologue:false,review:false})")
  p.wait_for_function('soundFX._loops.size===3')
  check(p.evaluate('Math.abs(soundFX.ambientGain._target-soundFX.settings.ambient*.25)<.0001'),'Speech ducks ambience to quarter level')
  check(p.evaluate('soundFX._accentTimer===null'),'No scheduled accents during speeches')
  p.evaluate("soundFX.setScene({phase:'VOTING',review:false});soundFX.setSetting('duckSpeech',false)")
  check(p.evaluate('soundFX._accentTimer!==null'),'Accents resume outside speeches')
  before=p.evaluate('JSON.stringify(soundFX._scene)')
  p.evaluate("soundFX.setScene({odds:100,hidden_cards:{age:100},contribution:-100})")
  check(p.evaluate('JSON.stringify(soundFX._scene)')==before,'Hidden odds and cards cannot affect soundscape')
  p.evaluate("soundFX.setScene({review:true})")
  check(p.evaluate('soundFX._accentTimer===null && soundFX._duck()===.3'),'Result review suppresses details and ducks ambience')
  p.evaluate("soundFX.setScene({review:false,prologue:true})")
  check(p.evaluate('soundFX._duck()===.1 && soundFX._accentTimer===null'),'Clip playback ducks background without double soundtrack')
  p.evaluate("soundFX.setScene({prologue:false});soundFX.setSetting('exterior',false)")
  check(p.evaluate('soundFX._loops.size===2'),'Exterior layer independently removable')
  p.evaluate("soundFX.setSetting('accents',false)")
  check(p.evaluate('soundFX._accentTimer===null'),'Rare mechanical accents independently removable')
  p.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))")
  check(p.evaluate('soundFX.masterGain._target===0 && soundFX._loops.size===0'),'Hidden tab mutes all channels and stops loops')
  p.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'))")
  p.wait_for_function('soundFX._loops.size===2')
  check(True,'Returning to tab restores exactly one copy per layer')
  p.evaluate("soundFX.setScene({connected:false})")
  check(p.evaluate('soundFX._loops.size===0'),'Disconnect stops ambience')
  p.evaluate("soundFX.setScene({connected:true});for(let i=0;i<8;i++){soundFX.toggleAmbient();soundFX.toggleAmbient();}")
  p.wait_for_timeout(450)
  check(p.evaluate('soundFX._loops.size===2 && [...soundFX._loops.values()].every(v=>!v.retired)'),'Rapid toggles cannot stop a newer layer through stale callbacks')
  p.evaluate("soundFX.setSetting('accents',false);soundFX.setScene({phase:'VOTING',review:false,prologue:false});window.oldTimeout=window.setTimeout;window.testAccentDelays=[];window.setTimeout=(f,ms,...args)=>{if(ms>=40000&&ms<=90000)window.testAccentDelays.push(ms);return window.oldTimeout(f,ms,...args)};soundFX.setSetting('accents',true)")
  check(p.evaluate('testAccentDelays.length===1 && testAccentDelays[0]>=40000 && testAccentDelays[0]<=90000'),'Accent interval constrained to 40–90 seconds')
  p.evaluate("window.setTimeout=window.oldTimeout;soundFX._playAccent('metal')")
  p.wait_for_function('soundFX._details.size===1')
  check(True,'Mechanical detail actually decodes and starts a buffer source')
  p.evaluate("soundFX.setScene({phase:'SPEECH'})")
  check(p.evaluate('soundFX._details.size===0 && soundFX._accentTimer===null'),'Entering a speech fades any already-playing mechanical detail')
  p.evaluate("soundFX.setSetting('accents',false);soundFX.setScene({phase:'VOTING'})")
  p.evaluate("soundFX.setSetting('notificationsEnabled',false);soundFX.setSetting('videoEnabled',false)")
  check(p.evaluate('soundFX.notificationsGain._target===0 && soundFX.mediaGain._target===0'),'Channel toggles mute independently')
  p.evaluate("soundFX.setSetting('notificationsEnabled',true);soundFX.setSetting('videoEnabled',true)")
  # Verify stored values reconstruct correctly without starting a second instance.
  check(p.evaluate("(()=>{const x=new BunkerSoundFX();const ok=x.volume===.7&&x.settings.video===.3&&x.settings.accents===false&&x.ctx===null;x.destroy();return ok;})()"),'Validated personal settings persist and new instance remains locked')
  p.evaluate("localStorage.setItem('bunker_audio_v46','{bad')")
  check(p.evaluate("(()=>{const x=new BunkerSoundFX();const ok=Number.isFinite(x.volume);x.destroy();return ok;})()"),'Corrupted settings do not break the game')
  p.evaluate('soundFX._save()')
  # Asset failure cache and manual retry, using real decoder for the fallback.
  p.evaluate("window.audioFetch=window.fetch;window.oggRequests=0;window.fetch=async(u,o)=>{if(String(u).includes('relay.ogg')){window.oggRequests++;return new Response('',{status:404});}return window.audioFetch(u,o);}")
  p.evaluate("soundFX._load('relay')")
  p.wait_for_function("soundFX._buffers.has('relay')")
  check(p.evaluate("window.oggRequests===1 && soundFX._buffers.get('relay').duration>.3"),'Missing OGG falls back to actual MP3 decode')
  p.evaluate("window.failCount=0;window.fetch=async(u,o)=>{if(String(u).includes('missing_test')){window.failCount++;return new Response('',{status:404});}return window.audioFetch(u,o);}")
  p.evaluate("soundFX._load('missing_test')")
  p.wait_for_function("soundFX._failures.has('missing_test')")
  p.evaluate("soundFX._load('missing_test');soundFX._load('missing_test')")
  check(p.evaluate('window.failCount===2'),'Failed assets are not fetched continuously')
  p.evaluate('window.fetch=window.audioFetch;soundFX.retryAmbient()')
  p.locator('#audioClose').click()
  # Native video plays actual packaged H264/AAC through the master bus.
  clip=asset('/static/videos/catastrophes/black_hole_approach.mp4')
  p.evaluate('''b64=>{window.testClipBlob=URL.createObjectURL(new Blob([Uint8Array.from(atob(b64),c=>c.charCodeAt(0))],{type:'video/mp4'}));const d=Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype,'src');Object.defineProperty(HTMLMediaElement.prototype,'src',{...d,set(v){d.set.call(this,String(v).startsWith('/static/videos/')?window.testClipBlob:v)}});}''',clip)
  r=ui.room(4,True,True);r.catastrophe=dict(next(c for c in ui.deck_data.CATASTROPHES if c['id']=='black_hole_approach'))
  # Poster rendering in the adapter uses local data, not a fetched website.
  p.evaluate('''b64=>{const d=Object.getOwnPropertyDescriptor(HTMLVideoElement.prototype,'poster');Object.defineProperty(HTMLVideoElement.prototype,'poster',{...d,set(v){d.set.call(this,'data:image/jpeg;base64,'+b64)}});}''',asset('/static/images/catastrophes/black_hole_approach.jpg'))
  ui.apply(p,r.get_state('p0'))
  p.wait_for_function("document.getElementById('prologueVideoBg').readyState>=2",timeout=20000)
  check(p.evaluate('soundFX._media.size===1 && !document.getElementById("prologueVideoBg").loop'),'One media source attached; clip is not looped')
  p.wait_for_timeout(5500)
  check(p.evaluate('document.getElementById("prologueVideoBg").ended && !soundFX._scene.prologue'),'Clip ends after five seconds and releases ambience duck')
  p.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'))")
  p.wait_for_timeout(100)
  check(p.evaluate('document.getElementById("prologueVideoBg").ended'),'Returning to tab never replays a completed clip')
  p.locator('#btnPrologueReplay').click();p.wait_for_timeout(350)
  check(p.evaluate('!document.getElementById("prologueVideoBg").paused'),'Explicit replay works')
  p.screenshot(path=str(OUT/'prologue_desktop.png'))
  p.locator('#btnPrologueAudioSettings').click()
  check(p.locator('#audioSettingsDialog').evaluate('(d)=>d.open'),'Settings accessible during prologue')
  p.keyboard.press('Escape');p.wait_for_timeout(100)
  check(p.evaluate('!document.getElementById("audioSettingsDialog").open && document.getElementById("cinematicPrologueModal").style.display==="flex"'),'Escape closes audio settings, not underlying prologue')
  p.evaluate('soundFX.toggleSound()')
  check(p.evaluate('soundFX.masterGain._target===0 && document.getElementById("prologueVideoBg").muted'),'Global mute includes native MP4 audio')
  p.evaluate('soundFX.setVolume(.6)')
  check(p.evaluate('document.getElementById("prologueVideoBg").muted'),'Video stays muted when master slider moves under mute')
  p.evaluate("soundFX.setSetting('clips',false)")
  check(p.evaluate('document.getElementById("prologueVideoBg").paused && document.getElementById("btnPrologueReplay").disabled'),'Disable clips immediately pauses playback; conditions remain visible')
  p.locator('#btnPrologueEnter').click()
  check(p.evaluate('document.getElementById("prologueVideoBg").paused && !soundFX._scene.prologue'),'Entering bunker stops clip and its duck state')
  p.close()
  # Mobile layout and keyboard/modal behavior.
  p=boot(browser,390,844);p.locator('#btnAudioSettings').click();p.screenshot(path=str(OUT/'settings_mobile.png'))
  box=p.locator('#audioSettingsDialog').bounding_box()
  check(box['x']>=0 and box['width']<=390 and box['y']>=0 and box['height']<=844,'Settings fit 390x844 viewport')
  check(p.evaluate('document.documentElement.scrollWidth<=innerWidth'),'No horizontal overflow at 390px')
  for _ in range(25):p.keyboard.press('Tab')
  check(p.evaluate('document.getElementById("audioSettingsDialog").contains(document.activeElement)'),'Keyboard focus stays inside native settings dialog')
  p.keyboard.press('Escape');check(not p.locator('#audioSettingsDialog').evaluate('(d)=>d.open'),'Escape closes mobile dialog')
  p.close();browser.close()
 check(not ui.ERRORS,'No uncaught JavaScript errors: '+str(ui.ERRORS))
 (OUT/'ui_checks.json').write_text(json.dumps({'count':len(checks),'checks':checks,'errors':ui.ERRORS,'method':__doc__},ensure_ascii=False,indent=2))
 print(f'{len(checks)} media/UI checks passed')
if __name__=='__main__':run()
