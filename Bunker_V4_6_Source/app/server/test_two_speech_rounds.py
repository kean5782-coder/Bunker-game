import unittest

from server.game_engine import (
    BunkerGameRoom,
    PHASE_REVEAL,
    PHASE_SPEECH,
    PHASE_ACCUSATION,
    PHASE_VOTING,
    PHASE_COLLECTIVE_DISCUSSION,
)


class TestTwoSpeechRounds(unittest.TestCase):
    def make_room(self):
        room = BunkerGameRoom('TALK', 'host', 'Host')
        room.add_player('p2', 'Alice')
        room.add_player('p3', 'Bob')
        room.start_game(capacity=2, enable_events=False)
        return room

    def test_standard_flow_is_60_then_30_then_vote(self):
        room = self.make_room()
        self.assertEqual(room.phase, PHASE_REVEAL)
        for _ in room.speakers_order:
            room.next_reveal_player(force=True)
        self.assertEqual(room.phase, PHASE_SPEECH)
        self.assertEqual(room.speech_duration_sec, 60)
        self.assertEqual(room.timer_seconds_left, 60)

        first_round_count = len(room.speakers_order)
        for _ in range(first_round_count):
            room.next_speaker(force=True)

        self.assertEqual(room.phase, PHASE_ACCUSATION)
        self.assertNotEqual(room.phase, PHASE_COLLECTIVE_DISCUSSION)
        self.assertEqual(room.accusation_duration_sec, 30)
        self.assertEqual(room.timer_seconds_left, 30)
        self.assertEqual(len(room.accusation_speakers_order), 3)

        second_round_count = len(room.accusation_speakers_order)
        for _ in range(second_round_count):
            room.next_accusation_speaker()

        self.assertEqual(room.phase, PHASE_VOTING)

    def test_legacy_collective_action_skips_directly_to_second_speeches(self):
        room = self.make_room()
        room.start_collective_discussion()
        self.assertEqual(room.phase, PHASE_ACCUSATION)
        self.assertEqual(room.timer_seconds_left, 30)

    def test_second_round_is_half_of_custom_first_round(self):
        room = BunkerGameRoom('FAST', 'host', 'Host')
        room.add_player('p2', 'Alice')
        room.add_player('p3', 'Bob')
        room.start_game(capacity=2, enable_events=False, speech_duration=30)
        self.assertEqual(room.speech_duration_sec, 30)
        self.assertEqual(room.accusation_duration_sec, 15)


if __name__ == '__main__':
    unittest.main()
