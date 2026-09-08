import sys
import os
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "Бункер")))

from server.deck_data import evaluate_survival, CATASTROPHES, BUNKER_PRESETS

def test_boost_single_line():
    survivors = [
        {
            "id": "p1",
            "name": "Алексей (Бот)",
            "cards": {
                "profession": {"value": "Анестезиолог-реаниматолог", "tag": "medicine"},
                "biology": {"value": "Мужчина, 22 года", "reproduction": "Бесплоден"},
                "health": {"severity": "good"},
                "baggage": {"value": "Фонарик"},
                "hobby": {"value": "Чтение"},
                "fact": {"value": "Нет судимостей"}
            }
        },
        {
            "id": "p2",
            "name": "Дмитрий (Бот)",
            "cards": {
                "profession": {"value": "Эпидемиолог-инфекционист", "tag": "medicine"},
                "biology": {"value": "Мужчина, 35 лет", "reproduction": "Бесплоден"},
                "health": {"severity": "good"},
                "baggage": {"value": "Компас"},
                "hobby": {"value": "Бег"},
                "fact": {"value": "Знает английский"}
            }
        },
        {
            "id": "p3",
            "name": "Елена (Бот)",
            "cards": {
                "profession": {"value": "Травматолог-ортопед", "tag": "medicine"},
                "biology": {"value": "Женщина, 28 лет", "reproduction": "Бесплодна"},
                "health": {"severity": "good"},
                "baggage": {"value": "Веревка"},
                "hobby": {"value": "Шитье"},
                "fact": {"value": "Волонтер"}
            }
        }
    ]

    catastrophe = CATASTROPHES[0]
    bunker = BUNKER_PRESETS[0]

    res = evaluate_survival(
        survivors=survivors,
        catastrophe=catastrophe,
        bunker=bunker,
        boosted_profession_tags={"medicine": 8}
    )

    print("Survival Score:", res["survival_percent"])
    print("Pros List:")
    for pro in res["pros"]:
        print(" -", pro)

    # Verify that only ONE line is generated for the boosted need!
    fire_lines = [p for p in res["pros"] if "🔥 Жизненная необходимость" in p]
    print(f"\nNumber of 'Жизненная необходимость' lines: {len(fire_lines)}")
    assert len(fire_lines) == 1, f"Expected exactly 1 line, got {len(fire_lines)}!"
    assert "(+8%)" in fire_lines[0] or "(+7%)" in fire_lines[0], f"Expected +8%, got {fire_lines[0]}"
    print("PASS: Exactly 1 consolidated line generated with balanced bonus!")

if __name__ == "__main__":
    test_boost_single_line()
