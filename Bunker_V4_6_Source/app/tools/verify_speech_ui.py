"""Actual Chromium assets with a real engine and explicit in-process transport.

WebSocket routing is tested independently in tests_balance/test_speech_api.py.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright
import verify_visual as visual
from server.game_engine import BunkerGameRoom
from server import special_cards as sc, speech_effects as speech

CHECKS=[]


def check(value,label):
    if not value:raise AssertionError(label)
    CHECKS.append(label)


def game():
    r=BunkerGameRoom('SPUI','p0','Алекс')
    for i,name in enumerate(['Ирина','Денис','Мария','Сергей','Лена'],1):r.add_player(f'p{i}',name)
    r.start_game(capacity=2,enable_events=False,skip_prologue=True)
    return r


def give(r,key):
    r.players['p0'].cards['special']={'category':'special','label':'Спецкарта','card_id':key,'value':sc.TITLES[key],
        'details':sc.DEFINITIONS[key][3],'target':sc.DEFINITIONS[key][1],
        'allow_self':sc.DEFINITIONS[key][2],'used':False,'revealed':False}


def run(browser,out):
    p=visual.boot(browser,1366,768,out,include_lobby=False)
    current={'room':None}
    def command(raw,viewer='p0'):
        r=current['room'];msg=json.loads(raw);a=msg['action'];v=msg.get('payload',{})
        try:
            if a=='USE_SPECIAL_CARD':
                r.validate_turn_command(v.get('expected_turn_id'))
                r.use_special_card(viewer,v.get('target_player_id'),categories=v.get('categories'),option_text=v.get('option_text'))
            elif a=='SPEECH_PROMPT':r.send_speech_prompt(viewer,v.get('target_id'),v.get('effect_id'),v.get('index'),v.get('word'))
            else:raise ValueError(a)
            return {'ack':{'action':a},'state':r.get_state(viewer)}
        except Exception as exc:return {'error':str(exc)}
    p.expose_function('engineCommand',command)
    def apply(r,viewer='p0'):
        current['room']=r
        visual.apply(p,r.get_state(viewer),viewer)
        p.evaluate('''()=>{window.holdTransport=false;state.ws.send=raw=>{
          window.sentCommands.push(JSON.parse(raw));window.engineCommand(raw,state.playerId).then(response=>{
            if(response.error){window.bunkerDashboard.actionError();showToast(response.error,'danger');return;}
            if(response.ack.action==='SPEECH_PROMPT')window.bunkerDashboard.promptAck();
            else window.bunkerDashboard.specialAck();
            handleStateUpdate(response.state);
          });};}''')
    def choose(key,option=None):
        p.locator('[data-special]').click()
        p.locator('#targetPickerList').get_by_text('Ирина',exact=True).click()
        p.locator('#btnTargetPickerConfirm').click()
        if option is not None:
            p.locator('#speechOptionInput').fill(option)
            p.locator('#btnTargetPickerConfirm').click()
            check(option in p.locator('#targetPickerPrompt').inner_text(),key+': setting shown before use')
        p.locator('#btnTargetPickerConfirm').click()
        p.wait_for_function("state.gameData.players.find(p=>p.id==='p0').cards.special.used")
    for key in speech.SPEECH_CARDS:
        r=game();give(r,key);apply(r)
        if key=='speech_style':
            p.locator('[data-special]').click();p.locator('#btnTargetPickerConfirm').click()
            p.locator('#btnTargetPickerConfirm').click()
            check(p.locator('.speech-input-error').inner_text()=='Введите текст.','Empty custom input stays open')
            p.evaluate('closeModals()')
            check(not r.players['p0'].cards['special']['used'],'Cancelling does not consume card')
        option={'speech_style':'Как робот <img src=x onerror=alert(1)>','speech_word':'Пельмень','speech_address':'Уважаемый огурец'}.get(key)
        choose(key,option)
        check(r.speech_effects['p1']['card_id']==key,key+': UI applies intended card to intended target')
        r.start_speech_phase();r.host_grant_speech_speaker('p1');apply(r)
        panel=p.locator('#speechEffectsPanel')
        check(panel.is_visible() and sc.TITLES[key] in panel.inner_text(),key+': visible while target speaks')
        check(panel.locator('img').count()==0,key+': custom text is escaped')
        r.next_speaker();apply(r)
        check(panel.is_hidden(),key+': effect disappears after speech')

    # The shared picker still handles existing cards with category selection.
    r=game();give(r,'swap_baggage');apply(r)
    old=r.players['p0'].cards['backpack']['source_id']
    other=r.players['p1'].cards['backpack']['source_id']
    p.locator('[data-special]').click();p.locator('#btnTargetPickerConfirm').click()
    p.locator('#btnTargetPickerConfirm').click();p.locator('#btnTargetPickerConfirm').click()
    p.wait_for_function("state.gameData.players.find(p=>p.id==='p0').cards.special.used")
    check(r.players['p0'].cards['backpack']['source_id']==other and r.players['p1'].cards['backpack']['source_id']==old,'Existing inventory swap picker still works')
    r=game();give(r,'truth_serum');apply(r)
    before=sum(c['revealed'] for c in r.players['p1'].cards.values())
    p.locator('[data-special]').click();p.locator('#btnTargetPickerConfirm').click()
    for _ in range(3):p.locator('#btnTargetPickerConfirm').click()
    p.wait_for_function("state.gameData.players.find(p=>p.id==='p0').cards.special.used")
    check(sum(c['revealed'] for c in r.players['p1'].cards.values())==before+2,'Existing two-category picker still works')

    r=game();give(r,'speech_prompter');apply(r);choose('speech_prompter')
    r.start_speech_phase();r.host_grant_speech_speaker('p1');apply(r)
    field=p.locator('.speech-prompt-form input');field.fill('Кабачок')
    r.timer_seconds_left-=1;apply(r)
    check(field.input_value()=='Кабачок','Timer update preserves typed prompt')
    for i,word in enumerate(['Кабачок','Тапок','Пельмень']):
        field.fill(word);p.locator('.speech-prompt-form button').click()
        p.wait_for_function('(n)=>state.gameData.speech_effects[0].prompts.length===n',arg=i+1)
        check(p.locator('.speech-prompt-list li').count()==i+1,f'Prompt {i+1} is visible')
    check(p.locator('.speech-prompt-form').count()==0,'No fourth prompt control')
    for width,height in [(1366,768),(1280,720),(390,844)]:
        p.set_viewport_size({'width':width,'height':height});apply(r,'p1')
        check(p.locator('#speechEffectsPanel').is_visible(),f'{width}: target sees speech effect')
        check(p.locator('.speech-prompt-form').count()==0,f'{width}: target cannot impersonate prompter')
        check(p.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'{width}: no horizontal overflow')
        p.screenshot(path=str(out/f'speech_{width}.png'))
    p.set_viewport_size({'width':390,'height':844})
    r2=game();give(r2,'speech_prompter');apply(r2)
    p.evaluate("document.querySelector('[data-mobile-tab=mine]').click()")
    choose('speech_prompter');r2.start_speech_phase();r2.host_grant_speech_speaker('p1');apply(r2)
    p.evaluate("document.querySelector('[data-mobile-tab=players]').click()")
    check(p.locator('.speech-prompt-form input').is_visible(),'Mobile author can enter prompt on participants tab')
    p.screenshot(path=str(out/'speech_mobile_author.png'))
    check(not visual.ERRORS,'No browser JavaScript errors')
    p.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--chromium',required=True);args=parser.parse_args()
    out=ROOT.parent/'test-results/speech-ui';out.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=args.chromium,headless=True)
        try:run(browser,out)
        finally:browser.close()
    (out/'report.json').write_text(json.dumps({'checks':CHECKS,'errors':visual.ERRORS},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(CHECKS)} UI checks passed')
