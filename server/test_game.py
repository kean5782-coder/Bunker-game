"""
Автоматический тест логики игры «Бункер» и API.
"""

import sys
import os
import asyncio

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


from server.game_engine import BunkerGameRoom, PHASE_LOBBY, PHASE_SPEECH, PHASE_DEBATE, PHASE_VOTING, PHASE_VOTE_RESULTS, PHASE_LAST_WORD, PHASE_FINAL
from server.network_utils import get_local_ip, get_external_ip, generate_qr_data_url

def test_network():
    print("-> Тестирование сетевых утилит...")
    local_ip = get_local_ip()
    ext_ip = get_external_ip()
    print(f"   Локальный IP: {local_ip}, Внешний IP: {ext_ip}")
    assert local_ip, "Local IP must not be empty"
    
    qr = generate_qr_data_url(f"http://{local_ip}:64738")

    assert qr.startswith("data:image/png;base64,"), "QR Code generation failed"
    print("   ✓ Сетевые утилиты и QR-код работают успешно.")

def test_game_flow():
    print("-> Тестирование игрового цикла и прав ведущего...")
    room = BunkerGameRoom("ABCD", "host_1", "Командир")
    room.add_player("p_2", "Анна")
    room.add_player("p_3", "Борис")
    room.add_player("p_4", "Виктор")
    
    # Запуск игры на 2 выживших
    room.start_game(capacity=2)
    assert room.phase == PHASE_SPEECH
    assert room.bunker_capacity == 2
    assert len(room.players) == 4
    print(f"   Катастрофа: {room.catastrophe['title']}, Мест: {room.bunker_capacity}")

    # 1. Первый оратор вскрывает профессию
    sp = room.get_current_speaker()
    room.reveal_player_card(sp.id, "profession")
    assert sp.cards["profession"]["revealed"] == True
    print(f"   Игрок {sp.name} вскрыл профессию: {sp.cards['profession']['value']}")

    # 2. Проверка хост-функций таймера
    init_time = room.timer_seconds_left
    room.host_pause_timer(True)
    assert room.timer_is_paused == True
    room.host_add_time(30)
    assert room.timer_seconds_left == init_time + 30
    room.host_pause_timer(False)

    # Тест передачи слова хостом во время речи
    room.host_grant_speech_speaker("p_2")
    assert room.get_current_speaker().id == "p_2"
    assert room.timer_is_paused == False
    print("   ✓ Хост-контроль таймера (пауза, добавление секунд) работает.")

    # 3. Принудительное переключение на дебаты
    room.host_set_phase(PHASE_DEBATE)
    assert room.phase == PHASE_DEBATE
    print("   ✓ Хост переключил фазу на DEBATE.")

    # 4. Перезапуск раунда дебатов
    room.host_restart_phase()
    assert room.phase == PHASE_DEBATE
    assert room.timer_seconds_left == room.debate_duration_sec
    print("   ✓ Хост перезапустил дебаты.")

    # 5. Ведущий дает слово конкретному игроку
    room.host_grant_debate_speaker("p_3")
    assert room.get_current_debate_speaker().id == "p_3"

    # 6. Переход к голосованию
    room.host_set_phase(PHASE_VOTING)
    assert room.phase == PHASE_VOTING

    # 7. Игроки голосуют: все против Виктора (p_4)
    room.cast_vote("host_1", "p_4")
    room.cast_vote("p_2", "p_4")
    room.cast_vote("p_3", "p_4")
    room.cast_vote("p_4", "p_2")
    
    # Голоса подсчитаны
    assert room.phase == PHASE_VOTE_RESULTS
    assert room.vote_results["eliminated_id"] == "p_4"
    print(f"   ✓ Голосование прошло, кандидат на выбывание: {room.vote_results['eliminated_name']}")

    # 10. Подтверждение изгнания игрока p_4 -> переход к последнему слову
    room.confirm_elimination()
    assert room.players["p_4"].is_alive == False
    assert room.phase == PHASE_LAST_WORD
    assert room.eliminated_in_last_word_id == "p_4"
    print(f"   ✓ Игрок Виктор изгнан, активировано Последнее слово.")

    # Завершение последнего слова
    room.finish_last_word()

    # 11. Следующий раунд: осталось 3 живых, а вместимость 2
    assert len(room.get_alive_players()) == 3
    assert room.round_number == 2

    # 12. Изгоняем еще одного игрока
    room.phase = PHASE_VOTE_RESULTS
    room.vote_results = {"eliminated_id": "p_3"}
    room.confirm_elimination("p_3")
    assert room.players["p_3"].is_alive == False
    assert room.phase == PHASE_LAST_WORD
    room.finish_last_word()

    # 13. Теперь осталось 2 выживших == вместимость бункера (2) -> ФИНАЛ!
    assert room.phase == PHASE_FINAL
    assert room.final_evaluation is not None
    print(f"   ✓ Финал активирован: шанс выживания {room.final_evaluation['survival_percent']}%. Эпилог: {room.final_evaluation['title']}")

