#!/usr/bin/env python3
"""Age V4.2: own dossier stability with real Chromium DOM and engine snapshots.

The transport is an explicit offline fixture, not a live multiplayer browser
session. Identity, mutations, geometry and animation events are measured, rather
than inferring absence of jitter from a screenshot. No production code is mocked.
"""
from __future__ import annotations
import argparse
import copy
import json
import random
import traceback
from pathlib import Path
from playwright.sync_api import sync_playwright
import verify_visual as visual
from verify_reveal_ui import command_for as reveal_command

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[str] = []
MEASUREMENTS: list[dict] = []


def check(value: bool, name: str) -> None:
    if not value:
        raise AssertionError(name)
    CHECKS.append(name)


def special(room, pid: str, card_id: str) -> None:
    row = next(c for c in visual.deck_data.SPECIAL_CARDS if c['id'] == card_id)
    room.players[pid].cards['special'] = {
        'card_id': card_id, 'value': row['title'], 'details': row['desc'],
        'used': False, 'revealed': False,
    }


def fixture(exiled: bool):
    r = visual.room(6)
    for person in r.players.values():
        for card in person.cards.values():
            card['revealed'] = False
    # A used special makes this the exact reported case: even the availability
    # object is unchanged when someone else completes their opening quota.
    r.players['p0'].cards['special']['used'] = True
    if exiled:
        r.players['p0'].is_alive = False
        for card in r.players['p0'].cards.values():
            card['revealed'] = True
    r.start_reveal_phase()
    if not exiled:
        r.next_reveal_player(force=True)
    r.host_pause_timer(True)
    return r


def probe(page, focus=True) -> None:
    page.wait_for_timeout(200)
    if focus:
        page.locator('#myCardsList [data-open-card="health"]').focus()
    page.evaluate('''() => {
      window.dossierProbe?.observer.disconnect();
      const list=document.getElementById('myCardsList');
      const nodes=[...list.children];
      const rect=e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]};
      const q=window.dossierProbe={nodes,reads:nodes.map(n=>n.querySelector('.card-read')),
        rects:nodes.map(rect),scroll:list.scrollTop,focus:document.activeElement,
        mutations:[],animations:[],maxDelta:0,frames:0,active:true};
      q.observer=new MutationObserver(ms=>q.mutations.push(...ms.map(m=>({
        type:m.type,category:m.target.closest?.('[data-cat]')?.dataset.cat||null,
        added:m.addedNodes.length,removed:m.removedNodes.length
      }))));
      q.observer.observe(list,{childList:true,subtree:true,attributes:true,characterData:true});
      list.onanimationstart=e=>q.animations.push({name:e.animationName,cat:e.target.dataset.cat});
      const tick=()=>{
        if(window.dossierProbe!==q||!q.active)return;
        q.frames++;
        q.nodes.forEach((n,i)=>{if(n.isConnected)rect(n).forEach((x,j)=>q.maxDelta=Math.max(q.maxDelta,Math.abs(x-q.rects[i][j])))});
        requestAnimationFrame(tick);
      };requestAnimationFrame(tick);
    }''')


def read_probe(page) -> dict:
    page.wait_for_timeout(210)
    return page.evaluate('''() => {
      const q=window.dossierProbe,list=document.getElementById('myCardsList');
      q.active=false;q.observer.disconnect();
      return {cards:q.nodes.length,retained:q.nodes.filter(n=>n.isConnected).length,
        readsRetained:q.reads.filter(n=>n.isConnected).length,
        focusRetained:document.activeElement===q.focus,
        scrollBefore:q.scroll,scrollAfter:list.scrollTop,
        animations:q.animations,mutations:q.mutations,maxDelta:q.maxDelta,frames:q.frames,
        transformed:[...list.children].filter(n=>getComputedStyle(n).transform!=='none').length};
    }''')


