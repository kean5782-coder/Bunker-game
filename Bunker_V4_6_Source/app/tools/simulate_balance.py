#!/usr/bin/env python3
"""Reproducible simplified campaigns. Standard library only.
Actual engine, reveal quotas, exile/events/health/final; NO human persuasion,
coalitions, actual ballots, traitor or special-card play. Success is the engine's
classification, not a real player win probability. Same seeds do not mean
identical decks across versions because RNG consumption changes.
"""
import argparse,sys,pathlib,random,copy,statistics,json,time,hashlib
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parents[1])
parser.add_argument('--games',type=int,default=300)
parser.add_argument('--sizes',type=int,nargs='+',default=[3,4,6,8,10,12])
parser.add_argument('--seed',type=int,default=20260919)
parser.add_argument('--out',type=pathlib.Path,default=pathlib.Path('balance_results/campaigns.json'))
args=parser.parse_args()
if args.games<1:parser.error('--games must be positive')
sys.path.insert(0,str(args.project.resolve()))
from server import deck_data as d
from server import game_engine as g
def public_players(pl):
 return [{'id':p.id,'name':p.name,'cards':{k:c for k,c in p.cards.items() if c.get('revealed') and k not in ('special','traitor')}} for p in pl]
def finalscore(r,ps):
 return d.evaluate_survival(ps,r.catastrophe,r.bunker,events_score_delta=r.events_score_delta,boosted_profession_tags=r.boosted_profession_tags)['survival_percent']
def reveal_choice(r,p,policy):
 hidden=[k for k,c in p.cards.items() if k not in ('special','traitor') and not c.get('revealed',False)]
 if r.round_number==1 and 'profession' in hidden:return 'profession'
 if policy=='random':return random.choice(hidden)
 candidates=[]
 for cat in hidden:
  p.cards[cat]['revealed']=True
  # Player knows their own cards; only currently revealed cards of others are used.
  es=d.calculate_event_odds(r.active_event,[p],[],volunteer_id=p.id,catastrophe=r.catastrophe)['final_chance'] if r.active_event else 0
  fs=finalscore(r,public_players(r.get_alive_players()))
  candidates.append((es+.5*fs,random.random(),cat));p.cards[cat]['revealed']=False
 return max(candidates)[2]

def run(n,policy,seed):
 random.seed(seed);r=g.BunkerGameRoom('SIM','p0','P0')
 for i in range(1,n):r.add_player(f'p{i}',f'P{i}')
 r.start_game(capacity=n//2,enable_events=True)
 while r.phase!=g.PHASE_FINAL:
  if r.round_number>n+1:raise RuntimeError('Unexpected nontermination')
  while r.phase==getattr(g,'PHASE_REVEAL',g.PHASE_SPEECH):
   actor=r.get_current_speaker()
   while not r.can_speaker_proceed():r.reveal_player_card(actor.id,reveal_choice(r,actor,policy))
   r.next_speaker()
  while r.phase==g.PHASE_SPEECH:r.next_speaker()
  alive=r.get_alive_players()
  if policy=='random':exile=random.choice(alive)
  else:
   pp=public_players(alive);ranks=[]
   for candidate in alive:
    fs=finalscore(r,[p for p in pp if p['id']!=candidate.id]);ranks.append((fs,random.random(),candidate.id))
   exile=r.players[max(ranks)[2]]
  remaining=[p for p in alive if p.id!=exile.id]
  if r.active_event and r.active_event['type']=='SURFACE_EVENT':
   if policy=='random':vol=random.choice(remaining)
   else:
    vol=max(remaining,key=lambda p:d.calculate_event_odds(r.active_event,[p],r.get_exiled_players(),volunteer_id=p.id,catastrophe=r.catastrophe)['final_chance'])
   r.assign_volunteer(vol.id)
  r.phase=g.PHASE_VOTE_RESULTS;r.vote_results={'eliminated_id':exile.id,'eliminated_ids':[exile.id]}
  r.confirm_elimination();r.finish_last_word();r.game_log.clear()
 res=r.final_evaluation
 return {'score':res['survival_percent'],'success':res['is_success'],'no_events_score_same_final_team':d.evaluate_survival(r.get_alive_players(),r.catastrophe,r.bunker)['survival_percent'],'events_delta':r.events_score_delta,'boost_tags':len(r.boosted_profession_tags),'events':[{'event_id':h['event']['id'],'type':h['event']['type'],'round':h['round'],'chance':h['result']['chance_required'],'success':h['result']['is_success'],'damage':h['result']['health_degraded'] is not None,'delta':h['result']['score_delta']} for h in r.resolved_events]}


start=time.time();rows=[]
for n in args.sizes:
 for policy in ('random','public_greedy'):
  runs=[run(n,policy,args.seed+100000*n+i) for i in range(args.games)]
  events=[e for r in runs for e in r['events']]
  row={'players':n,'capacity':n//2,'policy':policy,'games':len(runs),'mean_score':round(statistics.mean(r['score'] for r in runs),3),'success_pct':round(100*sum(r['success'] for r in runs)/len(runs),2),'near_cap_95_pct':round(100*sum(r['score']>=95 for r in runs)/len(runs),2),'events':len(events),'mean_event_chance':round(statistics.mean(e['chance'] for e in events),3),'mean_events_score_delta':round(statistics.mean(r['events_delta'] for r in runs),3),'event_types':{t:{'events':len(es:=[e for e in events if e['type']==t]),'mean_chance':round(statistics.mean(e['chance'] for e in es),3) if es else None,'success_pct':round(100*sum(e['success'] for e in es)/len(es),2) if es else None} for t in ('BUNKER_CRISIS','SURFACE_EVENT')}}
  rows.append(row)
  args.out.parent.mkdir(parents=True,exist_ok=True)
  metadata={'seed':args.seed,'games_per_cell':args.games,'python':sys.version,'project_sha256':{str(f.relative_to(args.project)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (args.project/'server').glob('*.py') if not f.name.startswith('test')},'notes':__doc__,'elapsed_seconds':round(time.time()-start,2),'rows':rows}
  args.out.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf8')
  print(row,flush=True)
print('elapsed_seconds',round(time.time()-start,2),flush=True)
