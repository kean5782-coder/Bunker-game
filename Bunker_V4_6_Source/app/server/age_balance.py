"""Age/care rules for fictional bunker characters, not medical probabilities.

The input age is structured card data, never guessed from diagnoses, a name,
profession, sex or fertility. A single bounded score cost is charged in the
final. Skills and event odds are not scaled down a second time.
"""
from __future__ import annotations

import math
import re
from typing import Callable

# Compatibility only for old cards that have no structured age field.
_LEGACY_AGE = re.compile(r'(?<![\d.,])(\d{1,3})\s*(?:лет|года?|год)\b', re.I)


def read_age(card: dict | None) -> int | None:
    """Accept a finite integer 0..120; missing/invalid data is not an old age."""
    if not isinstance(card, dict) or card.get('destroyed'):
        return None
    if 'age' in card:
        value = card['age']
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        try:
            number = float(value)
        except (ValueError, TypeError, OverflowError):
            return None
        if not math.isfinite(number) or not number.is_integer() or not 0 <= number <= 120:
            return None
        return int(number)
    match = _LEGACY_AGE.search(str(card.get('value', '')))
    return int(match[1]) if match and 0 <= int(match[1]) <= 120 else None


def age_from_cards(cards: dict) -> int | None:
    """Current gender card first, legacy biology second; never charge both."""
    for category in ('gender', 'biology'):
        age = read_age(cards.get(category))
        if age is not None:
            return age
    return None


def base_care_load(age: int | None, rules: dict) -> float:
    """Piecewise linear designer curve, independent of sex or fertility."""
    if age is None:
        return 0.0
    knots = rules['age_knots']
    if age <= knots[0][0]:
        return float(knots[0][1])
    for (lo, left), (hi, right) in zip(knots, knots[1:]):
        if age <= hi:
            return left + (right - left) * (age - lo) / (hi - lo)
    return float(knots[-1][1])


def age_mechanics_text(card: dict, rules: dict) -> str:
    age = read_age(card)
    value = base_care_load(age, rules)
    prefix = ('Возраст не указан: возрастной штраф не начисляется.' if age is None else
              f'Возраст {age} лет: базовая нагрузка ухода {value:g} усл. ед. до компенсаций.')
    return (prefix + f' До {rules["age_knots"][0][0]} лет включительно возрастной нагрузки нет; '
            'далее она растёт плавно. Хорошее здоровье и выносливость уменьшают нагрузку; '
            'медицина, оснащение и организация команды снижают её в финале. '
            f'Общий штраф команды — не более {rules["final_penalty_cap"]:g} баллов рейтинга. '
            'Знания и профессия сохраняют силу; шанс испытаний возраст не меняет. '
            'Пол, ориентация и фертильность не дают штрафа. Это игровая условность, не медицинский прогноз.')


def calculate_age_care(people: list, needs: dict, duration: float,
                       effects: Callable[[dict, str], dict], rules: dict) -> dict:
    """Return an auditable, deterministic final-only aggregate and per-person rows.

    Good/minor health and the *body card's* explicit endurance trait grant a
    discount. Other health severities do not multiply age costs (illness has a
    separate existing cost). Only medicine and organization coverage mitigate
    care; they already include facilities and useful, non-destroyed equipment.
    """
    n = len(people)
    multiplier = min(rules['duration_multiplier_cap'],
                     1 + max(0, duration - rules['duration_baseline_years']) * rules['duration_rate'])
    divisor = max(1, n) ** rules['team_size_exponent']
    medical = min(1.0, max(0.0, float(needs['medicine']['coverage'])))
    social = min(1.0, max(0.0, float(needs['social']['coverage'])))
    reduction = min(rules['support_reduction_cap'],
                    rules['medicine_relief'] * medical + rules['social_relief'] * social)
    rows = []
    for pid, name, cards, _ in people:
        age = age_from_cards(cards)
        base = base_care_load(age, rules)
        severity = (cards.get('health') or {}).get('severity')
        # Missing/hidden health is unknown, not automatically 'perfect health'.
        health_factor = rules['health_factors'].get(severity, 1.0)
        body = effects(cards.get('body') or {}, 'body')
        fit = bool(set(body.get('traits', [])).intersection(rules['fitness_traits']))
        fit_factor = rules['fitness_factor'] if fit else 1.0
        personal = base * health_factor * fit_factor * multiplier
        rows.append({'player_id': pid, 'player_name': name, 'age': age,
                     'base_load': round(base, 4), 'health_factor': health_factor,
                     'fitness_factor': fit_factor, 'duration_multiplier': round(multiplier, 4),
                     'care_load': round(personal, 6), 'penalty': 0.0})
    total = sum(row['care_load'] for row in rows)
    before = total / divisor
    uncapped = before * (1 - reduction)
    penalty = round(min(rules['final_penalty_cap'], uncapped), 2)
    # Largest remainder rounding keeps the displayed personal sum exact.
    if total > 0:
        exact_cents = [row['care_load'] / total * round(penalty * 100) for row in rows]
        cents = [math.floor(v) for v in exact_cents]
        remaining = round(penalty * 100) - sum(cents)
        order = sorted(range(n), key=lambda i: exact_cents[i] - cents[i], reverse=True)
        for i in order[:remaining]:
            cents[i] += 1
        for row, value in zip(rows, cents):
            row['penalty'] = value / 100
    return {'model': 'age_care_v1', 'penalty': penalty, 'max_penalty': rules['final_penalty_cap'],
            'known_age_count': sum(row['age'] is not None for row in rows),
            'unknown_age_count': sum(row['age'] is None for row in rows),
            'affected_count': sum(row['base_load'] > 0 for row in rows),
            'population': n, 'base_load_total': round(sum(row['base_load'] for row in rows), 4),
            'adjusted_load_total': round(total, 4), 'team_divisor': round(divisor, 6),
            'duration_multiplier': round(multiplier, 4), 'medical_coverage': medical,
            'social_coverage': social, 'support_reduction_pct': round(100 * reduction, 3),
            'before_support': round(before, 4), 'support_saved': round(before - uncapped, 4),
            'uncapped_penalty': round(uncapped, 4), 'cap_applied': uncapped > rules['final_penalty_cap'],
            'applies_to': 'final_rating_only', 'rows': rows}
