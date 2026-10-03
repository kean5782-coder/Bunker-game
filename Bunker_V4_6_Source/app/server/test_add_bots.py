import unittest
import asyncio
from server.game_engine import BunkerGameRoom, PHASE_LOBBY
from server.bot_client import BunkerBot, BOT_NAMES

class TestAddBots(unittest.TestCase):
    def test_add_bots_lobby_names(self):
        room = BunkerGameRoom(room_code="TEST", host_id="host_1", host_name="Ведущий")
        self.assertEqual(room.phase, PHASE_LOBBY)
        
        # Simulate adding 5 bots
        count = 5
        existing_names = {p.name for p in room.players.values()}
        available_names = [n for n in BOT_NAMES if n not in existing_names]
        
        added = []
        for i in range(count):
            name = available_names[i]
            pid = f"bot_{i}"
            room.add_player(pid, name)
            added.append(name)
            
        self.assertEqual(len(room.players), 6) # host + 5 bots
        self.assertEqual(len(added), 5)
        for name in added:
            self.assertTrue(any(p.name == name for p in room.players.values()))

    def test_bot_names_unique(self):
        self.assertGreaterEqual(len(BOT_NAMES), 16)
        self.assertEqual(len(BOT_NAMES), len(set(BOT_NAMES)))

if __name__ == "__main__":
    unittest.main()