def test_traitor_mode():
    print("-> Тестирование режима Предателя (Диверсионная миссия)...")
    room = BunkerGameRoom("TRTR", "host_tr", "Капитан")
    room.add_player("p_2", "Алиса")
    room.add_player("p_3", "Борис")
    room.start_game(capacity=2, enable_traitor=True)
    assert room.enable_traitor == True

    # Ровно один игрок должен иметь карту предателя
    traitor_players = [p for p in room.players.values() if "traitor" in p.cards]
    assert len(traitor_players) == 1, "Должен быть ровно 1 предатель"
    traitor = traitor_players[0]
    print(f"   ✓ Тайный предатель назначен: {traitor.name}, миссия: {traitor.cards['traitor']['value']}")

    # Проверка скрытия: для другого игрока карта 'traitor' вообще не передается в словаре
    other_player = [p for p in room.players.values() if p.id != traitor.id][0]
    state_for_other = room.get_state(for_player_id=other_player.id)
    traitor_in_other_view = [p for p in state_for_other["players"] if p["id"] == traitor.id][0]
    assert "traitor" not in traitor_in_other_view["cards"], "Карта предателя не должна быть видна другим игрокам!"

    # Для самого предателя карта видна
    state_for_traitor = room.get_state(for_player_id=traitor.id)
    traitor_self_view = [p for p in state_for_traitor["players"] if p["id"] == traitor.id][0]
    assert "traitor" in traitor_self_view["cards"], "Предатель должен видеть свою секретную роль в досье"
    print("   ✓ Секретность роли предателя проверена и работает идеально.")

def test_tiebreaker():
    print("-> Тестирование механики тайбрейка при равенстве голосов...")
    room = BunkerGameRoom("TIEB", "h1", "Хост")
    room.add_player("p2", "Игрок 2")
    room.add_player("p3", "Игрок 3")
    room.add_player("p4", "Игрок 4")
    room.start_game(capacity=2)

    room.start_voting()
    # 2 голоса против p2, 2 голоса против p3 -> ничья переводит в оправдание
    room.cast_vote("h1", "p2")
    room.cast_vote("p3", "p2")
    room.cast_vote("p2", "p3")
    room.cast_vote("p4", "p3")

    assert room.phase == "JUSTIFICATION"
    assert set(room.justification_candidates) == {"p2", "p3"}
    print(f"   ✓ Зафиксирована ничья и оправдательная речь для: {room.justification_candidates}")

    # Переход к переголосованию
    for _ in range(len(room.justification_candidates)):
        room.next_justification_speaker()
    assert room.phase == "REVOTE"
    print("   ✓ Переголосование успешно активировано.")

def test_events_flow():
    print("-> Тестирование системы событий и вылазок...")
    room = BunkerGameRoom("EVNT", "h1", "Хост")
    room.add_player("p2", "Алиса")
    room.add_player("p3", "Борис")
    room.add_player("p4", "Виктор")
    room.start_game(capacity=2, enable_events=True)
    assert room.events_enabled == True

    # Эмуляция изгнания игрока -> автоматический запуск события
    room.phase = PHASE_VOTE_RESULTS
    room.vote_results = {
        "eliminated_id": "p4",
        "eliminated_name": "Виктор",
        "is_tie": False
    }
    room.confirm_elimination()
    assert room.phase == PHASE_LAST_WORD
    room.finish_last_word()
    
    # После изгнания и завершения последнего слова должно появиться активное событие
    assert room.active_event is not None
    assert room.current_event_odds is not None
    print(f"   ✓ Событие активировано: {room.active_event['title']} ({room.active_event['type']})")
    print(f"   ✓ Базовый шанс успеха: {room.current_event_odds['base_chance']}%, Итоговый: {room.current_event_odds['final_chance']}%")

    # Проверка назначения добровольца
    if room.active_event["type"] == "SURFACE_EVENT":
        room.assign_volunteer("p2")
        assert room.assigned_volunteer_id == "p2"
        print("   ✓ Доброволец на поверхность назначен: Алиса")

    # Проверка разрешения события броском d100
    res = room.resolve_active_event(force_roll=10) # Выигрышный бросок
    assert res["is_success"] == True
    assert len(room.resolved_events) == 1
    print(f"   ✓ Событие успешно решено! Дельта очков бункера: {room.events_score_delta}%")

def test_prologue_and_enter_bunker():
    print("-> Тестирование фазы пролога и входа в бункер...")
    from server.game_engine import PHASE_PROLOGUE
    room = BunkerGameRoom("TEST", "host_1", "Командир")
    room.add_player("p_2", "Анна")
    room.add_player("p_3", "Борис")

    # 1. Запуск с прологом
    room.start_game(capacity=2, skip_prologue=False)
    assert room.phase == PHASE_PROLOGUE
    assert room.timer_is_paused == True
    init_time = room.timer_seconds_left

    # 2. Таймер не должен тикать во время пролога
    assert room.tick_timer() == False
    assert room.timer_seconds_left == init_time

    # 3. Обычный игрок жмет "В бункер" -> пока ведущий не нажал, игра не стартует
    room.enter_bunker("p_2")
    assert room.phase == PHASE_PROLOGUE

    # 4. Ведущий жмет "В бункер" -> переход в фазу речи
    room.enter_bunker("host_1")
    assert room.phase == PHASE_SPEECH
    assert room.timer_is_paused == False
    assert room.timer_seconds_left == room.speech_duration_sec

    # 5. Теперь в фазе речи таймер отсчитывает время
    room.tick_timer()
    assert room.timer_seconds_left == room.speech_duration_sec - 1
    print("   ✓ Пролог и кнопка «В бункер» работают корректно.")

if __name__ == "__main__":
    test_network()
    test_game_flow()
    test_traitor_mode()
    test_tiebreaker()
    test_events_flow()
    test_prologue_and_enter_bunker()
    print("\n✅ ВСЕ ТЕСТЫ УСПЕШНО ПРОЙДЕНЫ!")

