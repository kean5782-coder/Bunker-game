#!/usr/bin/env python3
"""Validate all source cards and repeat the production dealer deterministically."""
from pathlib import Path
import argparse,sys,json,random,math,collections
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server import deck_data as d
from server.balance import CATALOG,NEED_SKILLS,NEED_TRAITS
from server.special_cards import canonical,DEFINITIONS
parser=argparse.ArgumentParser();parser.add_argument('--deals',type=int,default=1000);parser.add_argument('--deal-mode',choices=['full_random','balanced'],default='full_random');args=parser.parse_args()
contexts=set();skills=set()
for e in CATALOG['events'].values():contexts.update(e['traits']+e['hazards']);contexts.update(['physical'] if e['physical'] else []);skills.update(e['skills'])
for v in NEED_SKILLS.values():skills.update(v)
for v in NEED_TRAITS.values():contexts.update(v)
categories={'profession':d.PROFESSIONS,'health':d.HEALTH_CONDITIONS,'body':d.BODY_BUILDS,'trait':d.HUMAN_TRAITS,'hobby':d.HOBBIES,'phobia':d.PHOBIAS,'big_inventory':d.BIG_INVENTORY,'backpack':d.BACKPACK_ITEMS,'fact':d.FACTS}
missing=[];inactive=[]
for cat,rows in categories.items():
 for row in rows:
  name=row['name'];effect=CATALOG['cards'][cat].get(name)
  if effect is None:missing.append([cat,name]);continue
  if cat in ('health','profession') or effect.get('roleplay_only'):continue
  if not (set(effect.get('skills',{}))&skills or set(effect.get('traits',[]))&contexts or set(effect.get('risks',[]))&contexts or set(effect.get('protection',[]))&contexts):inactive.append([cat,name])
assert not missing,missing
assert not inactive,inactive
assert all(canonical(s['id']) in DEFINITIONS for s in d.SPECIAL_CARDS)
results=[]
for n in [3,4,6,8,10,12]:
 random.seed(20260919+n);over=duplicate=0;health=collections.Counter();weak=0
 for _ in range(args.deals):
  deck=d.generate_game_deck(n,deal_mode=args.deal_mode);cards=deck['players_cards']
  nw=sum(c['profession']['tag']=='useless' for c in cards);weak+=nw;over+=nw>math.floor(n*.25)
  ids=[canonical(c['special']['card_id']) for c in cards];duplicate+=len(ids)!=len(set(ids))
  health.update(c['health']['severity'] for c in cards)
 assert not duplicate
 if args.deal_mode=='balanced':assert not over
 results.append({'players':n,'deals':args.deals,'weak_cap':math.floor(n*.25),'weak_cap_violations':over,'duplicate_special_effects':duplicate,'mean_weak_professions':round(weak/args.deals,3),'health_shares':{k:round(v/(n*args.deals),4) for k,v in health.items()}})
report={'deal_mode':args.deal_mode,'ordinary_source_rows':sum(len(rows) for rows in categories.values())+len(d.GENDER_TRAITS),'mechanical_categories':list(categories),'missing_profiles':missing,'inactive_profiles_in_body_trait_phobia_hobby_fact_equipment':inactive,'special_ids':len(d.SPECIAL_CARDS),'canonical_special_effects':len(DEFINITIONS),'events':len(d.BUNKER_EVENTS),'seed':20260919,'total_deals':sum(r['deals'] for r in results),'results':results}
out=ROOT/'balance_results'/f'catalog_and_deals_{args.deal_mode}.json';out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))
