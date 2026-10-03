"""Speech-card lifecycle, custom input, public state, and prompter authority."""
import copy
import json
from unittest.mock import patch

import pytest
from server import deck_data as d, special_cards as sc, speech_effects as speech
from server.game_engine import BunkerGameRoom


def room():
    r = BunkerGameRoom('SPEAK', 'p0', 'Алекс')
    for i in range(1, 6):
        r.add_player(f'p{i}', f'Игрок {i}')
    r.start_game(capacity=2, enable_events=False, skip_prologue=True)
    r.speakers_order = list(r.players)
    return r


def snapshot(r):
    return copy.deepcopy({**r.__dict__, 'players': {pid:p.__dict__ for pid,p in r.players.items()}})


def give(r, key, actor='p0'):
    row = next(x for x in d.SPECIAL_CARDS if x['id'] == key)
    r.players[actor].cards['special'] = {
        'category': 'special', 'card_id': key, 'value': row['title'],
        'details': row['desc'], 'used': False, 'revealed': False,
    }


def apply(r, key='speech_questions', target='p1', actor='p0', text=None):
    give(r, key, actor)
    if text is None and key in speech.INPUTS:
        text = 'Пельмень'
    r.use_special_card(actor, target, option_text=text)
    return r.speech_effects[target]


@pytest.mark.parametrize('key', speech.SPEECH_CARDS)
def test_nine_cards_in_both_deal_modes_and_events_off(key):
    rows = [c for c in d.SPECIAL_CARDS if c['id'] == key]
    assert len(rows) == 1 and rows[0]['target'] == 'player'
    assert key in sc.DEFINITIONS
    for mode in ('balanced', 'full_random'):
        pools = []
        original = d.random.sample
        def sample(population, k):
            if population and isinstance(population[0], dict) and 'phase' in population[0]:
                pools.append({r['id'] for r in population})
            return original(population, k)
        with patch.object(d.random, 'sample', side_effect=sample):
            d.generate_game_deck(6, enable_events=False, deal_mode=mode)
        assert any(key in pool for pool in pools)


@pytest.mark.parametrize('key', speech.SPEECH_CARDS)
def test_reveal_does_not_consume_effect_first_speech_does(key):
    r = room()
    effect = apply(r, key)
    for _ in r.players:
        assert effect['turn'] is None
        r.next_reveal_player(force=True)
    assert r.phase == 'SPEECH' and effect['turn'] is None
    r.next_speaker()
    assert r.get_current_speaker().id == 'p1' and effect['turn'] is not None
    r.host_restart_phase()
    assert r.speech_effects['p1']['id'] == effect['id']
    r.next_speaker()
    assert 'p1' not in r.speech_effects
    assert r.players['p0'].cards['special']['used']
    assert not r.players['p1'].is_silenced


@pytest.mark.parametrize('phase', ['SPEECH', 'ACCUSATION', 'JUSTIFICATION'])
@pytest.mark.parametrize('advance', ['normal', 'timer', 'host'])
def test_current_speech_expires_on_all_advances(phase, advance):
    r = room()
    if phase == 'SPEECH':
        r.start_speech_phase(); r.host_grant_speech_speaker('p1')
        finish = r.next_speaker
    elif phase == 'ACCUSATION':
        r.start_accusation_phase(); r.host_grant_debate_speaker('p1')
        finish = r.next_accusation_speaker
    else:
        r.start_justification(['p1','p2'], True, [], 50)
        finish = r.next_justification_speaker
    effect = apply(r)
    assert effect['turn'] is not None
    if advance == 'normal': finish()
    elif advance == 'host': r.host_set_phase('VOTING')
    else:
        r.timer_seconds_left = 1
        r.tick_timer()
    assert not r.speech_effects
    assert not r.players['p1'].has_immunity and not r.players['p1'].double_vote


def test_pending_effect_survives_next_round_and_silenced_skipped_turn():
    r = room(); r.start_accusation_phase(); r.host_grant_debate_speaker('p5')
    effect = apply(r)
    r.next_accusation_speaker()
    assert effect['turn'] is None
    r.round_number += 1; r.start_round()
    r.players['p1'].is_speech_silenced = True
    r.start_speech_phase()
    while r.phase == 'SPEECH': r.next_speaker()
    assert effect['turn'] is None
    r.players['p1'].is_speech_silenced = False
    r.host_grant_debate_speaker('p1')
    assert effect['turn'] is not None
    r.next_accusation_speaker()
    assert 'p1' not in r.speech_effects


@pytest.mark.parametrize('action', ['remove', 'eliminate', 'final', 'new_game'])
def test_effect_cleanup(action):
    r = room(); apply(r)
    if action == 'remove': r.remove_player('p1')
    elif action == 'eliminate':
        r.start_voting(); r.phase = 'VOTE_RESULTS'
        r.vote_results = {'eliminated_id':'p1','eliminated_ids':['p1']}
        r.confirm_elimination()
    elif action == 'final': r.trigger_final()
    else: r.start_game(capacity=2, enable_events=False, skip_prologue=True)
    assert not r.speech_effects


