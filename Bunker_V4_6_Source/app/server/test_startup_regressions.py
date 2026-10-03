import json
import unittest

from server.game_engine import BunkerGameRoom, PHASE_PROLOGUE, PHASE_REVEAL, PHASE_SPEECH, PHASE_ACCUSATION, PHASE_VOTING


class TestStartupRegressions(unittest.TestCase):
    def test_prologue_state_for_every_client_and_first_turn(self):
        room = BunkerGameRoom('BOOT', 'host', 'Host')
        room.add_player('p2', 'Alice')
        room.add_player('p3', 'Bob')
        room.start_game(capacity=2, enable_events=False, enable_traitor=True, skip_prologue=False)
        self.assertEqual(room.phase, PHASE_PROLOGUE)

        # Broadcasting to other players used to crash on the synergies list.
        for viewer in ['host', 'p2', 'p3', None]:
            state = room.get_state(viewer)
            json.dumps(state)
            for player in state['players']:
                for card in player['cards'].values():
                    self.assertIsInstance(card, dict)

        for player_id in room.players:
            room.enter_bunker(player_id)
        self.assertEqual(room.phase, PHASE_REVEAL)
        self.assertEqual(room.timer_seconds_left, 60)
        speaker = room.get_current_speaker()
        other = next(pid for pid in room.players if pid != speaker.id)
        with self.assertRaises(ValueError):
            room.reveal_player_card(other, 'profession')
        room.reveal_player_card(speaker.id, 'profession')
        self.assertTrue(speaker.cards['profession']['revealed'])

        for _ in room.speakers_order:
            room.timer_seconds_left = 1
            room.tick_timer()
            json.dumps(room.get_state(other))
        self.assertEqual(room.phase, PHASE_SPEECH)
        self.assertEqual(room.timer_seconds_left, 60)
        for _ in room.speakers_order:
            room.timer_seconds_left = 1
            room.tick_timer()
        self.assertEqual(room.phase, PHASE_ACCUSATION)
        self.assertEqual(room.timer_seconds_left, 30)
        for _ in room.accusation_speakers_order:
            room.timer_seconds_left = 1
            room.tick_timer()
        self.assertEqual(room.phase, PHASE_VOTING)


if __name__ == '__main__':
    unittest.main()
