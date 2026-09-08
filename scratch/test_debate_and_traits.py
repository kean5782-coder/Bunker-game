"""
Automated verification for turn-based debates, diverse/bad traits, round 2+ quotas, and event odds.
"""
import sys
import os
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "Бункер")))

from server.deck_data import (
    generate_game_deck,
    get_random_experience,
    EXPERIENCE_PRESETS,
    PROFESSIONS,
    HEALTH_CONDITIONS,
    HOBBIES,
    BAGGAGE_ITEMS,
    FACTS,
    calculate_event_odds,
    BUNKER_EVENTS,
)
from server.game_engine import (
    BunkerGameRoom,
    PHASE_LOBBY,
    PHASE_SPEECH,
    PHASE_DEBATE,
    PHASE_VOTING,
    PHASE_VOTE_RESULTS
)

def test_deck_diversity():
    print("\n--- TEST 1: Deck Diversity & Realistic/Bad Traits ---")
    
    # 1. Experience presets
    exp_samples = [get_random_experience() for _ in range(100)]
    print(f"Sample experiences: {exp_samples[:5]}")
    has_intern = any("Стажер" in e or "мес" in e for e in exp_samples)
    has_unemployed = any("Без опыта" in e or "Безработный" in e or "Самоучка" in e for e in exp_samples)
    assert has_intern or has_unemployed, "Experience presets should include interns/unemployed/novices!"
    print("PASS: Experience distribution contains interns/novices/varied durations.")

    # 2. Controversial professions
    bad_prof_names = ["Коллектор", "Таролог", "Блогер-пранкер", "Инфоцыган", "Фейсконтрольщик клуба", "Криптоинвестор-банкрот"]
    found_bad = [p["name"] for p in PROFESSIONS if any(b in p["name"] for b in ["Коллектор", "Таролог", "Блогер", "Инфоцыган", "Фейсконтрольщик", "Криптоинвестор"])]
    print(f"Found controversial professions in deck: {found_bad}")
    assert len(found_bad) >= 4, "Deck must contain controversial professions!"
    print("PASS: Controversial professions present.")

    # 3. Severe health flaws
    bad_health = [h["name"] for h in HEALTH_CONDITIONS if any(w in h["name"].lower() for w in ["алкоголизм", "эпилепсия", "ожирение", "слепота", "квинке"])]
    print(f"Found severe health conditions: {bad_health}")
    assert len(bad_health) >= 3, "Deck must contain severe health flaws!"
    print("PASS: Severe health flaws present.")

    # 4. Toxic hobbies & junk baggage
    junk_baggage = [b["name"] for b in BAGGAGE_ITEMS if any(w in b["name"].lower() for w in ["тостер", "фантиков", "фламинго", "билеты", "сейф", "доллары"])]
    print(f"Found junk baggage items: {junk_baggage}")
    assert len(junk_baggage) >= 3, "Deck must contain junk baggage items!"
    print("PASS: Junk baggage items present.")

    # 5. Full card generation test
    deck = generate_game_deck(player_count=3)
    card_pack = deck["players_cards"][0]
    print(f"Generated card sample: {card_pack['profession']['value']} | {card_pack['baggage']['value']} | {card_pack['fact']['value']}")
    assert "profession" in card_pack and "baggage" in card_pack
    print("PASS: Card generation fully functional.")

