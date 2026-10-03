"""Shared five-second result reviews, independent of the next gameplay timer.

The engine may already have prepared the next phase, but its timer and network
commands are held until the review ends. No browser timeout advances the game.
Only public ballot aggregates and viewer-safe event results are serialized.
"""
from __future__ import annotations

import copy
import uuid
import time

REVIEW_SECONDS = 5
REVIEW_ALLOWED_ACTIONS = frozenset({'PING', 'HOST_PAUSE_TIMER', 'CLAIM_HOST', 'JOIN_LOBBY'})


class ResultReviewMixin:
    def init_result_reviews(self):
        self.result_reviews: list[dict] = []
        self.last_vote_summary: dict | None = None
        self.vote_summary_history: list[dict] = []

    def require_review_finished(self, action: str):
        if self.result_reviews and action not in REVIEW_ALLOWED_ACTIONS:
            raise ValueError('Сейчас общий показ результата. Дождитесь окончания 5 секунд; время следующего этапа не расходуется.')

    def enqueue_review(self, kind: str, data: dict, *, after: str | None = None):
        review = {'id': uuid.uuid4().hex, 'kind': kind, 'data': copy.deepcopy(data),
                  'duration': REVIEW_SECONDS, 'seconds_left': REVIEW_SECONDS,
                  'is_paused': False, 'after': after, '_next_tick': time.monotonic() + 1}
        self.result_reviews.append(review)
        return review

    def tick_result_review(self) -> bool:
        if not self.result_reviews:
            return False
        review = self.result_reviews[0]
        if review['is_paused']:
            return True
        review['seconds_left'] = max(0, review['seconds_left'] - 1)
        review['_next_tick'] = time.monotonic() + 1
        if review['seconds_left'] == 0:
            self.result_reviews.pop(0)
            if self.result_reviews:
                self.result_reviews[0]['_next_tick'] = time.monotonic() + 1
            if review.get('after') == 'confirm_no_exile':
                # The caller has no veto candidate. Resolve the round only after
                # everybody has seen why nobody was expelled.
                self.confirm_elimination()
        return True

    def advance_review_clock(self, now: float | None = None) -> bool:
        """Real server cadence. Do not shorten five seconds to four by sharing
        the wall-clock phase of the room's regular one-second timer."""
        if not self.result_reviews:
            return False
        now = time.monotonic() if now is None else now
        review = self.result_reviews[0]
        if review['is_paused']:
            review['_next_tick'] = now + 1
            return False
        due = review['_next_tick']
        if now < due:
            return False
        self.tick_result_review()
        if self.result_reviews and self.result_reviews[0] is review:
            review['_next_tick'] = due + 1
        return True

    def current_ballot_tally(self) -> list:
        counts = {}
        total = self.ballot_counts()['total_weight']
        for player in self.get_alive_players():
            if player.is_quarantined:
                continue
            target = self.votes.get(player.id)
            if target in self.players and self.players[target].is_alive and not self.players[target].has_immunity:
                counts[target] = counts.get(target, 0) + (2 if player.double_vote else 1)
        return [{'player_id': pid, 'player_name': self.players[pid].name, 'votes': weight,
                 'percent': round(100 * weight / total, 1) if total else 0}
                for pid, weight in sorted(counts.items(), key=lambda item: item[1], reverse=True)]

    def ballot_counts(self) -> dict:
        voters = [p for p in self.get_alive_players() if not p.is_quarantined]
        result = {'total_weight': 0, 'abstain_weight': 0, 'skip_weight': 0,
                  'uncast_weight': 0, 'other_weight': 0, 'voters': len(voters)}
        for player in voters:
            weight = 2 if player.double_vote else 1
            result['total_weight'] += weight
            target = self.votes.get(player.id)
            if target is None:
                result['uncast_weight'] += weight
            elif target == 'ABSTAIN':
                result['abstain_weight'] += weight
            elif target == 'SKIP_ROUND':
                result['skip_weight'] += weight
            elif target not in self.players or not self.players[target].is_alive or self.players[target].has_immunity:
                result['other_weight'] += weight
        return result

    def present_vote_summary(self, result: dict, *, decision: str | None = None,
                             source: str = 'VOTING', after: str | None = None):
        data = copy.deepcopy(result)
        data.update(round_number=self.round_number, source=source, counts=self.ballot_counts())
        if decision is None:
            decision = ('veto' if data.get('veto_used') else 'skip' if data.get('skipped_round')
                        else 'none' if not data.get('eliminated_ids') else 'provisional')
        counted = sum(row.get('votes', 0) for row in data.get('detailed_tally', []))
        c = data['counts']
        c['other_weight'] = max(0, c['total_weight'] - counted - c['abstain_weight'] - c['skip_weight'] - c['uncast_weight'])
        data['decision'] = decision
        data['summary_id'] = uuid.uuid4().hex
        self.last_vote_summary = data
        self.vote_summary_history.append(copy.deepcopy(data))
        self.vote_summary_history = self.vote_summary_history[-20:]
        return self.enqueue_review('vote', data, after=after)

    def present_event_result(self, result: dict, event: dict, rating_before: float,
                             volunteer_id: str | None = None):
        # Metadata only: scoring and the actual server d100 result are unchanged.
        result['event_type'] = event.get('type')
        result['round_number'] = self.round_number
        result['rating_before'] = rating_before
        result['rating_after'] = self.events_score_delta
        result['rating_change'] = round(self.events_score_delta - rating_before, 2)
        result['volunteer_name'] = (self.players[volunteer_id].name
                                    if event.get('type') == 'SURFACE_EVENT' and volunteer_id in self.players else None)
        result['pity_bonus_active'] = self.consecutive_event_failures >= 2
        self.enqueue_review('event', result)

    def event_result_for(self, result: dict | None, viewer: str | None):
        if result is None:
            return None
        safe = copy.deepcopy(result)
        health = safe.get('health_degraded')
        if health:
            player = self.players.get(health.get('player_id'))
            visible = (viewer == health.get('player_id') or self.phase == 'FINAL'
                       or (player and player.cards.get('health', {}).get('revealed')))
            if not visible:
                # Even the fact that a hidden condition changed is private.
                safe['health_degraded'] = None
        return safe

    def events_history_for(self, viewer: str | None):
        return [{**copy.deepcopy(entry), 'result': self.event_result_for(entry.get('result'), viewer)}
                for entry in self.resolved_events[-10:]]

    def _after_round_label(self):
        if len(self.get_alive_players()) <= self.bunker_capacity:
            return 'Итоги партии'
        return f'Раунд {self.round_number + 1} · открытие карточек'

    def _after_vote_label(self):
        if self.events_enabled and self.active_event:
            return 'Результат испытания'
        targets = (self.vote_results or {}).get('eliminated_ids') or []
        if targets and not self.veto_used:
            return 'Последнее слово'
        return self._after_round_label()

    def phase_context(self) -> dict:
        """Current action and the actual next phase, without client-side guessing."""
        phase = self.phase
        title = {'LOBBY': 'Подготовка партии', 'PROLOGUE': 'Вступление',
                 'REVEAL': 'Открытие карточек', 'SPEECH': 'Речь 1',
                 'ACCUSATION': 'Речь 2', 'VOTING': 'Тайное голосование',
                 'JUSTIFICATION': 'Защита кандидата', 'REVOTE': 'Переголосование',
                 'VOTE_RESULTS': 'Право вето', 'LAST_WORD': 'Последнее слово',
                 'FINAL': 'Итоги партии'}.get(phase, phase)
        speaker = None
        next_label = ''
        instruction = ''
        if phase in ('REVEAL', 'SPEECH'):
            speaker = self.get_current_speaker()
            next_label = 'Речь 1' if phase == 'REVEAL' else 'Речь 2'
            instruction = 'Карточки открываются по очереди.' if phase == 'REVEAL' else 'Обычное раскрытие уже завершено.'
        elif phase == 'ACCUSATION':
            speaker = self.get_current_accusation_speaker()
            next_label = 'Тайное голосование'
            instruction = 'Дополнительные индивидуальные речи перед голосованием.'
        elif phase == 'VOTING':
            next_label = 'Итоги голосования · показ 5 сек'
            instruction = 'Выберите кандидата и подтвердите голос. Чужой выбор пока скрыт.'
        elif phase == 'JUSTIFICATION':
            speaker = self.get_current_justification_speaker()
            next_label = 'Переголосование'
            instruction = 'Это защита, а не новое голосование. Кандидаты выступают по очереди.'
        elif phase == 'REVOTE':
            next_label = 'Итоги переголосования · показ 5 сек'
            instruction = 'Голосуйте заново только между кандидатами на защиту. Решает число голосов.'
        elif phase == 'VOTE_RESULTS':
            r = self.vote_results or {}
            veto = bool(r.get('eliminated_ids')) and not self.veto_used
            title = 'Право вето' if veto else 'Подтверждение решения'
            instruction = ('Решение ещё не окончательное. Примените вето или другую допустимую спецкарту.'
                           if veto else 'Решения об изгнании нет. Ожидается продолжение раунда.')
            next_label = self._after_vote_label()
        elif phase == 'LAST_WORD':
            speaker = self.players.get(self.eliminated_in_last_word_id)
            next_label = self._after_round_label()
            instruction = 'Изгнание уже подтверждено. Открытые досье доступны всем.'
        return {'phase': phase, 'title': title, 'speaker_name': speaker.name if speaker else None,
                'seconds': self.timer_seconds_left, 'instruction': instruction, 'next_label': next_label}

    def review_state_for(self, viewer: str | None):
        if not self.result_reviews:
            return None
        review = self.result_reviews[0]
        data = (self.event_result_for(review['data'], viewer) if review['kind'] == 'event'
                else copy.deepcopy(review['data']))
        context = self.phase_context()
        if len(self.result_reviews) > 1:
            following = self.result_reviews[1]
            next_label = 'Результат испытания' if following['kind'] == 'event' else 'Итоги голосования'
            next_detail = 'Общий показ 5 сек'
        elif review.get('after') == 'confirm_no_exile':
            next_label = self._after_vote_label()
            next_detail = 'Никто не изгнан'
        else:
            next_label = context['title']
            next_detail = ' · '.join(str(v) for v in (context['speaker_name'],
                                   f"{context['seconds']} сек" if context['seconds'] > 0 and self.phase != 'FINAL' else '',
                                   'таймер на паузе' if self.timer_is_paused and self.phase != 'FINAL' else '') if v)
        return {k: copy.deepcopy(review[k]) for k in ('id', 'kind', 'duration', 'seconds_left', 'is_paused')} | {
                'data': data, 'next_label': next_label, 'next_detail': next_detail,
                'game_timer_held': True}
