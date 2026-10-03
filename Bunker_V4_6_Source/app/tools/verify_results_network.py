#!/usr/bin/env python3
"""Three real Python WebSocket clients + production HTTP server and timer worker.

The child only seeds an initial deterministic room. All following operations use
normal network commands, real wall-clock time, and production broadcasts. This
is not a browser test; the offline DOM suite verifies presentation separately.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_results_live import server

CHECKS = []
DURATIONS = []

def check(value, name):
    if not value:
        raise AssertionError(name)
    CHECKS.append(name)

class Client:
    def __init__(self, base, pid):
        self.url = base.replace('http://', 'ws://') + '/ws/LIVE/' + pid
        self.pid = pid
        self.ws = None
        self.messages = []
        self.latest = None
        self.task = None
        self.heartbeat = None

    async def connect(self):
        self.ws = await websockets.connect(self.url)
        self.task = asyncio.create_task(self.receive())
        self.heartbeat = asyncio.create_task(self.ping())
        await self.wait_state(lambda s: True)
        return self

    async def receive(self):
        async for raw in self.ws:
            m = json.loads(raw)
            self.messages.append({'at': time.monotonic(), 'message': m})
            if m.get('type') == 'STATE_UPDATE':
                self.latest = m['state']

    async def ping(self):
        while True:
            await asyncio.sleep(3)
            await self.send('PING')

    async def send(self, action, **payload):
        await self.ws.send(json.dumps({'action': action, 'payload': payload}))

    async def wait_state(self, predicate, timeout=13):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.latest is not None and predicate(self.latest):
                return self.latest
            await asyncio.sleep(.015)
        raise AssertionError(f'{self.pid}: state not reached; latest phase={self.latest and self.latest["phase"]}; review={self.latest and self.latest.get("result_review")}')

    async def wait_error(self, action, since=0):
        end = time.monotonic() + 4
        while time.monotonic() < end:
            for row in self.messages[since:]:
                m = row['message']
                if m.get('type') == 'ERROR' and m.get('action') == action:
                    return m
            await asyncio.sleep(.015)
        raise AssertionError(f'No ERROR for {action}')

    async def close(self):
        if self.heartbeat:
            self.heartbeat.cancel()
        if self.ws:
            await self.ws.close()
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)


def states(client):
    return [row for row in client.messages if row['message'].get('type') == 'STATE_UPDATE']


def first_unblocked(client, review_id, phase):
    notices = [r for r in states(client) if (r['message']['state'].get('result_review') or {}).get('id') == review_id]
    after = next(r for r in states(client) if r['at'] > notices[0]['at'] and r['message']['state']['phase'] == phase and not r['message']['state'].get('result_review'))
    return notices[0], after


def check_duration(client, review_id, phase, label):
    before, after = first_unblocked(client, review_id, phase)
    duration = after['at'] - before['at']
    DURATIONS.append({'name': label, 'seconds': round(duration, 4)})
    check(4.9 <= duration <= 6.5, f'{label}: real review lasts {duration:.3f} seconds')
    return after['message']['state']


async def run(base, out):
    clients = []
    try:
        for pid in ('p0', 'p1', 'p2'):
            clients.append(await Client(base, pid).connect())
        a, b, c = clients
        async def all_state(predicate):
            return await asyncio.gather(*(x.wait_state(predicate) for x in (a, b, c)))
        async def review(kind):
            return await all_state(lambda s: (s.get('result_review') or {}).get('kind') == kind)
        async def clear():
            return await all_state(lambda s: not s.get('result_review'))
        await all_state(lambda s: all(p['connected'] for p in s['players']))
        check(all(x.latest['phase'] == 'VOTING' for x in clients), 'Three real sockets join a paused voting round')
        for client, target in zip((a, b, c), ('p1', 'p2', 'p0')):
            await client.send('CAST_VOTE', target_id=target)
        ss = await review('vote')
        rid = ss[0]['result_review']['id']
        check(all(s['result_review']['id'] == rid for s in ss), 'All clients receive the identical intermediate result ID')
        check(all(s['result_review']['data']['decision'] == 'defense' for s in ss), 'Tie leads to defense, not expulsion')
        check(all(s['timer']['seconds_left'] == 30 for s in ss), 'Defense gets its full configured time behind the review')
        check(all(s['result_review']['next_label'] == 'Защита кандидата' for s in ss), 'Server gives every client the same next-stage label')
        mark = len(a.messages)
        await a.send('NEXT_JUSTIFICATION_SPEAKER')
        await a.wait_error('NEXT_JUSTIFICATION_SPEAKER', mark)
        check(a.latest['justification_status']['index'] == 0, 'Premature gameplay command is rejected by actual WebSocket handler')
        await a.send('HOST_PAUSE_TIMER', is_paused=True)
        await all_state(lambda s: s['result_review'] and s['result_review']['is_paused'])
        seconds = a.latest['result_review']['seconds_left']
        await asyncio.sleep(1.2)
        check(all(x.latest['result_review']['seconds_left'] == seconds for x in (a,b,c)), 'Host pauses the shared review for all clients')
        await c.close()
        c = await Client(base, 'p2').connect()
        clients.append(c)
        await c.wait_state(lambda s: bool(s['result_review']))
        check(c.latest['result_review']['id'] == rid and c.latest['result_review']['seconds_left'] == seconds, 'Reconnect retains result ID and remaining time')
        await a.send('HOST_PAUSE_TIMER', is_paused=False)
        await clear()
        _, first = first_unblocked(a, rid, 'JUSTIFICATION')
        check(first['message']['state']['timer']['seconds_left'] == 30, 'First playable defense state has all 30 seconds')
        for index in range(3):
            await a.wait_state(lambda s: s['phase'] == 'JUSTIFICATION' and s['justification_status']['index'] == index)
            await a.send('NEXT_JUSTIFICATION_SPEAKER')
            if index < 2:
                await a.wait_state(lambda s: s['justification_status']['index'] == index + 1)
        await all_state(lambda s: s['phase'] == 'REVOTE')
        check(all(x.latest['phase_context']['title'] == 'Переголосование' for x in (a,b,c)), 'Actual revote has an explicit separate stage title')
        for client, target in zip((a,b,c), ('p1','p0','p1')):
            await client.send('CAST_VOTE', target_id=target)
        ss = await review('vote')
        rid2 = ss[0]['result_review']['id']
        check(rid != rid2 and ss[0]['result_review']['data']['source'] == 'REVOTE', 'Revote produces a new final tally rather than replaying the intermediate one')
        check(all(s['result_review']['next_label'] == 'Право вето' for s in ss), 'All clients know veto comes next')
        check(all(next(p for p in s['players'] if p['id']=='p1')['is_alive'] for s in ss), 'Candidate remains alive during the result review')
        await clear()
        first = check_duration(a, rid2, 'VOTE_RESULTS', 'Revote result')
        check(first['timer']['seconds_left'] == 10, 'Entire original ten-second veto window starts after five-second summary')
        check(all(x.latest['phase_context']['title'] == 'Право вето' for x in (a,b,c)), 'Veto window is explicitly labeled, not shown as a live ballot')
        # Do not fast-forward: verify production timer automatically confirms.
        ss = await review('event')
        erid = ss[0]['result_review']['id']
        event = ss[0]['result_review']['data']
        check(all(s['result_review']['id'] == erid for s in ss), 'Automatic event result reaches every client without opening history')
        check(all(not next(p for p in s['players'] if p['id']=='p1')['is_alive'] for s in ss), 'Expulsion is final before automatic event outcome')
        check(event['roll'] is not None and event['chance_required'] is not None, 'Real event d100 and success threshold are in the result')
        check('rating_change' in event and 'description' in event and 'score_delta' in event, 'Event includes actual consequences and normalized rating contribution')
        check(all(s['timer']['seconds_left'] == 15 for s in ss), 'Event review freezes the full last-word timer')
        check(all(s['result_review']['next_label'] == 'Последнее слово' for s in ss), 'Event handoff explicitly names the last-word stage')
        await clear()
        first = check_duration(a, erid, 'LAST_WORD', 'Automatic event result')
        check(first['timer']['seconds_left'] == 15, 'First playable last word retains all fifteen seconds')
        await a.send('FINISH_LAST_WORD')
        await all_state(lambda s: s['phase']=='REVEAL' and s['round_number']==2)
        check(all(not x.latest['result_review'] for x in (a,b,c)), 'Next round does not replay historical results')
        check(all(x.latest['last_vote_summary']['summary_id'] == ss[0]['last_vote_summary']['summary_id'] for x in (a,b,c)), 'Latest tally remains available for voluntary recap')
        # Resolve another event during an already paused turn via normal host commands.
        await a.send('HOST_PAUSE_TIMER', is_paused=True)
        await a.wait_state(lambda s: s['timer']['is_paused'])
        oldtime = a.latest['timer']['seconds_left']
        if a.latest['events_state']['active_event']['type'] == 'SURFACE_EVENT':
            await a.send('ASSIGN_VOLUNTEER', volunteer_id='p0')
            await a.wait_state(lambda s: s['events_state']['volunteer_id']=='p0')
        await a.send('RESOLVE_EVENT', force_roll=99)
        ss = await review('event')
        eid2 = ss[0]['result_review']['id']
        check(eid2 != erid and ss[0]['result_review']['data']['is_crit_failure'], 'Manual resolution also creates a new result, including the real critical failure')
        check(all(s['result_review']['next_label']=='Открытие карточек' for s in ss), 'Mid-turn result tells users they return to card reveal')
        await clear()
        first = check_duration(a, eid2, 'REVEAL', 'Manually resolved event')
        check(first['timer']['seconds_left']==oldtime and first['timer']['is_paused'], 'Existing phase time and pre-existing pause survive a mid-turn event review')
        # No-exile result resolves after five seconds, without the old extra six.
        await a.send('START_VOTING')
        await all_state(lambda s:s['phase']=='VOTING')
        await a.send('CAST_VOTE',target_id='ABSTAIN')
        await c.send('CAST_VOTE',target_id='ABSTAIN')
        ss = await review('vote')
        nrid = ss[0]['result_review']['id']
        check(ss[0]['result_review']['data']['decision']=='none', 'All abstain yields explicit no-expulsion decision')
        check(ss[0]['result_review']['data']['counts']['abstain_weight']==2, 'Actual abstention count is separated from target votes')
        await all_state(lambda s:s['phase']=='REVEAL' and s['round_number']==3 and not s['result_review'])
        first = check_duration(a,nrid,'REVEAL','No-expulsion result')
        check(first['timer']['seconds_left']==60, 'No extra hidden wait: new reveal round begins with all sixty seconds')
        check(sum(p['is_alive'] for p in a.latest['players'])==2, 'Nobody is expelled by an all-abstain round')
        (out/'network_host_trace.json').write_text(json.dumps(a.messages,ensure_ascii=False,indent=2),encoding='utf8')
    finally:
        for client in clients:
            await client.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--server',type=int)
    parser.add_argument('--output',type=Path,default=ROOT/'results_v4_3/network')
    args=parser.parse_args()
    if args.server:
        server(args.server)
        return
    args.output.mkdir(parents=True,exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    failure=None
    with (args.output/'network_server.log').open('w') as log:
        process=subprocess.Popen([sys.executable,__file__,'--server',str(port)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    if httpx.get(base+'/api/room/LIVE',timeout=.4).status_code==200:
                        break
                except Exception:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('Server failed to start')
            asyncio.run(run(base,args.output))
        except Exception as exc:
            traceback.print_exc();failure=f'{type(exc).__name__}: {exc}'
        finally:
            process.terminate()
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    report={'passed':failure is None,'mode':'Three independent Python clients; real localhost HTTP/WebSockets; production timer worker running in real time',
            'checks_passed':len(CHECKS),'checks':CHECKS,'durations':DURATIONS,'failure':failure}
    (args.output/'results_network.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if failure:raise SystemExit(1)

if __name__=='__main__':main()
