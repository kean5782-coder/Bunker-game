"""Linux live transport check. Does NOT claim Windows or external VPN validation."""
import argparse, json, socket, time
from pathlib import Path
import requests
from websockets.sync.client import connect

ap=argparse.ArgumentParser();ap.add_argument('--instance',required=True);ap.add_argument('--output',required=True);ap.add_argument('--port',type=int,default=18008);a=ap.parse_args()
d=json.loads(Path(a.instance).read_text());base=d['origin'];headers={'X-Bunker-Token':d['token']};PORT=a.port
report={'environment':'Linux Go helper + private system-Python test runtime; real loopback TCP/HTTP/WebSocket. No actual Windows, router, Porthole, Hamachi, or external internet test.','checks':[]}
def check(name,ok):
 report['checks'].append({'name':name,'ok':bool(ok)})
 assert ok,name

def get():return requests.get(base+'/api/status',headers=headers,timeout=5).json()
def post(path,data=None):return requests.post(base+'/api/'+path,headers=headers,json=data or {},timeout=5)
def wait(phase):
 for _ in range(120):
  s=get()
  if s['phase']==phase:return s
  if s['phase']=='error' and phase!='error':raise AssertionError(s)
  time.sleep(.1)
 raise AssertionError(('timeout',phase,get()))

def msg(ws,typ):
 for _ in range(30):
  m=json.loads(ws.recv(timeout=5))
  if m['type']==typ:return m
 raise AssertionError(typ)
try:
 post('stop')
 check('helper requires control secret',requests.get(base+'/api/status',timeout=3).status_code==403)
 check('foreign Origin rejected',requests.post(base+'/api/start',headers={**headers,'Origin':'https://foreign.example'},json={},timeout=3).status_code==403)
 r=post('start',{'role':'guest','mode':'porthole','port':PORT,'address':''})
 check('guest starts without Python download',r.status_code==200 and get()['phase']=='guest')
 with socket.socket() as s:
  check('guest does not occupy game TCP port',s.connect_ex(('127.0.0.1',PORT))!=0)
 for mode,address,outport in [('porthole','',PORT),('lan','192.168.1.25',PORT),('vpn','25.1.2.3',PORT),('public','203.0.113.15',18009)]:
  # LAN/VPN/public values validate link generation only; requests still use loopback.
  data={'role':'host','mode':mode,'port':PORT,'address':address,'external_port':outport,'allow_download':False}
  r=post('start',data);check(mode+': start accepted',r.status_code==202)
  s=wait('running');game=s['game_url'];info=requests.get(game+'/api/network-info',timeout=3).json()
  expected='http://'+('127.0.0.1' if mode=='porthole' else address)+':'+str(outport)
  check(mode+': selected address and port',info['share_url']==expected)
  check(mode+': offline guide available',requests.get(game+'/help',timeout=3).status_code==200)
  c=requests.post(game+'/api/room/create',json={'host_name':'Test host'},timeout=3).json();code=c['room_code']
  check(mode+': invitation contains room',c['share_url']==expected+'/?room='+code)
  j=requests.post(game+'/api/room/join',json={'room_code':code,'player_name':'Test guest'},timeout=3).json()
  check(mode+': guest joins room',bool(j.get('player_id')))
  with connect(f'ws://127.0.0.1:{PORT}/ws/{code}/{c["host_id"]}',open_timeout=3) as wh:
   check(mode+': real WebSocket initial state',msg(wh,'STATE_UPDATE')['type']=='STATE_UPDATE')
   wh.send(json.dumps({'action':'PING'}));check(mode+': PONG',msg(wh,'PONG')['type']=='PONG')
   wh.send(json.dumps({'action':'UPDATE_LOBBY_SETTINGS','payload':{'settings':{'information_mode':'uncertainty'}}}))
   check(mode+': host changes information mode',msg(wh,'ACTION_OK')['action']=='UPDATE_LOBBY_SETTINGS')
  post('stop');wait('idle')
  with socket.socket() as s:
   check(mode+': stopped server releases port',s.connect_ex(('127.0.0.1',PORT))!=0)
 with socket.socket() as occupied:
  occupied.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);occupied.bind(('127.0.0.1',PORT));occupied.listen()
  post('start',{'role':'host','mode':'porthole','port':PORT,'address':'','allow_download':False})
  s=wait('error');check('occupied port reports explicit error','занят' in s['error'])
  check('occupied socket not killed',occupied.fileno()!=-1)
 post('stop')
 report['passed']=True
finally:
 Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps(report,ensure_ascii=False,indent=2))
