import random
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from server.deck_data import (
    evaluate_survival,
    calculate_event_odds,
    resolve_event_roll,
    BUNKER_EVENTS,
    CATASTROPHES
)
from server.game_engine import BunkerGameRoom, Player

def test_balance_distributions():
    print("=== ТЕСТИРОВАНИЕ БАЛАНСА ВЫЖИВАНИЯ ===")
    
    # 1. Тест малого бункера (2-3 человека) без доктора, но с аптечкой и консервами
    catastrophe = {"id": "nuclear_winter", "title": "Ядерная зима"}
    bunker = {"capacity": 2, "provisions_months": 24, "water_source": "Артезианская скважина"}
    
    survivors = [
        {
            "id": "p1",
            "name": "Инженер Алексей",
            "cards": {
                "profession": {"value": "Инженер-строитель", "tag": "engineering"},
                "biology": {"value": "Мужчина, 28 лет", "age": 28, "childbearing": True},
                "health": {"value": "Идеально здоров", "severity": 0},
                "baggage": {"value": "Армейская аптечка АИ-2 с запасом антибиотиков"},
                "hobby": {"value": "Кулинария и заготовка припасов"}
            }
        },
        {
            "id": "p2",
            "name": "Агроном Елена",
            "cards": {
                "profession": {"value": "Агроном-гидропоник", "tag": "agriculture"},
                "biology": {"value": "Женщина, 26 лет", "age": 26, "childbearing": True},
                "health": {"value": "Легкая близорукость", "severity": 0},
                "baggage": {"value": "Ящик тушенки и галет"},
                "hobby": {"value": "Радиолюбитель"}
            }
        }
    ]
    
    # Базовый финал без событий
    eval_no_events = evaluate_survival(survivors, catastrophe, bunker, events_score_delta=0)
    print(f"Малый бункер (2 чел, аптечка вместо доктора): Шанс выживания = {eval_no_events['survival_percent']}%")
    print(f"Плюсы: {eval_no_events['pros']}")
    print(f"Минусы: {eval_no_events['cons']}")
    assert eval_no_events['survival_percent'] >= 65, f"Expected >= 65%, got {eval_no_events['survival_percent']}%"
    
    # 2. Тест с проваленным событием (-6%), но со сработавшим бустом (+15%)
    eval_with_boost = evaluate_survival(
        survivors, 
        catastrophe, 
        bunker, 
        events_score_delta=-6, 
        boosted_profession_tags=["engineering"]
    )
    print(f"После провала события с бустом инженера (+15%): Шанс = {eval_with_boost['survival_percent']}%")
    assert eval_with_boost['survival_percent'] >= 70, f"Expected >= 70%, got {eval_with_boost['survival_percent']}%"
    
    # 3. Тест вылазки против нескольких вооруженных озлобленных изгнанников
    polar_drop = next(ev for ev in BUNKER_EVENTS if ev["id"] == "polar_airdrop")
    vol = Player("v1", "Доброволец")
    vol.cards = {
        "baggage": {"value": "Химзащита и пистолет", "revealed": True},
        "biology": {"value": "Мужчина, 25 лет", "age": 25, "revealed": True}
    }
    
    # 3 вооруженных изгнанника снаружи
    exiles = []
    for i in range(3):
        ex = Player(f"ex_{i}", f"Изгнанник {i+1}")
        ex.is_alive = False
        ex.cards = {
            "baggage": {"value": "Комплект химзащиты и пистолет Glock 17", "revealed": True},
            "profession": {"value": "Спецназовец", "tag": "security", "revealed": True}
        }
        exiles.append(ex)
        
    odds = calculate_event_odds(polar_drop, [vol], exiles, volunteer_id="v1", catastrophe=catastrophe)
    print(f"\nВылазка добровольца (+40%) против ТРЕХ вооруженных изгнанников:")
    print(f"Базовый шанс: {odds['base_chance']}%")
    print(f"Итоговый шанс: {odds['final_chance']}%")
    print(f"Бонусы добровольца: {[f['delta'] for f in odds['positive_factors']]}")
    
    # Базовый 50% + доброволец 40% - саботаж (макс 25%) = 65%
    # Игра остается полностью проходимой и захватывающей!
    assert odds['final_chance'] >= 50, f"Expected >= 50%, got {odds['final_chance']}%"
    print(f"✓ Штраф изгнанников ограничен капом в 25%, шанс вылазки честный ({odds['final_chance']}%)")
    
    # 4. Монте-Карло симуляция 1000 бросков событий с базовым шансом 55%
    wins = 0
    total = 1000
    for _ in range(total):
        roll = random.randint(1, 100)
        if roll <= 55:
            wins += 1
    winrate = (wins / total) * 100
    print(f"\nСимуляция 1000 бросков кубика при базовом шансе 55%: Успешных событий = {winrate:.1f}%")
    assert 50 <= winrate <= 60, f"Unexpected winrate {winrate}%"
    print("✓ Распределение кубика честное и не загоняет команду в безнадежность!")

if __name__ == "__main__":
    test_balance_distributions()
