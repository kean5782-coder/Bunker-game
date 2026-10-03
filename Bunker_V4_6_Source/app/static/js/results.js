/* Age V4.3 — shared result review. Only the server advances the five-second
   countdown; a reconnect resumes the same review, never replays old history. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  const fmt = value => num(value).toLocaleString('ru-RU', {maximumFractionDigits:2});
  const signed = value => (num(value) > 0 ? '+' : '') + fmt(value);
  const ui = {game:null, manual:null, key:null, returnFocus:null, held:false, connected:true};
  const modal = document.createElement('section');
  modal.id = 'resultReviewModal';
  modal.className = 'result-review-overlay';
  modal.hidden = true;
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-labelledby', 'resultReviewTitle');
  modal.innerHTML = `<article class="result-review-card" tabindex="-1"><header class="result-review-head"><div><span class="eyebrow" id="resultReviewEyebrow"></span><h2 id="resultReviewTitle"></h2></div><button id="btnCloseResultReview" type="button" class="btn btn-secondary" aria-label="Закрыть результат">×</button></header><div id="resultReviewContent" class="result-review-content"></div><footer class="result-review-footer"><div class="result-review-clock" id="resultReviewClock" aria-hidden="true">5</div><div class="result-review-next"><span id="resultReviewTiming"></span><strong id="resultReviewNext"></strong><small id="resultReviewNextDetail"></small><small id="resultReviewTimerNote"></small></div><button id="btnClaimReviewHost" type="button" class="btn btn-secondary btn-small" hidden>Стать ведущим</button><button id="btnPauseResultReview" type="button" class="btn btn-secondary btn-small"></button></footer><div class="sr-only" id="resultReviewAnnounce" aria-live="polite"></div></article>`;
  document.body.appendChild(modal);
  const recall = document.createElement('button');
  recall.id = 'btnLastVoteReview';
  recall.className = 'btn btn-secondary btn-small result-vote-recall';
  recall.type = 'button';
  recall.textContent = 'Итоги';
  recall.hidden = true;
  $('dashPlayers')?.querySelector('.dash-panel-title').appendChild(recall);
  recall.onclick = () => openVote(ui.game?.last_vote_summary);

  function eventOutcome(r){
    if(r.outcome)return r.outcome;
    if(r.is_skipped)return 'Вылазка отменена';
    if(r.is_crit_success)return 'Выдающийся успех';
    if(r.is_crit_failure)return 'Тяжёлый провал';
    return r.is_success ? 'Успех' : 'Провал';
  }
  function eventTone(r){return r.is_skipped?'neutral':r.is_success?'success':'danger';}
  function voteExplanation(r){
    const names = r.candidate_names?.join(', ') || r.eliminated_name || '';
    if(r.decision==='defense')return {title:'Впереди — защита кандидатов', tone:'warning',
      text:r.is_tie?`Равенство голосов: ${names}. Сначала защита каждого, затем переголосование.`:`${names}: ${fmt(r.top_votes)} голосов; для решения без защиты требуется ${fmt(r.required_votes)}. Сначала защита, затем переголосование.`,
      note:'Никто ещё не изгнан. Сейчас только промежуточный результат.'};
    if(r.decision==='veto'||r.veto_used)return {title:'Вето принято. Изгнание отменено',tone:'success',text:'Решение изменено спецкартой. Все кандидаты остаются в бункере.',note:'Предыдущий список на изгнание больше не действует.'};
    if(r.decision==='skip'||r.skipped_round)return {title:'Изгнание пропущено',tone:'warning',text:'Большинство выбрало пропуск. В этом раунде все остаются.',note:'В следующем раунде предусмотрено двойное изгнание — не ниже вместимости бункера.'};
    if(r.decision==='none'||r.threshold_failed)return {title:'Никто не выбран на изгнание',tone:'neutral',text:'Нет действительных голосов против допустимого кандидата.',note:'Раунд продолжится без изгнания.'};
    return {title:r.double_elimination?'Два кандидата на изгнание':'Кандидат на изгнание',tone:'danger',text:names||'Подсчёт завершён.',
      note: r.source==='CORRECTION'?'Список изменён спецкартой. Решение ещё можно отменить до подтверждения.':
        r.tie_broken_by==='dice'?'При равенстве голосов кандидат выбран сервером случайно. Впереди ещё право вето.':
        r.revote_completed?'Переголосование завершено. Решение ещё не окончательное: впереди право вето.':
        r.double_elimination?'По правилам двойного изгнания выбраны два кандидата. Впереди право вето.':
        `Набрано ${fmt(r.top_votes)} голосов; для решения без защиты требуется ${fmt(r.required_votes)}. Защита пропускается, но впереди ещё право вето.`};
  }
  function voteBody(r){
    const explanation=voteExplanation(r),counts=r.counts||{},rows=r.detailed_tally||[];
    const extras=[['Воздержание',counts.abstain_weight],['За пропуск изгнания',counts.skip_weight],['Не подано',counts.uncast_weight],['Без допустимой цели',counts.other_weight]].filter(([,n])=>num(n)>0);
    const tally=[...rows.map(t=>({name:t.player_name,votes:t.votes})),...extras.map(([name,votes])=>({name,votes}))];
    return `<div class="review-decision"><p class="review-lead">${esc(explanation.text)}</p><p class="review-important">${esc(explanation.note)}</p></div><section class="review-ballots" aria-label="Итоговый подсчёт"><div class="review-section-title"><h3>Подсчёт голосов</h3><span>Общий вес: ${fmt(counts.total_weight??rows.reduce((a,t)=>a+num(t.votes),0))}</span></div><div class="review-tally-grid ${tally.length>8?'many':''}">${tally.map(t=>`<div class="review-tally-row narrative-tally"><strong title="${esc(t.name)}">${esc(t.name)}</strong><b>${fmt(t.votes)} <small>гол.</small></b></div>`).join('')||'<p class="muted">Голосов против кандидатов нет.</p>'}</div><p class="review-count-note">Двойной голос считается за два. Чужие бюллетени поимённо не раскрываются.</p></section>`;
  }
  function eventBody(r){
    const health=r.health_degraded;
    return `<p class="review-event-name">${esc(r.event_title||r.title||'Испытание')}</p><section class="review-consequences"><h3>Что произошло</h3>${r.title&&r.title!==r.event_title?`<p><b>${esc(r.title)}</b></p>`:''}<p class="review-lead">${esc(r.description||'Испытание разрешено.')}</p><p class="review-consequence-note">${esc(r.consequence||'')}</p>${r.guaranteed_success?'<p>Сработала спецкарта: гарантированный обычный успех.</p>':''}${r.volunteer_name?`<p>Доброволец: <b>${esc(r.volunteer_name)}</b>.</p>`:''}${health?`<p class="review-health">Здоровье ${esc(health.player_name)} ухудшилось: ${esc(health.new_condition)}.</p>`:''}${r.event_type==='SURFACE_EVENT'&&!health&&!r.is_skipped?'<small class="muted">Личное состояние добровольца — в его досье. Скрытая карта здоровья не раскрывается.</small>':''}</section>`;
  }
  function setBackgroundInert(value){
    for(const el of [$('viewWelcome'),$('viewGame'),document.querySelector('.hud-header')])if(el)el.inert=value;
  }
  function hide(){
    if(modal.hidden)return;
    modal.hidden=true;ui.key=null;
    if(ui.held){setBackgroundInert(false);ui.held=false;}
    if(ui.returnFocus?.isConnected&&ui.returnFocus.getClientRects().length&&!ui.returnFocus.disabled)ui.returnFocus.focus({preventScroll:true});
    ui.returnFocus=null;
  }
  function paint(review,automatic){
    if(!review)return hide();
    const r=review.data||{};
    const key=[ui.game?.room_code,review.id||r.summary_id||r.resolved_at,review.kind,automatic].join(':');
    if(ui.key!==key){
      if(modal.hidden)ui.returnFocus=document.activeElement;
      closeModals();
      ui.key=key;
      modal.dataset.kind=review.kind;
      modal.dataset.automatic=String(automatic);
      modal.dataset.tone=review.kind==='event'?eventTone(r):voteExplanation(r).tone;
      $('resultReviewEyebrow').textContent=`РАУНД ${r.round_number||ui.game?.round_number||1} · ${review.kind==='event'?'РЕЗУЛЬТАТ СОБЫТИЯ':r.source==='REVOTE'?'ИТОГИ ПЕРЕГОЛОСОВАНИЯ':r.source==='CORRECTION'?'РЕШЕНИЕ ИЗМЕНЕНО':'ИТОГИ ГОЛОСОВАНИЯ'}`;
      $('resultReviewTitle').textContent=review.kind==='event'?eventOutcome(r):voteExplanation(r).title;
      $('resultReviewContent').innerHTML=review.kind==='event'?eventBody(r):voteBody(r);
      $('resultReviewContent').scrollTop=0;
      modal.hidden=false;
      // Other dialog observers finish releasing their old focus first.
      requestAnimationFrame(()=>{if(!modal.hidden){setBackgroundInert(true);ui.held=true;modal.querySelector('article').focus({preventScroll:true});}});
      $('resultReviewAnnounce').textContent=`${$('resultReviewTitle').textContent}. ${automatic?'Общий показ результата.':''}`;
    }
    const paused=review.is_paused,seconds=Math.max(0,num(review.seconds_left));
    $('btnCloseResultReview').hidden=automatic;
    $('btnPauseResultReview').hidden=!automatic||!ui.game?.is_host;
    $('btnClaimReviewHost').hidden=!automatic||ui.game?.is_host||!ui.game?.can_claim_host;
    $('btnPauseResultReview').textContent=paused?'Продолжить показ':'Пауза показа';
    $('btnPauseResultReview').disabled=!ui.connected;
    $('resultReviewClock').hidden=!automatic;
    $('resultReviewClock').textContent=paused?'Ⅱ':seconds;
    $('resultReviewTiming').textContent=!automatic?'ПРОСМОТР СОХРАНЁННОГО ИТОГА':!ui.connected?'НЕТ СВЯЗИ С СЕРВЕРОМ':paused?'ПОКАЗ НА ПАУЗЕ':`АВТОМАТИЧЕСКИ ЧЕРЕЗ ${seconds} СЕК`;
    $('resultReviewNext').textContent=automatic?`Далее: ${review.next_label||'продолжение партии'}`:`Сейчас: ${ui.game?.phase_context?.title||ui.game?.phase||'партия'}`;
    $('resultReviewNextDetail').textContent=automatic?review.next_detail||'':ui.game?.phase_context?.speaker_name||'';
    $('resultReviewTimerNote').textContent=!automatic?'Ручной просмотр не останавливает общий таймер.':!ui.connected?'Ожидаем актуальное состояние. Локально этап не переключается.':'Время следующего этапа не расходуется.';
  }
  function render(g){
    if(ui.game&&ui.game.room_code!==g.room_code){ui.manual=null;hide();}
    ui.game=g;ui.connected=true;
    recall.hidden=!g.last_vote_summary||g.phase==='LOBBY';
    recall.title=g.last_vote_summary?`Итог голосования · раунд ${g.last_vote_summary.round_number}`:'';
    if(g.result_review){ui.manual=null;paint(g.result_review,true);}else if(ui.manual){paint(ui.manual,false);}else hide();
  }
  function openVote(data){if(!data||ui.game?.result_review)return;ui.manual={kind:'vote',data};paint(ui.manual,false);}
  function openEvent(data){if(!data||ui.game?.result_review)return;ui.manual={kind:'event',data};paint(ui.manual,false);}
  function closeManual(){if(ui.game?.result_review)return;ui.manual=null;hide();}
  $('btnCloseResultReview').onclick=closeManual;
  $('btnClaimReviewHost').onclick=()=>sendAction('CLAIM_HOST',{});
  $('btnPauseResultReview').onclick=()=>{const r=ui.game?.result_review;if(r&&ui.game.is_host)sendAction('HOST_PAUSE_TIMER',{is_paused:!r.is_paused});};
  modal.addEventListener('click',e=>{if(e.target===modal)closeManual();});
  document.addEventListener('keydown',e=>{
    if(document.getElementById('audioSettingsDialog')?.open)return;
    if(modal.hidden)return;
    if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();closeManual();return;}
    if(e.key==='Tab'){
      const controls=[...modal.querySelectorAll('button')].filter(el=>!el.hidden&&!el.disabled);
      if(!controls.length){e.preventDefault();modal.querySelector('article').focus();return;}
      const index=controls.indexOf(document.activeElement);
      if(index===-1||(!e.shiftKey&&index===controls.length-1)||(e.shiftKey&&index===0)){
        e.preventDefault();controls[e.shiftKey?controls.length-1:0].focus();
      }
    }
  },true);
  window.bunkerResults={render,openVote,openEvent,eventOutcome,
    reset(){ui.manual=null;ui.game=null;ui.connected=true;recall.hidden=true;hide();},
    disconnected(){ui.connected=false;if(!modal.hidden)paint(ui.game?.result_review||ui.manual,Boolean(ui.game?.result_review));}};
})();
