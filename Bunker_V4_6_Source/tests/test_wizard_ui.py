"""Actual wizard assets, explicit test-only HTTP bridge; does not alter browser policy."""
import json,re,time,argparse
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright
parser=argparse.ArgumentParser();parser.add_argument('--instance',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
OUT=Path(args.output);OUT.mkdir(parents=True,exist_ok=True);ROOT=Path(__file__).resolve().parents[1]/'launcher/ui'
d=json.loads(Path(args.instance).read_text());headers={'X-Bunker-Token':d['token']}
# Set helper to idle before tests (only test instance, not a user's process).
requests.post(d['origin']+'/api/stop',headers=headers,json={})
report={'transport':'explicit Python HTTP bridge into the live test helper; Chromium navigation is blocked by environment policy','checks':[],'errors':[]}
def ok(name,value):
 report['checks'].append({'name':name,'ok':bool(value)})
 assert value,name
def bridge(path,opts):
 r=requests.request(opts.get('method','GET'),d['origin']+path,headers=opts.get('headers',{}),data=opts.get('body'),timeout=10)
 return {'status':r.status_code,'text':r.text}
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 page=b.new_page(viewport={'width':1366,'height':900});page.on('pageerror',lambda e:report['errors'].append(str(e)));page.on('dialog',lambda d:d.accept())
 try:
  html=ROOT.joinpath('index.html').read_text();html=re.sub(r'<link[^>]+>','',html);html=re.sub(r'<script[^>]+></script>','',html)
  page.set_content(html);page.add_style_tag(content=ROOT.joinpath('wizard.css').read_text())
  page.expose_function('httpBridge',bridge)
  page.evaluate('''token=>{location.hash='token='+token;window.fetch=async(path,opts={})=>{const r=await window.httpBridge(String(path),opts);return new Response(r.text,{status:r.status,headers:{'Content-Type':'application/json'}});};}''',d['token'])
  page.add_script_tag(content=ROOT.joinpath('wizard.js').read_text());page.wait_for_timeout(350)
  ok('wizard opens',page.locator('h1').inner_text()=='Соберите людей у шлюза.')
  ok('four modes',page.locator('[data-mode]').count()==4)
  ok('two roles',page.locator('[data-role]').count()==2)
  ok('no overflow desktop',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
  page.screenshot(path=str(OUT/'wizard_initial_1366.png'),full_page=True)
  # Simulate unprepared state only for display/consent coverage; no download attempted.
  page.evaluate('runtimeReady=false;renderForm()')
  ok('first-run consent visible',page.locator('#downloadNote').is_visible());page.screenshot(path=str(OUT/'wizard_first_run_1366.png'),full_page=True)
  page.locator('[data-role="guest"]').click();ok('guest skips runtime consent',not page.locator('#downloadNote').is_visible())
  page.locator('#port').fill('8008');page.locator('#start').click();page.wait_for_timeout(400)
  ok('guest URL generated',page.locator('#openGame').get_attribute('href')=='http://127.0.0.1:8008/')
  data=requests.get(d['origin']+'/api/status',headers=headers).json();ok('guest no game server',data['phase']=='guest')
  page.screenshot(path=str(OUT/'wizard_guest_1366.png'),full_page=True)
  for mode in ('lan','vpn','public','porthole'):
   page.locator(f'[data-mode="{mode}"]').click();ok('guide '+mode,page.locator('#steps li').count()>=3)
  page.locator('[data-role="host"]').click();page.locator('#port').fill('18008');page.locator('#start').click()
  page.wait_for_function("document.getElementById('statusTitle').textContent==='Сервер работает'",timeout=15000)
  ok('live helper starts real server',requests.get('http://127.0.0.1:18008/api/health').json()['application']=='bunker')
  ok('host game URL',page.locator('#openGame').get_attribute('href')=='http://127.0.0.1:18008')
  ok('settings locked while running',page.locator('[data-mode="lan"]').is_disabled())
  page.screenshot(path=str(OUT/'wizard_running_1366.png'),full_page=True)
  page.locator('#stop').click();page.wait_for_timeout(400)
  ok('stop confirmed',requests.get(d['origin']+'/api/status',headers=headers).json()['phase']=='idle')
  page.locator('[data-role="guest"]').click();page.locator('[data-mode="lan"]').click();page.locator('#address').fill('ABCD');page.locator('#start').click();page.wait_for_timeout(400)
  ok('room code rejected as address',page.locator('#error').is_visible())
  page.locator('[data-mode="porthole"]').click();page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'wizard_mobile_390.png'),full_page=True)
  ok('mobile no overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
  h=b.new_page(viewport={'width':1366,'height':900});h.set_content(re.sub(r'<link[^>]+>','',ROOT.joinpath('help.html').read_text()));h.add_style_tag(content=ROOT.joinpath('help.css').read_text());ok('all manual sections',all(h.locator('#'+s).count()==1 for s in ['first','porthole','lan','vpn','public','game','problems']));h.screenshot(path=str(OUT/'help_1366.png'));h.close()
  ok('no JS exceptions',not report['errors'])
 finally:
  OUT.joinpath('ui_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));b.close()
print(json.dumps(report,ensure_ascii=False,indent=2))
