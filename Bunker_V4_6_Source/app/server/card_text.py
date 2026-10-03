"""Shared wording for dealt cards and replacements."""


def gender_age_title(gender: str, age: int) -> str:
    if 11 <= age % 100 <= 14:
        unit = 'лет'
    elif age % 10 == 1:
        unit = 'год'
    elif 2 <= age % 10 <= 4:
        unit = 'года'
    else:
        unit = 'лет'
    return f'{gender}, {age} {unit}'


def profession_title(name: str, experience: str) -> str:
    # Experience is deliberately independent of age in the party deck.
    return f'{name} (по собственным словам: {experience})'


TREATED_HEALTH = {
    'medium': (
        'Идёт на поправку',
        'После лечения стало лучше. Проблемы со здоровьем ещё остаются; нужны уход и отдых.',
    ),
    'minor': (
        'Небольшое недомогание после лечения',
        'После лечения самочувствие заметно лучше. Небольшие ограничения пока остаются.',
    ),
    'good': (
        'Хорошее самочувствие после лечения',
        'Лечение помогло. Прежние ограничения по здоровью больше не действуют.',
    ),
}
