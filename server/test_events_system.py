import unittest
from server.deck_data import (
    draw_random_event,
    calculate_event_odds,
    resolve_event_roll,
    is_exile_alive_on_surface,
    evaluate_survival,
    BUNKER_EVENTS,
    CATASTROPHES
)
from server.game_engine import BunkerGameRoom, Player

class TestEventsSystem(unittest.TestCase):
    def test_catastrophe_compatibility(self):
        """События не должны противоречить катаклизму"""
        flood_cat = next(c for c in CATASTROPHES if c["id"] == "global_flood")
        for _ in range(50):
            ev = draw_random_event(flood_cat["id"])
            compat = ev.get("compatible_catastrophes", [])
            self.assertTrue("ALL" in compat or "global_flood" in compat)
            # Не должно быть мороза при потопе
            self.assertNotIn(ev["id"], ["frozen_air_intake", "polar_airdrop"])

        ice_cat = next(c for c in CATASTROPHES if c["id"] == "ice_age")
        for _ in range(50):
            ev = draw_random_event(ice_cat["id"])
            compat = ev.get("compatible_catastrophes", [])
            self.assertTrue("ALL" in compat or "ice_age" in compat)
            # Не должно быть потопа при ледниковом периоде
            self.assertNotIn(ev["id"], ["hatch_pressure_breach", "drifting_lifeboat"])

    def test_exile_lethality(self):
        """В экстремальных катаклизмах изгнанник без снаряжения гибнет, со снаряжением - выживает"""
        ice_cat = {"id": "ice_age", "title": "Ледниковый период"}
        zombie_cat = {"id": "zombie_outbreak", "title": "Зомби-пандемия"}

        # Игрок 1: без защитной одежды
        p_unprotected = {
            "id": "p1",
            "name": "Иван",
            "is_alive": False,
            "cards": {
                "baggage": {"value": "Акустическая гитара", "desc": "Гитара", "revealed": True}
            }
        }
        status1 = is_exile_alive_on_surface(p_unprotected, ice_cat)
        self.assertFalse(status1["is_alive_surface"])
        self.assertIn("Замерз насмерть", status1["reason"])

        # Игрок 2: в костюме химзащиты
        p_protected = {
            "id": "p2",
            "name": "Сергей",
            "is_alive": False,
            "cards": {
                "baggage": {"value": "Комплект химзащиты с панорамной маской", "desc": "Комплект", "revealed": True}
            }
        }
        status2 = is_exile_alive_on_surface(p_protected, ice_cat)
        self.assertTrue(status2["is_alive_surface"])
        self.assertIn("Выжил", status2["reason"])

        # В обычной среде (zombie_outbreak) выживают оба
        status3 = is_exile_alive_on_surface(p_unprotected, zombie_cat)
        self.assertTrue(status3["is_alive_surface"])

    def test_only_revealed_attributes_count(self):
        """Учитываются ТОЛЬКО ОТКРЫТЫЕ характеристики"""
        rat_event = next(ev for ev in BUNKER_EVENTS if ev["id"] == "rat_infestation")

        p = Player("p1", "Михаил")
        p.cards = {
            "baggage": {"value": "Пистолет Glock 17", "desc": "Пистолет", "revealed": False},
            "health": {"value": "Бронхиальная астма", "desc": "Астма", "revealed": False},
            "profession": {"value": "Инженер", "tag": "engineering", "revealed": False},
            "biology": {"value": "Мужчина, 25 лет", "age": 25, "revealed": False}
        }

        odds_unrevealed = calculate_event_odds(rat_event, [p], [])
        self.assertEqual(odds_unrevealed["final_chance"], odds_unrevealed["base_chance"])
        self.assertEqual(len(odds_unrevealed["positive_factors"]), 0)
        self.assertEqual(len(odds_unrevealed["negative_factors"]), 0)

        # Игрок открывает пистолет
        p.cards["baggage"]["revealed"] = True
        odds_with_weapon = calculate_event_odds(rat_event, [p], [])
        self.assertGreater(odds_with_weapon["final_chance"], odds_unrevealed["base_chance"])
        self.assertTrue(any("Оружие" in f["title"] for f in odds_with_weapon["positive_factors"]))

        # Игрок открывает астму -> шанс падает
        p.cards["health"]["revealed"] = True
        odds_with_asthma = calculate_event_odds(rat_event, [p], [])
        self.assertLess(odds_with_asthma["final_chance"], odds_with_weapon["final_chance"])
        self.assertTrue(any("ограничение" in f["title"] for f in odds_with_asthma["negative_factors"]))

    def test_surface_duel_hostile_exiles(self):
        """В событиях на поверхности вооруженные изгнанники саботируют вылазку"""
        airdrop = next(ev for ev in BUNKER_EVENTS if ev["id"] == "polar_airdrop")
        cat = {"id": "ice_age", "title": "Ледниковый период"}

        vol = Player("v1", "Доброволец")
        vol.cards = {
            "baggage": {"value": "Комплект химзащиты и пистолет Glock 17", "desc": "Защита", "revealed": True},
            "biology": {"value": "Мужчина, 24 года", "age": 24, "revealed": True}
        }

        # Изгнанник 1: погиб на морозе
        ex_dead = Player("ex1", "Погибший")
        ex_dead.is_alive = False
        ex_dead.cards = {
            "baggage": {"value": "Гитара", "revealed": True}
        }

        # Изгнанник 2: выжил на морозе в химзащите и имеет открытый пистолет Glock
        ex_hostile = Player("ex2", "Озлобленный боец")
        ex_hostile.is_alive = False
        ex_hostile.cards = {
            "baggage": {"value": "Комплект химзащиты и пистолет Glock 17", "desc": "Оружие", "revealed": True},
            "profession": {"value": "Офицер спецназа", "tag": "security", "revealed": True}
        }

        odds_duel = calculate_event_odds(airdrop, [vol], [ex_dead, ex_hostile], volunteer_id=vol.id, catastrophe=cat)
        
        # Изгнанник 1 должен иметь 0% угрозы (погиб)
        ex1_data = next(e for e in odds_duel["exiles"] if e["id"] == "ex1")
        self.assertFalse(ex1_data["is_alive_surface"])
        self.assertEqual(ex1_data["factors"][0]["delta"], 0)

        # Изгнанник 2 должен иметь серьезный штраф (засада)
        ex2_data = next(e for e in odds_duel["exiles"] if e["id"] == "ex2")
        self.assertTrue(ex2_data["is_alive_surface"])
        self.assertTrue(any("Вооруженная засада" in f["title"] for f in ex2_data["factors"]))
        self.assertTrue(any("Военный опыт" in f["title"] for f in ex2_data["factors"]))

    def test_game_room_event_resolution_and_boost(self):
        """Тест полного цикла комнаты: вытягивание, d100, буст профессий и влияние на финал"""
        room = BunkerGameRoom("TEST1", "host_1", "Ведущий")
        p1 = room.add_player("p1", "Игрок 1")
        p2 = room.add_player("p2", "Игрок 2")
        p3 = room.add_player("p3", "Игрок 3")
        room.start_game(capacity=2)

        # Принудительно задаем событие с бустом профессий (rat_infestation)
        rat_event = next(ev for ev in BUNKER_EVENTS if ev["id"] == "rat_infestation")
        room.active_event = rat_event
        room.recalculate_event_odds()

        # Симулируем провальный бросок (кубик 99 > шанса)
        res = room.resolve_active_event(force_roll=99)
        self.assertFalse(res["is_success"])
        self.assertLess(room.events_score_delta, 0)
        self.assertIn("medicine", room.boosted_profession_tags)
        self.assertIn("engineering", room.boosted_profession_tags)

        # Проверяем, что в финале выжившие с профессией инженер получают спасительный буст
        p1.cards["profession"] = {"value": "Инженер-электрик", "tag": "engineering"}
        eval_res = evaluate_survival(
            [p1.to_dict(show_all_secret=True)],
            room.catastrophe,
            room.bunker,
            events_score_delta=room.events_score_delta,
            boosted_profession_tags=room.boosted_profession_tags
        )
        self.assertTrue(any("Жизненная необходимость" in p for p in eval_res["pros"]))

    def test_round1_event_active_in_standard_mode(self):
        """В 1-м раунде стандартного режима игры событие должно быть активно сразу"""
        room = BunkerGameRoom("TEST_R1", "host_1", "Host")
        room.add_player("p1", "Игрок 1")
        room.add_player("p2", "Игрок 2")
        room.add_player("p3", "Игрок 3")
        room.start_game(capacity=2, enable_events=True)
        self.assertTrue(room.events_enabled)
        self.assertIsNotNone(room.active_event)
        self.assertIsNotNone(room.current_event_odds)

    def test_skip_sortie_mechanism(self):
        """Пропуск вылазки ведущим: 0% дельта, статус is_skipped, здоровье не ухудшается"""
        room = BunkerGameRoom("TEST_SKIP", "host_1", "Host")
        p1 = room.add_player("p1", "Игрок 1")
        p2 = room.add_player("p2", "Игрок 2")
        room.start_game(capacity=1, enable_events=True)

        surface_ev = {
            "id": "test_surf",
            "type": "SURFACE_EVENT",
            "title": "Вылазка за припасами",
            "description": "Тестовая вылазка",
            "base_chance": 40,
            "rules": {"positive": [], "negative": []},
            "on_success": {"score_delta": 10, "title": "Успех", "description": "Найдено"},
            "on_failure": {"score_delta": -10, "title": "Провал", "description": "Потеря"}
        }
        room.active_event = surface_ev
        room.assigned_volunteer_id = "p1"
        room.recalculate_event_odds()

        # Ведущий пропускает вылазку
        room.skip_sortie(True)
        self.assertTrue(room.is_sortie_skipped)

        res = room.resolve_active_event()
        self.assertTrue(res["is_skipped"])
        self.assertEqual(res["score_delta"], 0)
        self.assertEqual(room.events_score_delta, 0)
        self.assertIsNone(res["health_degraded"])
        self.assertIsNone(room.active_event)

    def test_surface_sortie_health_degradation_healthy_to_minor(self):
        """Здоровый доброволец при провальной вылазке в экстремальный катаклизм получает легкую болезнь"""
        room = BunkerGameRoom("TEST_DEG1", "host_1", "Host")
        p1 = room.add_player("p1", "Игрок 1")
        p2 = room.add_player("p2", "Игрок 2")
        room.start_game(capacity=1, enable_events=True)

        room.catastrophe = {
            "id": "ice_age",
            "title": "Ледниковый период (-70°C)",
            "description": "Смертоносный мороз сковал планету"
        }

        p1.cards["health"] = {
            "value": "Абсолютно здоров",
            "details": "Отличный иммунитет",
            "severity": "good",
            "revealed": False
        }

        surface_ev = {
            "id": "test_freeze_surf",
            "type": "SURFACE_EVENT",
            "title": "Разведка ледника",
            "description": "Выход на ледяную поверхность",
            "base_chance": 10,
            "rules": {"positive": [], "negative": []},
            "on_success": {"score_delta": 10, "title": "Успех", "description": "Успешно"},
            "on_failure": {"score_delta": -10, "title": "Провал", "description": "Замерзли"}
        }
        room.active_event = surface_ev
        room.assigned_volunteer_id = "p1"
        room.recalculate_event_odds()

        import random
        # Фиксируем random, чтобы кубик вылазки провалился (force_roll=99) и кубик здоровья выпал 1 (урон)
        orig_randint = random.randint
        def mock_randint(a, b):
            if a == 1 and b == 100:
                return 1  # 1 <= danger_chance гарантирует ухудшение
            return orig_randint(a, b)

        random.randint = mock_randint
        try:
            res = room.resolve_active_event(force_roll=99)
        finally:
            random.randint = orig_randint

        self.assertIsNotNone(res["health_degraded"])
        self.assertEqual(res["health_degraded"]["player_id"], "p1")
        # Здоровый должен получить начальную стадию (minor), а не остаться 'good'
        self.assertEqual(p1.cards["health"]["severity"], "minor")
        # Карта здоровья не раскрывается автоматически, остается скрытой
        self.assertFalse(p1.cards["health"]["revealed"])
        self.assertIn("обморожение", p1.cards["health"]["value"].lower())

    def test_surface_sortie_health_degradation_minor_to_medium(self):
        """Доброволец с легким заболеванием (minor) при вылазке ухудшает состояние до medium втихую"""
        room = BunkerGameRoom("TEST_DEG2", "host_1", "Host")
        p1 = room.add_player("p1", "Игрок 1")
        room.add_player("p2", "Игрок 2")
        room.start_game(capacity=1, enable_events=True)

        room.catastrophe = {
            "id": "super_virus",
            "title": "Супер-вирус",
            "description": "Смертоносная биологическая пандемия"
        }

        p1.cards["health"] = {
            "value": "Хронический гастрит",
            "details": "Легкая форма",
            "severity": "minor",
            "revealed": False
        }

        surface_ev = {
            "id": "test_virus_surf",
            "type": "SURFACE_EVENT",
            "title": "Вылазка за вакциной",
            "description": "Поиск антидота",
            "base_chance": 10,
            "rules": {"positive": [], "negative": []},
            "on_success": {"score_delta": 10, "title": "Успех", "description": "Успешно"},
            "on_failure": {"score_delta": -10, "title": "Провал", "description": "Провал"}
        }
        room.active_event = surface_ev
        room.assigned_volunteer_id = "p1"
        room.recalculate_event_odds()

        import random
        orig_randint = random.randint
        def mock_randint(a, b):
            if a == 1 and b == 100:
                return 1
            return orig_randint(a, b)

        random.randint = mock_randint
        try:
            res = room.resolve_active_event(force_roll=99)
        finally:
            random.randint = orig_randint

        self.assertIsNotNone(res["health_degraded"])
        # minor должен обостриться до medium
        self.assertEqual(p1.cards["health"]["severity"], "medium")
        # Карта здоровья не раскрывается автоматически, остается скрытой
        self.assertFalse(p1.cards["health"]["revealed"])
        self.assertIn("Обострение", p1.cards["health"]["value"])


if __name__ == "__main__":
    unittest.main()

