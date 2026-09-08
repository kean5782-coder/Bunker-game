"""
Тесты новых балансных и геймплейных механик:
1. Балансированная раздача колоды (гарантированные медик + инженер, лимит бесполезных, здоровье, спецкарты).
2. Синергии и антагонизмы профессий в расчете выживания.
3. Штраф за перенаселение (extra_bunk).
4. Кулдаун Права Вето (1 раунд).
5. Обет молчания (silence_player).
6. Разоблачение подсмотренной карты (announce_peeked).
7. Механика «Вендетта изгнанных».
8. Быстрый режим «Метеорит».
9. Фаза «Последнее слово».
"""

import unittest
from server.deck_data import (
    generate_game_deck, 
    evaluate_survival, 
    calculate_event_odds,
    resolve_event_roll,
    is_exile_alive_on_surface
)
from server.game_engine import (
    BunkerGameRoom,
    PHASE_LOBBY,
    PHASE_SPEECH,
    PHASE_DEBATE,
    PHASE_VOTING,
    PHASE_VOTE_RESULTS,
    PHASE_LAST_WORD,
    PHASE_FINAL
)

class TestNewMechanics(unittest.TestCase):
    def test_balanced_deck_generation(self):
        """Проверка гарантированного баланса раздачи колоды для 6 игроков"""
        deck = generate_game_deck(6)
        cards_list = deck["players_cards"]
        prof_tags = [c["profession"]["tag"] for c in cards_list]
        
        # Гарантия наличия медицины и инженерии/науки
        self.assertIn("medicine", prof_tags, "Должен быть хотя бы 1 медик")
        self.assertTrue(
            any(t in ["engineering", "science", "technical", "tech"] for t in prof_tags),
            "Должен быть хотя бы 1 инженер или ученый"
        )
        
        # Лимит бесполезных профессий (<= 25% от 6 игроков -> не более 1-2)
        useless_count = prof_tags.count("useless")
        self.assertLessEqual(useless_count, 2, "Не более 25% бесполезных профессий")
        
        # extra_bunk не более 1
        specials = [c["special"]["card_id"] for c in cards_list if "special" in c]
        self.assertLessEqual(specials.count("extra_bunk"), 1, "Спецкарта extra_bunk не более 1 на игру")

    def test_synergies_and_antagonisms(self):
        """Проверка бонусов синергии и штрафов антагонизма"""
        deck = generate_game_deck(6)
        cat = deck["catastrophe"]
        bunk = deck["bunker"]
        
        # Синергия: Медицина + Наука
        survivors_synergy = [
            {"id": "p1", "name": "П1", "cards": {"profession": {"value": "Врач-хирург", "tag": "medicine", "desc": "Хирургические операции"}}},
            {"id": "p2", "name": "П2", "cards": {"profession": {"value": "Ученый-микробиолог", "tag": "science", "desc": "Исследование микроорганизмов"}}}
        ]
        eval_syn = evaluate_survival(survivors_synergy, cat, bunk)
        syn_breakdown = [p for p in eval_syn["pros"] if "Синергия" in p]
        self.assertTrue(len(syn_breakdown) > 0, "Должна сработать синергия медицины и науки")

        # Антагонизм: Служба безопасности + Сомнительная личность
        survivors_antagonism = [
            {"id": "p1", "name": "П1", "cards": {"profession": {"value": "Начальник службы безопасности", "tag": "security", "desc": "Охрана"}}},
            {"id": "p2", "name": "П2", "cards": {"profession": {"value": "Коллектор микрозаймов", "tag": "useless", "desc": "Выбивание долгов"}}}
        ]
        eval_ant = evaluate_survival(survivors_antagonism, cat, bunk)
        ant_breakdown = [c for c in eval_ant["cons"] if "недоверие" in c.lower()]
        self.assertTrue(len(ant_breakdown) > 0, "Должен сработать антагонизм охраны и сомнительной личности")

    def test_overcrowding_penalty(self):
        """Проверка штрафа -5% за перенаселение бункера"""
        deck = generate_game_deck(6)
        cat = deck["catastrophe"]
        bunk = dict(deck["bunker"])
        bunk["initial_capacity"] = 2
        
        # 3 выживших при базовой вместимости 2
        survivors = [
            {"id": f"p{i}", "name": f"П{i}", "cards": {}} for i in range(3)
        ]
        eval_res = evaluate_survival(survivors, cat, bunk)
        overcrowd_breakdown = [c for c in eval_res["cons"] if "Перенаселение" in c]
        self.assertTrue(len(overcrowd_breakdown) > 0, "Должен быть начислен штраф за перенаселение")

    def test_veto_cooldown(self):
        """Проверка кулдауна в 1 раунд для Права Вето"""
        room = BunkerGameRoom("VETO", "h1", "Хост")
        room.add_player("p2", "Анна")
        room.add_player("p3", "Борис")
        room.start_game(capacity=2)
        
        # Раунд 1: Вето применяется
        room.phase = PHASE_VOTE_RESULTS
        room.vote_results = {"eliminated_id": "p2"}
        room.players["h1"].cards["special"] = {"card_id": "veto_vote", "title": "Право Вето", "used": False}
        room.use_special_card("h1")
        self.assertTrue(room.veto_used)
        self.assertEqual(room.veto_used_round, 1)

        # Раунд 2: попытка применить Вето снова (например другой игрок)
        room.round_number = 2
        room.phase = PHASE_VOTE_RESULTS
        room.vote_results = {"eliminated_id": "p3"}
        room.players["p2"].cards["special"] = {"card_id": "veto_vote", "title": "Право Вето", "used": False}
        with self.assertRaises(ValueError):
            room.use_special_card("p2")

    def test_silence_and_announce_peeked(self):
        """Проверка Обета молчания и разоблачения подсмотренной карты"""
        room = BunkerGameRoom("PEEK", "h1", "Хост")
        room.add_player("p2", "Анна")
        room.add_player("p3", "Борис")
        room.start_game(capacity=2)
        
        # silence_player
        room.players["h1"].cards["special"] = {"card_id": "silence_player", "title": "Обет молчания", "used": False}
        room.use_special_card("h1", target_player_id="p2")
        self.assertTrue(room.players["p2"].is_silenced)

        # secret_peek
        room.players["h1"].cards["special"] = {"card_id": "secret_peek", "title": "Тайный шпионаж", "used": False}
        room.use_special_card("h1", target_player_id="p2")
        self.assertIsNotNone(room.players["h1"].last_peeked)

        # announce_peeked
        room.announce_peeked("h1")
        self.assertIsNone(room.players["h1"].last_peeked)

    def test_last_word_flow(self):
        """Проверка фазы «Последнее слово» после изгнания"""
        room = BunkerGameRoom("LSTW", "h1", "Хост")
        room.add_player("p2", "Анна")
        room.add_player("p3", "Борис")
        room.add_player("p4", "Виктор")
        room.start_game(capacity=2)
        
        room.phase = PHASE_VOTE_RESULTS
        room.vote_results = {"eliminated_id": "p4"}
        room.confirm_elimination()
        
        self.assertEqual(room.phase, PHASE_LAST_WORD)
        self.assertEqual(room.eliminated_in_last_word_id, "p4")
        self.assertEqual(room.timer_seconds_left, 15)
        self.assertTrue(room.players["p4"].cards["profession"]["revealed"])
        
        # Завершение последнего слова -> переход ко 2-му раунду
        room.finish_last_word()
        self.assertEqual(room.phase, PHASE_SPEECH)
        self.assertEqual(room.round_number, 2)

    def test_exile_vendetta(self):
        """Проверка механики «Вендетта изгнанных»"""
        room = BunkerGameRoom("VNDT", "h1", "Хост")
        room.add_player("p2", "Анна")
        room.add_player("p3", "Борис")
        room.add_player("p4", "Виктор")
        room.start_game(capacity=2)
        
        # Изгоняем p4 (остаются h1, p2, p3 - игра продолжается во 2 раунде)
        room.phase = PHASE_VOTE_RESULTS
        room.vote_results = {"eliminated_id": "p4"}
        room.confirm_elimination()
        room.finish_last_word()
        self.assertEqual(room.phase, PHASE_SPEECH)
        
        # Настраиваем p4 так, чтобы он гарантированно выжил на поверхности (скафандр / бункерный костюм)
        room.players["p4"].cards["baggage"] = {"value": "Полный костюм РХБЗ защиты высшего класса"}
        room.players["p4"].cards["profession"] = {"value": "Служебный кинолог с обученной собакой"}
        
        init_delta = room.events_score_delta
        room.trigger_exile_vendetta("p4")
        self.assertTrue(room.exile_vendetta_used)
        self.assertEqual(room.events_score_delta, init_delta - 5)

    def test_quick_meteorite_mode(self):
        """Проверка быстрого режима «Метеорит»"""
        room = BunkerGameRoom("MTRT", "h1", "Хост")
        room.add_player("p2", "Анна")
        room.add_player("p3", "Борис")
        room.start_game(capacity=2, game_mode="METEORITE", speech_duration=30, debate_duration=45)
        
        self.assertEqual(room.game_mode, "METEORITE")
        self.assertEqual(room.speech_duration_sec, 30)
        self.assertEqual(room.debate_duration_sec, 45)
        
        # Профессия и здоровье вскрыты сразу
        for p in room.players.values():
            self.assertTrue(p.cards["profession"]["revealed"])
            self.assertTrue(p.cards["health"]["revealed"])

if __name__ == "__main__":
    unittest.main()
