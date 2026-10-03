"""Weighted ballots shared by normal voting and revoting.

Quarantined voters have no ballot or AFK penalty. Immunity is respected by both
manual ballots and timer-generated ballots. A changed SKIP vote is removed.
"""
import random
import time


def eligible(room):
    return [p for p in room.get_alive_players() if not p.is_quarantined]


def _weight(player):
    return 2 if player.double_vote else 1


def _finish_no_exile(room, tally=None, abstain=0):
    source = room.phase
    room.phase='VOTE_RESULTS';room.timer_seconds_left=0;room.timer_is_paused=False
    room.vote_results={'eliminated_id':None,'eliminated_ids':[], 'eliminated_name':None,
        'is_tie':False,'threshold_failed':True,'abstain_count':abstain,
        'top_candidates':[],'detailed_tally':tally or [],'veto_possible':False}
    room.present_vote_summary(room.vote_results, source=source, after='confirm_no_exile')
    room.log_event('Нет решения об изгнании','Нет действительных голосов против кандидатов.','warning')


def cast_vote(room,voter_id,target_id):
    if room.phase not in ('VOTING','REVOTE'):raise ValueError('Голосование сейчас не активно.')
    voter=room.players.get(voter_id)
    if voter is None or not voter.is_alive:raise ValueError('Изгнанные не голосуют.')
    if voter.is_quarantined:raise ValueError('Игрок в изоляторе не голосует до конца раунда.')
    if target_id in ('ABSTAIN',None,'NONE',''):
        target='ABSTAIN'
    elif target_id in ('SKIP_ROUND','SKIP'):
        if room.phase!='VOTING' or room.round_number!=1 or room.forced_revote_round==room.round_number:
            raise ValueError('Пропуск доступен только на первом голосовании первого раунда.')
        target='SKIP_ROUND'
    else:
        candidate=room.players.get(target_id)
        if not candidate or not candidate.is_alive:raise ValueError('Нужен живой кандидат.')
        if candidate.has_immunity:raise ValueError('У кандидата иммунитет.')
        if room.phase=='REVOTE' and target_id not in room.justification_candidates:
            raise ValueError('На переголосовании выбирают среди кандидатов на оправдание.')
        target=target_id
    room.last_activity=time.time()
    room.skip_round_votes.discard(voter_id)
    voter.vote_target=target;room.votes[voter_id]=target
    voters=eligible(room);total=sum(_weight(p) for p in voters)
    if target=='SKIP_ROUND':room.skip_round_votes.add(voter_id)
    skip_weight=sum(_weight(p) for p in voters if room.votes.get(p.id)=='SKIP_ROUND')
    if room.phase=='VOTING' and room.round_number==1 and skip_weight>total/2:
        room.finish_skip_round();return
    room.log_event('Голос учтён',f'{voter.name} сделал выбор.','info')
    connected=[p for p in voters if p.connected]
    required=connected if len(connected)>=2 else voters
    if required and all(p.id in room.votes for p in required):
        (finish_voting if room.phase=='VOTING' else finish_revote)(room)


def _tally(room,revote=False):
    voters=eligible(room);valid_candidates={p.id for p in room.get_alive_players() if not p.has_immunity}
    if revote:valid_candidates.intersection_update(room.justification_candidates)
    for p in voters:
        if p.id not in room.votes or room.votes[p.id] is None:
            if p.id in valid_candidates:
                target=p.id
            elif revote and valid_candidates:
                target=random.choice(sorted(valid_candidates))
            else:target='ABSTAIN'
            p.vote_target=target;room.votes[p.id]=target
    total=sum(_weight(p) for p in voters);counts={};abstain=0
    for p in voters:
        target=room.votes.get(p.id)
        if target in valid_candidates:counts[target]=counts.get(target,0)+_weight(p)
        else:abstain+=_weight(p)
    detailed=[{'player_id':pid,'player_name':room.players[pid].name,'votes':v,
               'percent':round(100*v/total,1) if total else 0}
              for pid,v in sorted(counts.items(),key=lambda kv:kv[1],reverse=True)]
    return voters,total,counts,abstain,detailed


