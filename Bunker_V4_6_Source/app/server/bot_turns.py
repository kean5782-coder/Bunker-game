"""State-driven reveal/speech actions shared by both bundled bot runners."""
from __future__ import annotations


def plan_turn(state: dict, player_id: str, priority: list[str]) -> dict | None:
    """Never reveal in SPEECH. The server's quota and turn token are authoritative."""
    if state.get('result_review'):
        return None
    phase = state.get('phase')
    current = state.get('current_speaker') or {}
    player = next((p for p in state.get('players', []) if p['id'] == player_id), None)
    if (phase not in ('REVEAL', 'SPEECH') or current.get('id') != player_id
            or not player or not player.get('is_alive') or player.get('is_quarantined')):
        return None
    payload = {'expected_turn_id': state['turn_id']} if 'turn_id' in state else {}
    if phase == 'SPEECH':
        return {'action': 'NEXT_SPEAKER', 'payload': payload}
    status = state.get('reveal_status') or {}
    if status.get('can_proceed'):
        return {'action': 'NEXT_REVEAL', 'payload': payload}
    cards = player.get('cards', {})
    hidden = [cat for cat in priority if cat not in ('special', 'traitor')
              and cat in cards and not cards[cat].get('revealed')]
    if state.get('round_number') == 1 and 'profession' in hidden:
        category = 'profession'
    else:
        category = next(iter(hidden), None)
    if category is None:
        return None
    return {'action': 'REVEAL_CARD', 'payload': {**payload, 'category': category}}
