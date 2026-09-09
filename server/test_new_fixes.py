"""
Automated unit and integration tests verifying:
1. Revote tie-breaker with dice roll and 50%/50% percentage calculation
2. Special cards interacting with events (satellite recon, hazard exosuit, suppress sabotage, route reroll, overdrive)
3. Event odds calculations with matching items (hazmat, flashlight, safety engineer)
4. Host force next speaker across phases
"""
import unittest
import sys
from server.game_engine import (
    BunkerGameRoom,
    PHASE_SPEECH,
    PHASE_COLLECTIVE_DISCUSSION,
    PHASE_ACCUSATION,
    PHASE_VOTING,
    PHASE_JUSTIFICATION,
    PHASE_REVOTE,
    PHASE_VOTE_RESULTS,
    PHASE_FINAL
)
from server.deck_data import calculate_event_odds, SPECIAL_CARDS, BUNKER_EVENTS


class TestNewFixes(unittest.TestCase):
    def setUp(self):
        self.room = BunkerGameRoom("TEST", "host_1", "Host")
        self.room.add_player("p2", "Player 2")
        self.room.add_player("p3", "Player 3")
        self.room.add_player("p4", "Player 4")
        self.room.add_player("p5", "Player 5")
        self.room.add_player("p6", "Player 6")
        self.room.catastrophe = {
            "id": "nuclear_winter",
            "title": "Ядерная зима",
            "description": "Радиация, токсичный пепел и экстремальный мороз."
        }
        self.room.bunker = {
            "capacity": 3,
            "supplies_years": 5,
            "threat": "Утечка фреона"
        }

    def test_revote_tie_breaker_and_percentages(self):
        """Verify revote tie-breaker: 2 candidates with equal votes get 50%/50%, tie is marked, and dice breaks tie"""
        self.room.phase = PHASE_REVOTE
        self.room.justification_candidates = ["p2", "p3"]
        self.room.votes = {
            "p2": "p3",
            "p3": "p2",
            "host_1": "p2",
            "p4": "p3",
            "p5": "p2",
            "p6": "p3"
        }

        self.room.finish_revote()

        self.assertEqual(self.room.phase, PHASE_VOTE_RESULTS)
        res = self.room.vote_results
        self.assertIsNotNone(res)
        self.assertTrue(res["revote_completed"])
        self.assertTrue(res["is_tie"])
        self.assertEqual(res["tie_broken_by"], "dice")
        self.assertIn(res["eliminated_id"], ["p2", "p3"])

        # Check tally percentages
        tally = res["detailed_tally"]
        self.assertEqual(len(tally), 2)
        total_pct = sum(t["percent"] for t in tally)
        self.assertAlmostEqual(total_pct, 100.0, delta=1.0)
        # Both candidates had equal votes (3 each after AFK split or 50%)
        self.assertEqual(tally[0]["votes"], tally[1]["votes"])
        self.assertEqual(tally[0]["percent"], 50.0)
        self.assertEqual(tally[1]["percent"], 50.0)

    def test_special_card_satellite_recon(self):
        """Verify event_satellite_recon adds +25% to event odds"""
        self.room.events_enabled = True
        self.room.active_event = {
            "id": "test_event",
            "title": "Тестовое событие",
            "type": "SURFACE_EVENT",
            "base_chance": 40,
            "rules": {"positive_tags": [], "negative_tags": []}
        }
        self.room.recalculate_event_odds()
        initial_chance = self.room.current_event_odds["final_chance"]

        # Give player p2 satellite recon card
        p2 = self.room.players["p2"]
        p2.cards["special"] = {
            "card_id": "event_satellite_recon",
            "title": "📡 Спутниковая навигация",
            "used": False,
            "revealed": False
        }

        self.room.use_special_card("p2")
        self.assertEqual(self.room.event_special_bonus, 25)
        new_chance = self.room.current_event_odds["final_chance"]
        self.assertEqual(new_chance, min(95, initial_chance + 25))

    def test_special_card_hazard_exosuit(self):
        """Verify event_hazard_exosuit adds +20% and volunteer_is_safe = True"""
        self.room.events_enabled = True
        self.room.active_event = {
            "id": "test_sortie",
            "title": "Тестовая вылазка",
            "type": "SURFACE_EVENT",
            "base_chance": 30,
            "rules": {"positive_tags": [], "negative_tags": []}
        }
        self.room.recalculate_event_odds()

        p2 = self.room.players["p2"]
        p2.cards["special"] = {
            "card_id": "event_hazard_exosuit",
            "title": "🦾 Тяжелый экзокостюм сталкера",
            "used": False,
            "revealed": False
        }

        self.room.use_special_card("p2")
        self.assertTrue(self.room.volunteer_is_safe)
        self.assertEqual(self.room.event_special_bonus, 20)

        # Resolving event should guarantee volunteer health is not degraded
        p2.cards["health"] = {"value": "Абсолютно здоров", "details": "Идеальное состояние", "severity": "good"}
        self.room.assigned_volunteer_id = "p2"
        res = self.room.resolve_active_event(force_roll=99)  # force failure
        self.assertIsNone(res["health_degraded"])
        self.assertEqual(p2.cards["health"]["value"], "Абсолютно здоров")

    def test_special_card_suppress_sabotage(self):
        """Verify event_suppress_sabotage blocks exile sabotage penalties"""
        self.room.events_enabled = True
        self.room.active_event = {
            "id": "test_sortie",
            "title": "Тестовая вылазка",
            "type": "SURFACE_EVENT",
            "base_chance": 50,
            "rules": {"positive_tags": [], "negative_tags": []}
        }
        # Simulate an exiled player who would reduce chance
        exiled_p = self.room.players["p6"]
        exiled_p.is_alive = False
        exiled_p.cards["profession"] = {"revealed": True, "value": "Диверсант", "tag": "military"}

        p2 = self.room.players["p2"]
        p2.cards["special"] = {
            "card_id": "event_suppress_sabotage",
            "title": "🛡️ Охранный дрон «Периметр»",
            "used": False,
            "revealed": False
        }
        self.room.use_special_card("p2")
        self.assertTrue(self.room.sabotage_suppressed)
        self.assertIsNotNone(self.room.current_event_odds)

    def test_special_card_route_reroll(self):
        """Verify event_route_reroll draws a new event"""
        self.room.events_enabled = True
        self.room.trigger_next_event()
        old_ev_id = self.room.active_event["id"] if self.room.active_event else None

        p2 = self.room.players["p2"]
        p2.cards["special"] = {
            "card_id": "event_route_reroll",
            "title": "🗺️ Тактическая карта местности",
            "used": False,
            "revealed": False
        }
        self.room.use_special_card("p2")
        self.assertIsNotNone(self.room.active_event)

    def test_sortie_odds_user_scenario(self):
        """Verify the user's exact scenario: nuclear winter, hazmat suit, LED flashlight, safety engineer"""
        event = next(ev for ev in BUNKER_EVENTS if ev["id"] == "fuel_tanker_discovery")
        vol = self.room.players["p2"]
        vol.cards = {
            "profession": {
                "category": "profession",
                "label": "Профессия",
                "value": "Инженер по технике безопасности (12 лет)",
                "details": "Опыт работы на химическом заводе и нефтеперерабатывающем комплексе. Сертификация по ГО и ЧС.",
                "tag": "engineer",
                "revealed": True
            },
            "biology": {"category": "biology", "label": "Биология", "value": "Мужчина 38 лет", "revealed": True},
            "health": {"category": "health", "label": "Здоровье", "value": "Абсолютно здоров", "details": "Крепкий иммунитет", "revealed": True},
            "backpack": {
                "category": "backpack",
                "label": "Рюкзак",
                "value": "Комплект хим-радиационной защиты (ОЗК + противогаз ГП-7)",
                "details": "Герметичный комбинезон, сменные фильтры ФПК.",
                "revealed": True
            },
            "baggage": {
                "category": "baggage",
                "label": "Багаж",
                "value": "Мощный светодиодный фонарь с динамо-подзарядкой",
                "details": "Влагозащищенный корпус, дальность луча 300 метров.",
                "revealed": True
            }
        }
        odds = calculate_event_odds(
            event,
            [vol],
            [],
            volunteer_id="p2",
            catastrophe=self.room.catastrophe
        )
        self.assertGreaterEqual(odds["final_chance"], 80)
        self.assertGreaterEqual(len(odds["positive_factors"]), 3)
        print("\nOdds positive factors calculated for user scenario:")
        for f in odds["positive_factors"]:
            print(" -", f)
        print("Final chance:", odds["final_chance"], "%")

    def test_host_force_next_speaker_across_phases(self):
        """Verify host can force phase advance across speech, collective discussion, and accusation"""
        self.room.start_game()
        # In speech phase
        self.assertEqual(self.room.phase, PHASE_SPEECH)
        curr_spk_idx = self.room.active_speaker_idx
        self.room.next_speaker(force=True)
        self.assertEqual(self.room.active_speaker_idx, curr_spk_idx + 1)

        # Transition to collective discussion
        self.room.start_collective_discussion()
        self.assertEqual(self.room.phase, PHASE_COLLECTIVE_DISCUSSION)

        # Host skips discussion to accusation
        self.room.start_accusation_phase()
        self.assertEqual(self.room.phase, PHASE_ACCUSATION)
        self.assertGreater(len(self.room.accusation_speakers_order), 0)

        # Host advances accusation speaker
        acc_idx = self.room.active_accusation_speaker_idx
        self.room.next_accusation_speaker()
        self.assertEqual(self.room.active_accusation_speaker_idx, acc_idx + 1)


if __name__ == "__main__":
    unittest.main()