def _results(room,ids,detailed,abstain=0,tied=False,revote=False,max_percent=0):
    room.phase='VOTE_RESULTS';room.timer_seconds_left=10;room.timer_is_paused=False
    room.vote_results={'eliminated_id':ids[0] if ids else None,'eliminated_ids':ids,
        'eliminated_name':', '.join(room.players[pid].name for pid in ids) if ids else None,
        'is_tie':tied,'tie_broken_by':'dice' if tied else None,'threshold_failed':False,
        'revote_completed':revote,'double_elimination':len(ids)>1,'detailed_tally':detailed,
        'top_candidates':ids,'veto_possible':bool(ids),'abstain_count':abstain,
        'max_percent':round(max_percent,1),'instant_exile':not revote and max_percent>=70}
    room.present_vote_summary(room.vote_results, source='REVOTE' if revote else 'VOTING')
    room.log_event('Итоги голосования',f"Кандидаты на изгнание: {room.vote_results['eliminated_name'] or 'нет'}. До подтверждения действуют спецкарты.",'danger' if ids else 'info')


def finish_voting(room):
    room.last_activity=time.time()
    voters,total,tally,abstain,detailed=_tally(room)
    skip_weight=sum(_weight(p) for p in voters if room.votes.get(p.id)=='SKIP_ROUND')
    if room.round_number==1 and skip_weight>total/2 and room.forced_revote_round!=room.round_number:
        room.finish_skip_round();return
    if not tally:_finish_no_exile(room,detailed,abstain);return
    limit=min(2 if room.double_elimination_pending else 1,max(0,len(room.get_alive_players())-room.bunker_capacity))
    if not limit:_finish_no_exile(room,detailed,abstain);return
    ranked=sorted(tally,key=tally.get,reverse=True);max_votes=tally[ranked[0]]
    leaders=[pid for pid in ranked if tally[pid]==max_votes]
    pct=100*max_votes/total if total else 0
    if limit==2 and len(ranked)>=2:
        cutoff=tally[ranked[1]]
        tied_second=[pid for pid in ranked if tally[pid]==cutoff]
        above=[pid for pid in ranked if tally[pid]>cutoff]
        if len(above)+len(tied_second)==2:
            _results(room,ranked[:2],detailed,abstain,max_percent=pct);return
        candidates=list(dict.fromkeys(above+tied_second))
        _defense_results(room,candidates,True,detailed,pct,abstain);return
    if pct>=70 and len(leaders)==1:
        _results(room,leaders,detailed,abstain,max_percent=pct);return
    _defense_results(room,leaders,len(leaders)>1,detailed,pct,abstain)



def _defense_results(room,candidates,tied,detailed,pct,abstain):
    room.start_justification(candidates,tied,detailed,pct)
    room.present_vote_summary({'candidates': candidates, 'is_tie': tied,
        'candidate_names': [room.players[pid].name for pid in candidates],
        'detailed_tally': detailed, 'max_percent': round(pct,1),
        'abstain_count': abstain, 'eliminated_ids': [], 'veto_possible': False},
        decision='defense')

def finish_revote(room):
    room.last_activity=time.time()
    _,total,tally,abstain,detailed=_tally(room,revote=True)
    if not tally:_finish_no_exile(room,detailed,abstain);return
    limit=min(2 if room.double_elimination_pending else 1,max(0,len(room.get_alive_players())-room.bunker_capacity))
    remaining=dict(tally);ids=[];tied=False
    for _ in range(min(limit,len(remaining))):
        top=max(remaining.values());leaders=[pid for pid,v in remaining.items() if v==top]
        tied=tied or len(leaders)>1
        chosen=random.choice(leaders) if len(leaders)>1 else leaders[0]
        ids.append(chosen);del remaining[chosen]
    _results(room,ids,detailed,abstain,tied=tied,revote=True,max_percent=100*max(tally.values())/total if total else 0)
