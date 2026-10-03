#!/usr/bin/env python3
"""Paired Age V4 evaluation and actual-engine simplified campaigns.

Both formulas see the identical team, scenario and event history in each pair.
Campaign choices use random or current-score/public-card heuristics, not human
persuasion. No traitor or special-card use. Elimination choice replaces ballots;
reveal circles, both speeches, exile, events and finals use the real engine.
Success percentages describe simulated colony classifications, not human wins.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import itertools
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server import balance as current, deck_data as d, game_engine as g
from server.age_balance import age_from_cards


def load_baseline(path):
    path=Path(path)
    if (path/'server').is_dir():path=path/'server'
    spec=importlib.util.spec_from_file_location('server._age_reference',path/'balance.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module,{name:hashlib.sha256((path/name).read_bytes()).hexdigest() for name in
                   ('balance.py','balance_catalog.json','balance_config.json')}


def comparison(old,new):
    age=new['breakdown']['age_care']
    assert abs(old['breakdown']['score_components']['raw']-age['raw_without_age']) <= .0011
    assert 0 <= age['penalty'] <= current.CONFIG['age_care']['final_penalty_cap']
    assert new['survival_score'] <= old['survival_score']
    return {'old_score':old['survival_score'],'new_score':new['survival_score'],
            'old_success':old['is_success'],'new_success':new['is_success'],
            'penalty':age['penalty'],'affected':age['affected_count']>0,
            'cap':age['cap_applied'],'support_relief':age['support_reduction_pct']}


def aggregate(runs):
    n=len(runs);deltas=[r['new_score']-r['old_score'] for r in runs]
    affected=[r for r in runs if r['affected']]
    return {'samples':n,'old_mean_score':round(statistics.mean(r['old_score'] for r in runs),3),
        'new_mean_score':round(statistics.mean(r['new_score'] for r in runs),3),
        'old_success_pct':round(100*sum(r['old_success'] for r in runs)/n,3),
        'new_success_pct':round(100*sum(r['new_success'] for r in runs)/n,3),
        'changed_success_to_failure':sum(r['old_success'] and not r['new_success'] for r in runs),
        'mean_score_delta':round(statistics.mean(deltas),3),
        'paired_delta_standard_error':round(statistics.stdev(deltas)/n**.5,4) if n>1 else 0,
        'affected_teams_pct':round(100*len(affected)/n,3),
        'mean_penalty_all':round(statistics.mean(r['penalty'] for r in runs),4),
        'mean_penalty_affected':round(statistics.mean(r['penalty'] for r in affected),4) if affected else 0,
        'max_penalty':max(r['penalty'] for r in runs),'cap_hits':sum(r['cap'] for r in runs)}


def public_players(ps):
    return [{'id':p.id,'name':p.name,'cards':{k:c for k,c in p.cards.items()
            if c.get('revealed') and k not in ('special','traitor')}} for p in ps]


def score(r,ps):
    return current.evaluate_survival(ps,r.catastrophe,r.bunker,
        resolved_events_history=r.resolved_events)['breakdown']['score_components']['raw']


def reveal_choice(r,p,policy,rng):
    hidden=[k for k,c in p.cards.items() if k not in ('special','traitor') and not c.get('revealed')]
    if r.round_number==1 and 'profession' in hidden:return 'profession'
    if policy=='random':return rng.choice(hidden)
    candidates=[]
    for category in hidden:
        card=p.cards[category];was=card.get('revealed',False);card['revealed']=True
        try:
            event=d.calculate_event_odds(r.active_event,[p],[],volunteer_id=p.id,
                catastrophe=r.catastrophe)['final_chance'] if r.active_event else 0
            candidates.append((event+.5*score(r,public_players(r.get_alive_players())),rng.random(),category))
        finally:card['revealed']=was
    return max(candidates)[2]


def campaign(n,policy,seed,baseline):
    random.seed(seed);rng=random.Random(seed+73921)
    r=g.BunkerGameRoom('AGESIM','p0','P0')
    for i in range(1,n):r.add_player(f'p{i}',f'P{i}')
    r.start_game(capacity=n//2,enable_events=True,enable_traitor=False)
    reveals=first=second=0
    while r.phase!=g.PHASE_FINAL:
        assert r.round_number<=n+1,'Nontermination'
        while r.phase==g.PHASE_REVEAL:
            p=r.get_current_speaker()
            while not r.can_speaker_proceed():r.reveal_player_card(p.id,reveal_choice(r,p,policy,rng))
            r.next_reveal_player();reveals+=1
        while r.phase==g.PHASE_SPEECH:r.next_speaker();first+=1
        while r.phase==g.PHASE_ACCUSATION:r.next_accusation_speaker();second+=1
        assert r.phase==g.PHASE_VOTING
        alive=r.get_alive_players()
        if policy=='random':exile=rng.choice(alive)
        else:
            pp=public_players(alive)
            exile=max(alive,key=lambda p:(score(r,[v for v in pp if v['id']!=p.id]),rng.random()))
        remaining=[p for p in alive if p.id!=exile.id]
        if r.active_event and r.active_event['type']=='SURFACE_EVENT':
            volunteer=rng.choice(remaining) if policy=='random' else max(remaining,
                key=lambda p:d.calculate_event_odds(r.active_event,[p],r.get_exiled_players(),
                volunteer_id=p.id,catastrophe=r.catastrophe)['final_chance'])
            r.assign_volunteer(volunteer.id)
        r.phase=g.PHASE_VOTE_RESULTS
        r.vote_results={'eliminated_id':exile.id,'eliminated_ids':[exile.id]}
        r.confirm_elimination();r.finish_last_word();r.game_log.clear()
    assert reveals==first==second,'Both speech circles must be executed'
    old=baseline.evaluate_survival(r.get_alive_players(),r.catastrophe,r.bunker,
                                  resolved_events_history=r.resolved_events)
    return {**comparison(old,r.final_evaluation),'events':len(r.resolved_events),
            'reveal_turns':reveals,'speech1_turns':first,'speech2_turns':second}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,default=ROOT/'tools/baseline_reveal_v3')
    parser.add_argument('--teams',type=int,default=1000,help='Paired random final teams per initial population')
    parser.add_argument('--campaigns',type=int,default=100,help='Engine games per population/policy')
    parser.add_argument('--optimize',type=int,default=500,help='Six-person deals; enumerate all 20 trios')
    parser.add_argument('--seed',type=int,default=20260920)
    parser.add_argument('--out',type=Path,default=ROOT/'age_results/simulations.json')
    args=parser.parse_args()
    if min(args.teams,args.campaigns,args.optimize)<1:parser.error('counts must be positive')
    baseline,hashes=load_baseline(args.baseline);start=time.time()
    report={'notes':__doc__,'seed':args.seed,'python':sys.version,'baseline_sha256':hashes,
            'config':current.CONFIG,'random_teams':[],'campaigns':[],'optimization':{}}
    def save():
        report['elapsed_seconds']=round(time.time()-start,2)
        args.out.parent.mkdir(exist_ok=True,parents=True)
        args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    for n in (3,4,6,8,10,12,20):
        runs=[]
        for i in range(args.teams):
            random.seed(args.seed+n*100000+i)
            deck=d.generate_game_deck(n,n//2,enable_events=True)
            ps=[{'id':str(j),'name':f'P{j}','cards':cards} for j,cards in enumerate(deck['players_cards'])]
            ps=random.sample(ps,n//2)
            runs.append(comparison(baseline.evaluate_survival(ps,deck['catastrophe'],deck['bunker']),
                                   current.evaluate_survival(ps,deck['catastrophe'],deck['bunker'])))
        row={'players':n,'capacity':n//2,**aggregate(runs)};report['random_teams'].append(row);save();print('teams',row,flush=True)
    # Full information optimizer is NOT human voting; random jitter only resolves exact ties.
    selections={'older':{'dealt':0,'old_selected':0,'new_selected':0},'younger':{'dealt':0,'old_selected':0,'new_selected':0}}
    changes=0;profession_counts={}
    for i in range(args.optimize):
        random.seed(args.seed+8000000+i);deck=d.generate_game_deck(6,3,enable_events=False)
        ps=[{'id':str(j),'name':f'P{j}','cards':cards} for j,cards in enumerate(deck['players_cards'])]
        choices=[]
        for inds in itertools.combinations(range(6),3):
            subset=[ps[j] for j in inds]
            old=baseline.evaluate_survival(subset,deck['catastrophe'],deck['bunker'])
            new=current.evaluate_survival(subset,deck['catastrophe'],deck['bunker'])
            comparison(old,new)
            choices.append((old['breakdown']['score_components']['raw'],new['breakdown']['score_components']['raw'],random.random(),inds))
        old_set=set(max(choices,key=lambda row:(row[0],row[2]))[3]);new_set=set(max(choices,key=lambda row:(row[1],row[2]))[3])
        changes+=old_set!=new_set
        for j,p in enumerate(ps):
            bucket='older' if age_from_cards(p['cards'])>=60 else 'younger'
            row=selections[bucket];row['dealt']+=1;row['old_selected']+=j in old_set;row['new_selected']+=j in new_set
            tag=p['cards']['profession']['tag'];row=profession_counts.setdefault(tag,{'dealt':0,'old_selected':0,'new_selected':0})
            row['dealt']+=1;row['old_selected']+=j in old_set;row['new_selected']+=j in new_set
    report['optimization']={'deals':args.optimize,'evaluated_trios':args.optimize*20,
        'changed_optimal_teams':changes,'age_groups':selections,'profession_tags':profession_counts,
        'note':'Oracle full-information optimization, not a human win rate. Age groups are >=60 and <60.'};save()
    print('optimization',report['optimization'],flush=True)
    for n in (4,6,8,12):
        for policy in ('random','public_greedy'):
            runs=[campaign(n,policy,args.seed+10000000+n*10000+i,baseline) for i in range(args.campaigns)]
            row={'players':n,'capacity':n//2,'policy':policy,**aggregate(runs),
                'events':sum(x['events'] for x in runs),'reveal_turns':sum(x['reveal_turns'] for x in runs),
                'speech1_turns':sum(x['speech1_turns'] for x in runs),'speech2_turns':sum(x['speech2_turns'] for x in runs)}
            report['campaigns'].append(row);save();print('campaigns',row,flush=True)
    print('DONE',round(time.time()-start,2),flush=True)

if __name__=='__main__':main()
