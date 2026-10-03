"""
Unit tests for the official Bunker game rules:
- Option 1B: 11 character card categories
- Option 2B: Dynamic card quotas based on player count
- Option 3B: Alternating round order (forward/reverse)
- Option 4B: Two-phase discussion (collective open mic + accusations round)
- Option 5B: Voting rules (15s, AFK self-vote, R1 skip, double elimination, >=70% instant exile, <70% justification + revote)
- Option 6A: Mathematical survival evaluation with all 11 cards & D100 events
"""

import unittest
from server.deck_data import (
    generate_game_deck,
    evaluate_survival,
    PROFESSIONS
)
from server.game_engine import (
    GameRoom,
    Player,
    get_reveal_quota,
    PHASE_REVEAL,
    PHASE_SPEECH,
    PHASE_COLLECTIVE_DISCUSSION,
    PHASE_ACCUSATION,
    PHASE_VOTING,
    PHASE_JUSTIFICATION,
    PHASE_REVOTE,
    PHASE_VOTE_RESULTS,
    PHASE_LAST_WORD,
    PHASE_FINAL
)


class TestOfficialRules(unittest.TestCase):

    def test_block_1_eleven_cards(self):
        """Block 1 (Option 1B): Deck generator creates 11 card categories"""
        deck = generate_game_deck(num_players=4, bunker_capacity=2, enable_traitor=True)
        player_cards = deck["players_cards"][0]
        
        expected_categories = [
            "gender", "body", "trait", "profession", "health", 
            "hobby", "phobia", "big_inventory", "backpack", "fact", 
            "special"
        ]
        for cat in expected_categories:
            self.assertIn(cat, player_cards, f"Category '{cat}' must be in player's cards")
            card = player_cards[cat]
            self.assertEqual(card["category"], cat)
            self.assertTrue(bool(card.get("value")), f"Card '{cat}' must have a value")
            self.assertTrue(bool(card.get("icon")), f"Card '{cat}' must have an icon")
            self.assertTrue(bool(card.get("label")), f"Card '{cat}' must have a label")

        all_traitors = [p for p in deck["players_cards"] if "traitor" in p]
        self.assertEqual(len(all_traitors), 1)

    def test_block_2_dynamic_reveal_quota(self):
        """Block 2 (Option 2B): Dynamic quota based on player count"""
        self.assertEqual(get_reveal_quota(5, round_number=1, unrevealed_count=10), 3)
        self.assertEqual(get_reveal_quota(6, round_number=2, unrevealed_count=7), 3)
        self.assertEqual(get_reveal_quota(6, round_number=3, unrevealed_count=4), 2)
        self.assertEqual(get_reveal_quota(6, round_number=4, unrevealed_count=2), 1)

        self.assertEqual(get_reveal_quota(7, round_number=1, unrevealed_count=10), 3)
        self.assertEqual(get_reveal_quota(8, round_number=2, unrevealed_count=7), 2)
        self.assertEqual(get_reveal_quota(8, round_number=3, unrevealed_count=5), 2)
        self.assertEqual(get_reveal_quota(8, round_number=4, unrevealed_count=3), 1)

        self.assertEqual(get_reveal_quota(10, round_number=1, unrevealed_count=10), 2)
        self.assertEqual(get_reveal_quota(12, round_number=2, unrevealed_count=8), 2)
        self.assertEqual(get_reveal_quota(9, round_number=3, unrevealed_count=6), 2)
        self.assertEqual(get_reveal_quota(9, round_number=4, unrevealed_count=4), 1)

    def test_block_3_alternating_round_order(self):
        """Block 3 (Option 3B): Alternating order across rounds"""
        room = GameRoom("TEST", "h1", "Host")
        room.add_player("p2", "Player 2")
        room.add_player("p3", "Player 3")
        room.add_player("p4", "Player 4")
        room.start_game(capacity=2, enable_events=False)

        self.assertEqual(room.round_number, 1)
        r1_order = list(room.speakers_order)
        self.assertEqual(r1_order, ["h1", "p2", "p3", "p4"])

        room.round_number = 2
        room.start_round()
        self.assertEqual(room.speakers_order, list(reversed(r1_order)))

        room.round_number = 3
        room.start_round()
        self.assertEqual(room.speakers_order, r1_order)

    def test_block_4_two_phase_discussion(self):
        """Block 4 (Option 4B): Collective discussion (60s) -> Accusation round (30s) -> Voting"""
        room = GameRoom("TEST", "h1", "Host")
        room.add_player("p2", "Player 2")
        room.add_player("p3", "Player 3")
        room.start_game(capacity=2, enable_events=False)

        for _ in range(len(room.speakers_order)):
            room.next_reveal_player(force=True)
        self.assertEqual(room.phase, PHASE_SPEECH)
        for _ in range(len(room.speakers_order)):
            room.next_speaker(force=True)

        self.assertEqual(room.phase, PHASE_ACCUSATION)
        self.assertEqual(room.timer_seconds_left, room.accusation_duration_sec)
        self.assertIsNotNone(room.get_current_accusation_speaker())

        speakers_count = len(room.accusation_speakers_order)
        for i in range(speakers_count - 1):
            room.next_accusation_speaker()
            self.assertEqual(room.phase, PHASE_ACCUSATION)

        room.next_accusation_speaker()
        self.assertEqual(room.phase, PHASE_VOTING)

    def test_block_5_voting_timeout_self_vote(self):
        """Block 5 (Option 5B): AFK / timeout counts as self-vote"""
        room = GameRoom("TEST", "h1", "Host")
        room.add_player("p2", "Player 2")
        room.add_player("p3", "Player 3")
        room.start_game(capacity=2, enable_events=False)
        room.start_voting()

        room.cast_vote("h1", "p2")
        self.assertNotIn("p2", room.votes)
        self.assertNotIn("p3", room.votes)

        room.finish_voting()
        self.assertEqual(room.votes["p2"], "p2")
        self.assertEqual(room.votes["p3"], "p3")

    def test_block_5_round_1_skip_and_double_elimination(self):
        """Block 5 (Option 5B): Round 1 skip voting leads to double elimination in Round 2"""
        room = GameRoom("TEST", "h1", "Host")
        room.add_player("p2", "Player 2")
        room.add_player("p3", "Player 3")
        room.add_player("p4", "Player 4")
        room.start_game(capacity=1, enable_events=False)
        self.assertEqual(room.round_number, 1)
        room.start_voting()

        room.cast_vote("h1", "SKIP_ROUND")
        room.cast_vote("p2", "SKIP_ROUND")
        room.cast_vote("p3", "SKIP_ROUND")

        self.assertEqual(room.phase, PHASE_VOTE_RESULTS)
        self.assertTrue(room.vote_results["skipped_round"])
        self.assertTrue(room.double_elimination_pending)

        room.confirm_elimination()
        self.assertEqual(room.round_number, 2)
        self.assertTrue(room.double_elimination_pending)

        room.start_voting()
        room.cast_vote("p3", "p4")
        room.cast_vote("p4", "p2")

        room.finish_voting()
        self.assertEqual(room.phase, PHASE_JUSTIFICATION)

    def test_block_5_instant_exile_threshold(self):
        """Block 5 (Option 5B): >= 70% threshold means instant exile"""
        room = GameRoom("TEST", "h1", "Host")
        room.add_player("p2", "Player 2")
        room.add_player("p3", "Player 3")
        room.add_player("p4", "Player 4")
        room.start_game(capacity=2, enable_events=False)
        room.round_number = 2
        room.start_voting()

        room.cast_vote("h1", "p2")
        room.cast_vote("p3", "p2")
        room.cast_vote("p4", "p2")
        room.cast_vote("p2", "p4")

        self.assertEqual(room.phase, PHASE_VOTE_RESULTS)
        self.assertTrue(room.vote_results.get("instant_exile"))
        self.assertEqual(room.vote_results.get("eliminated_id"), "p2")

    def test_block_5_justification_and_revote(self):
        """Block 5 (Option 5B): < 70% threshold leads to justification speech and 15s revote"""
        room = GameRoom("TEST", "h1", "Host")
        room.add_player("p2", "Player 2")
        room.add_player("p3", "Player 3")
        room.add_player("p4", "Player 4")
        room.start_game(capacity=2, enable_events=False)
        room.round_number = 2
        room.start_voting()

        room.cast_vote("h1", "p2")
        room.cast_vote("p3", "p2")
        room.cast_vote("p4", "p3")
        room.cast_vote("p2", "p4")

        self.assertEqual(room.phase, PHASE_JUSTIFICATION)
        self.assertIn("p2", room.justification_candidates)

        room.next_justification_speaker()
        self.assertEqual(room.phase, PHASE_REVOTE)
        self.assertEqual(room.timer_seconds_left, room.revote_duration_sec)

        room.cast_vote("h1", "p2")
        room.cast_vote("p3", "p2")
        room.cast_vote("p4", "p2")
        room.cast_vote("p2", "p2")

        self.assertEqual(room.phase, PHASE_VOTE_RESULTS)
        self.assertTrue(room.vote_results.get("revote_completed"))
        self.assertEqual(room.vote_results.get("eliminated_id"), "p2")

    def test_block_6_survival_evaluation(self):
        """Block 6 (Option 6A): Mathematical survival model evaluates all 11 card categories"""
        deck = generate_game_deck(num_players=3, bunker_capacity=3, enable_traitor=False)
        survivors = deck["players_cards"]
        for s in survivors:
            for c in s.values():
                c["revealed"] = True
        
        result = evaluate_survival(
            survivor_cards_list=survivors,
            catastrophe=deck["catastrophe"],
            bunker=deck["bunker"],
            traitor_eliminated=False
        )

        self.assertIn("survival_percent", result)
        self.assertGreaterEqual(result["survival_percent"], 0)
        self.assertLessEqual(result["survival_percent"], 100)
        self.assertIn("breakdown", result)
        self.assertIn("profession_coverage", result["breakdown"])
        self.assertIn("health_status", result["breakdown"])
        self.assertIn("demographics_status", result["breakdown"])
        self.assertIn("inventory_status", result["breakdown"])
        self.assertIn("achievements", result)


if __name__ == "__main__":
    unittest.main()