def test_turn_quotas_and_foolproof():
    print("\n--- TEST 2: Round Quotas (Round 1 = 1, Round 2+ = 2, Never 2/1) ---")
    room = BunkerGameRoom(room_code="TEST", host_id="h1", host_name="Ведущий")
    room.add_player("p1", "Alice")
    room.add_player("p2", "Bob")
    room.add_player("p3", "Charlie")
    
    room.start_game(capacity=2, enable_traitor=False, enable_events=False)
    assert room.phase == PHASE_SPEECH
    assert room.round_number == 1
    
    # Round 1 speaker 1: must reveal profession first
    spk1 = room.get_current_speaker()
    assert spk1 is not None
    spk1_id = spk1.id
    
    # Try revealing something other than profession -> should fail
    try:
        room.reveal_player_card(spk1_id, "biology")
        assert False, "Should not allow non-profession card first in Round 1!"
    except ValueError as e:
        print(f"Correctly rejected non-profession card in R1: {e}")

    # Reveal profession
    room.reveal_player_card(spk1_id, "profession")
    state = room.get_state(spk1_id)
    assert state["speaker_status"]["revealed_count"] == 1
    assert state["speaker_status"]["required_count"] == 1
    assert state["speaker_status"]["can_proceed"] is True
    print(f"R1 Speaker status after profession: {state['speaker_status']}")
    room.next_speaker()

    while room.phase == PHASE_SPEECH:
        spk = room.get_current_speaker()
        if spk:
            room.reveal_player_card(spk.id, "profession")
            room.next_speaker()

    assert room.phase == PHASE_DEBATE
    print("PASS: Round 1 speech sequence succeeded.")

    # Now let's test Round 2 quota
    room.round_number = 2
    room.phase = PHASE_SPEECH
    room.speakers_order = [p.id for p in room.get_alive_players()]
    room.active_speaker_idx = 0
    room.turn_revealed_categories.clear()
    
    curr_spk = room.get_current_speaker()
    st_start = room.get_state(curr_spk.id)
    print(f"R2 Start quota: {st_start['speaker_status']['revealed_count']} / {st_start['speaker_status']['required_count']}")
    assert st_start['speaker_status']['required_count'] == 2
    assert st_start['speaker_status']['revealed_count'] == 0
    assert st_start['speaker_status']['can_proceed'] is False

    # Reveal first card in R2 (e.g. biology)
    room.reveal_player_card(curr_spk.id, "biology")
    st_mid = room.get_state(curr_spk.id)
    print(f"R2 Mid quota (after 1st card): {st_mid['speaker_status']['revealed_count']} / {st_mid['speaker_status']['required_count']}")
    # Quota must be 1 / 2, NOT 1 / 1 or 2 / 1!
    assert st_mid['speaker_status']['revealed_count'] == 1
    assert st_mid['speaker_status']['required_count'] == 2
    assert st_mid['speaker_status']['can_proceed'] is False

    # Reveal second card in R2 (e.g. health)
    room.reveal_player_card(curr_spk.id, "health")
    st_done = room.get_state(curr_spk.id)
    print(f"R2 Done quota (after 2nd card): {st_done['speaker_status']['revealed_count']} / {st_done['speaker_status']['required_count']}")
    assert st_done['speaker_status']['revealed_count'] == 2
    assert st_done['speaker_status']['required_count'] == 2
    assert st_done['speaker_status']['can_proceed'] is True

    # Try revealing a 3rd card in R2 -> should fail
    try:
        room.reveal_player_card(curr_spk.id, "hobby")
        assert False, "Should reject revealing more than 2 cards per turn!"
    except ValueError as e:
        print(f"Correctly rejected 3rd reveal: {e}")

    print("PASS: Round 2+ quota stays strictly at 2 throughout the turn.")

def test_turn_based_debates():
    print("\n--- TEST 3: Turn-Based Debates (60s per living player) ---")
    room = BunkerGameRoom(room_code="TEST", host_id="h1", host_name="Ведущий")
    room.add_player("p1", "Alice")
    room.add_player("p2", "Bob")
    room.add_player("p3", "Charlie")
    room.start_game(capacity=2, enable_traitor=False, enable_events=False)

    room.start_debate()
    assert room.phase == PHASE_DEBATE
    assert room.timer_seconds_left == 60
    assert len(room.debate_speakers_order) == len(room.get_alive_players())
    assert room.active_debate_speaker_idx == 0

    first_deb = room.get_current_debate_speaker()
    print(f"First debate speaker: {first_deb.name} (ID: {first_deb.id})")
    assert first_deb.id == room.debate_speakers_order[0]

    # Advance to second debate speaker
    room.next_debate_speaker()
    second_deb = room.get_current_debate_speaker()
    print(f"Second debate speaker: {second_deb.name}")
    assert second_deb.id == room.debate_speakers_order[1]
    assert room.timer_seconds_left == 60

    # Host grants debate speech to specific player (Charlie)
    room.host_grant_debate_speaker("p3")
    cur_deb = room.get_current_debate_speaker()
    print(f"After host grant, speaker: {cur_deb.name}")
    assert cur_deb.id == "p3"
    assert room.timer_seconds_left == 60

    # Cycle remaining debate speakers -> should transition to voting!
    while room.phase == PHASE_DEBATE:
        room.next_debate_speaker()

    print(f"Phase after debate queue finishes: {room.phase}")
    assert room.phase == PHASE_VOTING
    print("PASS: Debate advances sequentially and automatically transitions to voting.")

def test_event_balance_and_odds():
    print("\n--- TEST 4: Hardcore Rebalanced Event Odds (Max <= 80%) ---")
    room = BunkerGameRoom(room_code="TEST", host_id="h1", host_name="Ведущий")
    room.add_player("p1", "Alice")
    room.add_player("p2", "Bob")
    room.add_player("p3", "Charlie")
    room.start_game(capacity=2, enable_traitor=False, enable_events=True)

    # Force all cards to be revealed for maximum possible positive bonuses
    for p in room.players.values():
        for cat, c in p.cards.items():
            c["revealed"] = True

    for tmpl in BUNKER_EVENTS:
        odds = calculate_event_odds(tmpl, room.get_alive_players(), room.get_exiled_players(), volunteer_id=room.players["p1"].id)
        print(f"Event '{tmpl['title']}': Base {odds['base_chance']}%, Final {odds['final_chance']}%")
        assert 10 <= odds['final_chance'] <= 80, f"Event chance {odds['final_chance']} must be clamped [10, 80]!"

    print("PASS: All event odds strictly respect hardcore bounds (10% to 80%).")

if __name__ == "__main__":
    test_deck_diversity()
    test_turn_quotas_and_foolproof()
    test_turn_based_debates()
    test_event_balance_and_odds()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")
