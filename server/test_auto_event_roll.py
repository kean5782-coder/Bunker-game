import unittest
from server.game_engine import BunkerGameRoom, PHASE_VOTE_RESULTS, PHASE_LAST_WORD


class TestAutoEventRoll(unittest.TestCase):
    def test_auto_roll_upon_exile(self):
        room = BunkerGameRoom("TEST", "host_1", "Host")
        room.add_player("p1", "Alice")
        room.add_player("p2", "Bob")
        room.add_player("p3", "Charlie")
        room.add_player("p4", "David")

        room.start_game(capacity=2, enable_events=True)

        # Force a bunker crisis event
        test_event = {
            "id": "test_crisis",
            "type": "BUNKER_CRISIS",
            "title": "Утечка газа",
            "description": "Тестовая утечка",
            "base_chance": 30,
            "rules": {
                "positive": [],
                "negative": [
                    {
                        "type": "health_kw",
                        "keywords": ["астма"],
                        "penalty": 20,
                        "reason": "{player} задыхается"
                    }
                ]
            }
        }
        room.active_event = test_event

        # Give Bob asthma (revealed)
        room.players["p2"].cards["health"] = {
            "value": "Бронхиальная астма",
            "desc": "Тяжелая форма",
            "revealed": True
        }

        room.recalculate_event_odds()
        initial_chance = room.current_event_odds["final_chance"]

        # Move to VOTE_RESULTS
        room.phase = PHASE_VOTE_RESULTS
        room.vote_results = {"eliminated_id": "p2"}

        # Confirm elimination of Bob
        room.confirm_elimination("p2")

        # Bob should be eliminated
        self.assertFalse(room.players["p2"].is_alive)

        # Phase should be LAST_WORD
        self.assertEqual(room.phase, PHASE_LAST_WORD)
        self.assertEqual(room.eliminated_in_last_word_id, "p2")

        # Event should have been automatically resolved
        self.assertIsNotNone(room.last_resolved_event)
        self.assertIsNone(room.active_event)

        # Odds without Bob should be higher than with Bob
        chance_used = room.last_resolved_event["chance_required"]
        self.assertGreater(chance_used, initial_chance)

    def test_auto_roll_upon_no_elimination(self):
        """Если по итогам голосования никто не изгнан, событие все равно автоматически разрешается"""
        room = BunkerGameRoom("TEST_NO_ELIM", "host_1", "Host")
        room.add_player("p1", "Alice")
        room.add_player("p2", "Bob")
        room.start_game(capacity=1, enable_events=True)

        self.assertIsNotNone(room.active_event)

        # Фаза результатов с пустым изгнанием
        room.phase = PHASE_VOTE_RESULTS
        room.vote_results = {"eliminated_id": None, "threshold_failed": True}

        room.confirm_elimination()

        # Событие 1-го раунда разрешилось автоматически
        self.assertIsNotNone(room.last_resolved_event)
        # Игра перешла во 2-й раунд и вытянула новое событие
        self.assertEqual(room.round_number, 2)


if __name__ == "__main__":
    unittest.main()