def test_no_stacking_self_dead_or_muted_targets_no_card_consumption():
    r = room(); apply(r)
    give(r, 'speech_short', 'p2')
    for target in ['p1','p2','missing']:
        with pytest.raises(ValueError): r.use_special_card('p2', target)
        assert not r.players['p2'].cards['special']['used']
    r.players['p3'].is_alive = False
    r.players['p4'].is_quarantined = True
    r.players['p5'].is_speech_silenced = True
    for target in ['p3','p4','p5']:
        with pytest.raises(ValueError): r.use_special_card('p2', target)
    available = sc.special_availability(r, 'p2')
    assert available['target_ids'] == ['p0']


@pytest.mark.parametrize('key,value', [
    ('speech_word',None),('speech_word',''),('speech_word','два слова'),('speech_word',17),
    ('speech_word','а'*33),('speech_word','-слово'),('speech_style','а'*81),
    ('speech_style','робот\nдиктор'),('speech_address',{}),('speech_address','а'*61),
    ('speech_short','внезапная настройка'),('speech_style','слово\u202e'),
])
def test_invalid_options_are_transactional(key, value):
    r = room(); give(r,key); before = snapshot(r)
    with pytest.raises(ValueError): r.use_special_card('p0','p1',option_text=value)
    assert snapshot(r) == before


def test_custom_text_is_public_only_after_use_and_no_other_cards_leak():
    r = room(); give(r,'speech_style')
    private = r.players['p1'].cards['health']['value'] = 'SECRET_MEDICAL_TEXT'
    assert 'input_config' in r.get_state('p0')['players'][0]['cards']['special']
    assert 'input_config' not in r.get_state('p1')['players'][0]['cards']['special']
    r.use_special_card('p0','p1',option_text='  Как   робот <кот>  ')
    for viewer in ['p0','p2',None]:
        state = r.get_state(viewer)
        effect = state['speech_effects'][0]
        assert 'Как робот <кот>' in effect['instruction']
        assert 'turn' not in effect
        assert private not in json.dumps(state, ensure_ascii=False)


def test_unexpected_apply_error_rolls_back_restriction_and_consumption():
    r = room(); give(r,'speech_questions'); before=snapshot(r)
    original=speech.apply_effect
    def fail(*args):
        original(*args)
        raise RuntimeError('after applying')
    with patch.object(speech,'apply_effect',side_effect=fail),pytest.raises(RuntimeError):
        r.use_special_card('p0','p1')
    assert snapshot(r) == before


def test_prompter_authority_count_replay_expiry_and_public_words():
    r = room(); effect=apply(r,'speech_prompter')
    def prompt(actor='p0',index=0,word='Кабачок',eid=None):
        return r.send_speech_prompt(actor,'p1',eid or effect['id'],index,word)
    with pytest.raises(ValueError): prompt()
    r.start_speech_phase();r.next_speaker()
    with pytest.raises(ValueError): prompt('p2')
    with pytest.raises(ValueError): prompt(eid='old-effect')
    r.host_pause_timer(True)
    with pytest.raises(ValueError): prompt()
    r.host_pause_timer(False)
    with pytest.raises(ValueError): prompt(word='два слова')
    with pytest.raises(ValueError): prompt(index=True)
    assert effect['prompts']==[]
    for i,word in enumerate(['Кабачок','Тапок','Пельмень']):
        prompt(index=i,word=word)
        with pytest.raises(ValueError): prompt(index=i,word=word)
        assert r.get_state('p3')['speech_effects'][0]['prompts'][-1]==word
    with pytest.raises(ValueError): prompt(index=3)
    assert not r.get_state('p0')['speech_effects'][0]['can_prompt']
    r.next_speaker()
    with pytest.raises(ValueError): prompt(index=3)
    assert not r.get_state('p0')['speech_effects']


def test_review_blocks_applying_and_prompting_without_consuming_words():
    r=room();effect=apply(r,'speech_prompter')
    r.start_speech_phase();r.next_speaker()
    r.enqueue_review('event',{})
    with pytest.raises(ValueError,match='показ результата'):
        r.send_speech_prompt('p0','p1',effect['id'],0,'Слово')
    give(r,'speech_questions','p2')
    with pytest.raises(ValueError,match='показ результата'):
        r.use_special_card('p2','p3')
    assert not effect['prompts'] and not r.players['p2'].cards['special']['used']


def test_prompter_leaving_does_not_leave_an_unusable_restriction():
    r=room();apply(r,'speech_prompter')
    r.remove_player('p0')
    assert not r.speech_effects


@pytest.mark.parametrize('bad_target,bad_effect', [([], 'id'),('p1', {}), (None, None)])
def test_malformed_prompt_identity_is_rejected(bad_target,bad_effect):
    r=room();apply(r,'speech_prompter')
    with pytest.raises(ValueError):r.send_speech_prompt('p0',bad_target,bad_effect,0,'Слово')
    assert not r.speech_effects['p1']['prompts']