def stable(page, label: str, zero_mutations=True, geometry=True) -> dict:
    m=read_probe(page);MEASUREMENTS.append({'scenario':label,**m})
    check(m['retained']==m['cards'] and m['readsRetained']==m['cards'],label+': all card/read nodes retained')
    check(m['focusRetained'],label+': keyboard focus retained')
    check(abs(m['scrollBefore']-m['scrollAfter'])<.5,label+': scroll position retained')
    check(not m['animations'] and not m['transformed'],label+': no card entrance/translation animation')
    if zero_mutations:
        check(not m['mutations'],label+': zero DOM mutations in own card list')
    if geometry:
        check(m['maxDelta']<.5 and m['frames']>0,label+': no measured geometry jitter')
    return m


def run(browser, out: Path) -> None:
    # Actual allowed reveals by another player, including quota false -> true.
    for width,height in ((1366,768),(1440,900),(1920,1080),(1280,720),(390,844),(683,384)):
        for exiled in (True,False):
            page=visual.boot(browser,width,height,out)
            r=fixture(exiled);g=r.get_state('p0');visual.apply(page,g)
            if width<1100:
                page.locator('[data-mobile-tab="mine"]').click()
            check(page.locator('#myCardsList .dossier-item').count()==11,f'{width}, exiled={exiled}: eleven cards visible')
            page.locator('#myCardsList').evaluate('(e)=>e.scrollTop=e.scrollHeight')
            probe(page)
            active=g['current_speaker']['id']
            before=copy.deepcopy(g['players'][0]['cards'])
            for cat in ('profession','health','hobby','fact','body')[:g['reveal_status']['required_count']]:
                r.reveal_player_card(active,cat)
                visual.apply(page,r.get_state('p0'))
            after=r.get_state('p0')
            check(after['reveal_status']['quota_reached'] and before==after['players'][0]['cards'],f'{width}, exiled={exiled}: real foreign quota changes, own data unchanged')
            stable(page,f'{width}x{height}, exiled={exiled}: foreign reveals')
            if exiled and width in (1366,390):
                page.screenshot(path=str(out/f'stable_exiled_{width}x{height}.png'))
            # The next participant starts opening; the exile's hint also stays
            # unchanged. Alive players legitimately get a different hint.
            probe(page)
            r.next_reveal_player(force=True);visual.apply(page,r.get_state('p0'))
            stable(page,f'{width}x{height}, exiled={exiled}: next foreign participant',geometry=exiled)
            check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'{width}, exiled={exiled}: no horizontal overflow')
            page.close()

    page=visual.boot(browser,1366,768,out)
    r=fixture(False)
    special(r,'p0','secret_peek')
    g=r.get_state('p0');visual.apply(page,g);probe(page)
    r.reveal_player_card(g['current_speaker']['id'],'profession')
    after=r.get_state('p0')
    check(g['players'][0]['cards']['special']!=after['players'][0]['cards']['special'],'Foreign reveal changes eligible categories of own unused special')
    visual.apply(page,after)
    stable(page,'Own special: only target metadata changed')
    page.locator('#myCardsList [data-special]').click()
    check(page.locator('#modalTargetPicker').is_visible(),'Existing delegated special action still opens target picker')
    page.keyboard.press('Escape')

    # A burst of ordinary server snapshots must not regenerate the list/banner.
    probe(page)
    snap=r.get_state('p0')
    for i in range(30):
        tick=copy.deepcopy(snap);tick['timer']['seconds_left']=59-i
        visual.apply(page,tick)
    stable(page,'Thirty repeated timer snapshots')
    check(page.locator('#timerDigits').inner_text()=='0:30','Timer continues to update independently')

    # Availability is a real visible change: mutate only special button, not cards.
    snap=r.get_state('p0')
    all_open=copy.deepcopy(snap)
    mine=next(p for p in all_open['players'] if p['id']=='p0')
    mine['cards']['special']['available']=False
    mine['cards']['special']['unavailable_reason']='Нет подходящих целей.'
    probe(page);visual.apply(page,all_open)
    stable(page,'Special availability changed',zero_mutations=False)
    check(page.locator('#myCardsList [data-special]').is_disabled(),'Special unavailable state disables existing button')
    check(page.locator('#myCardsList [data-special]').get_attribute('title')=='Нет подходящих целей.','Special disabled reason updated')
    visual.apply(page,snap)
    check(page.locator('#myCardsList [data-special]').is_enabled(),'Special availability restored without stale cache')

    # Real special effects: heal, swap inventory and reroll a hidden card.
    r.players['p0'].cards['health']['severity']='medium'
    r.players['p0'].cards['health']['value']='Хроническое заболевание (контрольная карточка)'
    special(r,'p1','heal_illness');visual.apply(page,r.get_state('p0'));probe(page)
    r.use_special_card('p1','p0');visual.apply(page,r.get_state('p0'))
    stable(page,'Real healing effect',zero_mutations=False)
    check('Исцелён' in page.locator('#myCardsList [data-cat="health"] .dossier-val').inner_text(),'Healing changes own visible health')
    check(page.locator('#myCardsList [data-cat="health"]').get_attribute('class').find('revealed')>=0,'Healing updates public visibility')
    special(r,'p0','swap_baggage')
    old=r.players['p2'].cards['backpack']['value']
    visual.apply(page,r.get_state('p0'));probe(page)
    r.use_special_card('p0','p2',category='backpack');visual.apply(page,r.get_state('p0'))
    stable(page,'Real inventory swap',zero_mutations=False)
    check(page.locator('#myCardsList [data-cat="backpack"] .dossier-val').inner_text()==old,'Swapped inventory uses latest server value')
    check(page.locator('#myCardsList [data-cat="special"] .card-note').inner_text()=='Использована','Special spent status updates')
    check(page.locator('#myCardsList [data-special]').count()==0,'Spent special action removed')

    special(r,'p0','reroll_dossier_card');r.players['p0'].cards['fact']['revealed']=False
    visual.apply(page,r.get_state('p0'));probe(page)
    r.use_special_card('p0',category='fact');visual.apply(page,r.get_state('p0'))
    stable(page,'Real hidden card reroll',zero_mutations=False)
    actual=r.players['p0'].cards['fact']['value']
    check(page.locator('#myCardsList [data-cat="fact"] .dossier-val').inner_text()==actual,'Rerolled fact rendered in stable node')
    check(page.locator('#myCardsList [data-cat="fact"] .card-note').inner_text()=='Только вам','Rerolled hidden fact stays private')
    page.locator('#myCardsList [data-open-card="fact"]').click()
    check(actual in page.locator('#modalPlayerDossier').inner_text(),'Detailed dossier opens latest card, not cached old contents')
    page.keyboard.press('Escape')

    # Dynamic categories must be created/deleted once, without rebuilding others.
    snap=r.get_state('p0');added=copy.deepcopy(snap)
    own=next(p for p in added['players'] if p['id']=='p0')
    own['cards']['stolen_baggage']={'value':'Контрольный трофей','revealed':True,'details':'Динамический слот'}
    probe(page);visual.apply(page,added)
    stable(page,'Trophy category added',zero_mutations=False)
    check(page.locator('#myCardsList [data-cat="stolen_baggage"]').count()==1,'Dynamic trophy added once')
    visual.apply(page,added)
    check(page.locator('#myCardsList [data-cat="stolen_baggage"]').count()==1,'Repeated snapshot does not duplicate trophy')
    visual.apply(page,snap)
    check(page.locator('#myCardsList [data-cat="stolen_baggage"]').count()==0,'Removed dynamic category disappears')
    check(page.locator('#myCardsList .dossier-item').count()==11,'Normal eleven slots restored')

    # Navigation/reconnect must keep the already-fixed automatic mode intact.
    page.locator('#dashRoster [data-player="p4"]').click()
    check(page.locator('#dashFindSpeaker').get_attribute('data-follow-mode')=='manual','Manual dossier pin still works')
    page.locator('#dashFindSpeaker').click()
    check(page.locator('#dashFindSpeaker').get_attribute('data-follow-mode')=='auto','Return to auto retained')
    probe(page);page.evaluate('window.bunkerDashboard.disconnected()');visual.apply(page,r.get_state('p0'))
    stable(page,'Reconnect snapshot')
    r.next_reveal_player(force=True);visual.apply(page,r.get_state('p0'))
    check(page.locator('.dash-focus-header h2').inner_text()==r.get_current_speaker().name,'Automatic following reaches next active player')
    # HTML strings remain escaped after moving to an incremental renderer.
    malformed=copy.deepcopy(r.get_state('p0'))
    own=next(p for p in malformed['players'] if p['id']=='p0')
    own['cards']['fact']['value']='<img src=x onerror="window.badCard=true">'
    visual.apply(page,malformed)
    check(page.locator('#myCardsList [data-cat="fact"] img').count()==0,'Card value rendered as text, never executable markup')
    check(not page.evaluate('Boolean(window.badCard)'),'No injected card handler executed')
    page.close()

    # Actual clicks through delegated event listener and authoritative engine ACK.
    page=visual.boot(browser,1366,768,out);r=visual.room(6)
    for c in r.players['p0'].cards.values():c['revealed']=False
    r.start_reveal_phase();r.host_pause_timer(True);visual.apply(page,r.get_state('p0'))
    page.expose_function('engineCommand',reveal_command(r,'p0'))
    page.locator('#myCardsList [data-reveal="profession"]').focus()
    probe(page,focus=False)
    page.locator('#myCardsList [data-reveal="profession"]').click()
    check(page.evaluate("window.sentCommands.filter(c=>c.action==='REVEAL_CARD').length")==1,'One reveal click issues exactly one command')
    check(page.locator('#myCardsList [data-reveal="profession"]').is_disabled(),'Pending reveal disables double submit')
    check(page.evaluate("document.activeElement?.dataset.openCard==='profession'"),'Pending reveal keeps focus within the same card')
    # Simulate rejected transport first; user can retry without losing panel.
    page.evaluate('window.bunkerDashboard.actionError()')
    check(page.locator('#myCardsList [data-reveal="profession"]').is_enabled(),'Rejected reveal restores action')
    page.evaluate('window.holdTransport=false')
    page.locator('#myCardsList [data-reveal="profession"]').click()
    page.wait_for_function("state.gameData.players.find(p=>p.id==='p0').cards.profession.revealed")
    m=read_probe(page);MEASUREMENTS.append({'scenario':'Own reveal via actual engine binding',**m})
    check(m['retained']==11 and not m['animations'],'Own confirmed reveal updates stable nodes without entrance animation')
    check(page.locator('#myCardsList [data-cat="profession"] .card-note').inner_text()=='Открыто всем','Confirmed reveal is marked public')
    check(page.evaluate("document.activeElement?.dataset.openCard==='profession'"),'Removed reveal action transfers keyboard focus to its own card')
    while not r.get_state('p0')['reveal_status']['quota_reached']:
        cat=next(k for k,c in r.players['p0'].cards.items() if k not in ('special','traitor','stolen_baggage') and not c['revealed'])
        page.locator(f'#myCardsList [data-reveal="{cat}"]').click()
        page.wait_for_function('(cat)=>state.gameData.players.find(p=>p.id==="p0").cards[cat].revealed',arg=cat)
    check(page.locator('#myCardsList [data-reveal]').count()==0,'Quota completion removes all extra reveal actions')
    r.next_reveal_player(force=True);visual.apply(page,r.get_state('p0'))
    check(page.locator('#myCardsList [data-reveal]').count()==0,'No reveal action during another player turn')
    r.start_speech_phase();visual.apply(page,r.get_state('p0'))
    check(page.locator('#myCardsList [data-reveal]').count()==0,'No ordinary reveal action during first speech')
    page.close()
    check(not visual.ERRORS,'No JavaScript exceptions in all dossier stability scenarios')


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--chromium',default='/usr/bin/chromium')
    parser.add_argument('--output',type=Path,default=ROOT/'dossier_stability_results')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    random.seed(442127);failure=None
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
            try:run(browser,args.output)
            finally:browser.close()
    except Exception as exc:
        traceback.print_exc();failure=f'{type(exc).__name__}: {exc}'
    result={'passed':failure is None,'checks_passed':len(CHECKS),'checks':CHECKS,
        'measurements':MEASUREMENTS,'javascript_errors':visual.ERRORS,'failure':failure,
        'transport':'Real Chromium DOM and real engine; explicit offline snapshot/command binding, not live browser WebSockets.'}
    (args.output/'dossier_stability.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('checks','measurements')},ensure_ascii=False,indent=2))
    if failure:raise SystemExit(1)

if __name__=='__main__':main()
