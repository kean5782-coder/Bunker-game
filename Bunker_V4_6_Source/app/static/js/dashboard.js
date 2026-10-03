/** Visual v1: presentation only. Server state remains authoritative.
 * No hidden-card ranking, local dice outcomes or optimistic vote confirmations.
 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => escapeHtml(String(value ?? ''));
  const cats = ['gender','body','trait','profession','health','hobby','phobia','big_inventory','backpack','fact','special'];
  const labels = {gender:'Пол / возраст',body:'Телосложение',trait:'Характер',profession:'Профессия',health:'Здоровье',hobby:'Хобби',phobia:'Фобия',big_inventory:'Инвентарь',backpack:'Рюкзак',fact:'Факт',special:'Спецкарта',biology:'Биология',baggage:'Багаж',stolen_baggage:'Трофей',traitor:'Тайная роль'};
  const paths = {gender:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8M18 8h4m-2-2v4',body:'M12 3v2m-6 3 6 2 6-2M12 10v6m0 0-4 5m4-5 4 5M10 3a2 2 0 1 0 4 0',trait:'M4 4h16v13H9l-5 4V4m4 5h8m-8 4h5',profession:'M4 7h16v14H4V7m4 0V3h8v4M4 12h16m-10 0v3h4v-3',health:'M9 3h6v6h6v6h-6v6H9v-6H3V9h6V3',hobby:'m12 3 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1 3-6',phobia:'m12 3 10 18H2L12 3m0 6v5m0 3v1',big_inventory:'M3 7h18v14H3V7m4 0V3h10v4M3 12h18m-14-2v4m10-4v4',backpack:'M6 7h12l2 14H4L6 7m3 0V3h6v4m-7 8h8v6',fact:'M5 2h10l4 4v16H5V2m9 0v5h5M8 11h8m-8 4h8m-8 4h5',special:'m13 2-9 12h7l-1 8 10-13h-8l1-7',lock:'M6 10h12v11H6V10m3 0V6a3 3 0 0 1 6 0v4m-3 4v3',eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12m10-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6',check:'m4 12 5 5L20 6',shield:'M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6l-9-4',gear:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2',mic:'M9 3h6v11H9V3m-3 8v3a6 6 0 0 0 12 0v-3m-6 9v3m-4 0h8',log:'M5 3h14v18H5V3m4 4h6m-6 5h6m-6 5h6',air:'M3 7h13a3 3 0 1 0-3-3M3 12h17M3 17h11a3 3 0 1 1-3 3',food:'M12 2s-8 10-8 14a8 8 0 0 0 16 0c0-4-8-14-8-14',people:'M9 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6m7 1a3 3 0 0 1 0 6M2 21v-5a5 5 0 0 1 10 0v5m4 0v-5a5 5 0 0 0-1-3'};
  const icon = name => `<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name]||paths.fact}"/></svg>`;
  const ui = {game:null, room:null,phase:null,follow:true,focusId:null,view:'focus',mobile:'players',voteChoice:null,votePending:null,specialPending:false,revealPending:null,signatures:{},seenResult:null,actionContext:null};
  const phases={LOBBY:'Сбор у шлюза',PROLOGUE:'Вступление',REVEAL:'Открытие карточек',SPEECH:'Первый круг речей',ACCUSATION:'Второй круг речей',DEBATE:'Второй круг речей',JUSTIFICATION:'Защита кандидата',VOTING:'Тайное голосование',REVOTE:'Переголосование',VOTE_RESULTS:'Ожидание вето',LAST_WORD:'Последнее слово',FINAL:'Итоги партии'};
  function make(tag, cls, html=''){const e=document.createElement(tag);e.className=cls;e.innerHTML=html;return e;}
  function btn(text, fn, cls='btn btn-secondary'){const e=make('button',cls,esc(text));e.type='button';e.onclick=fn;return e;}
  function move(id,to){if($(id))to.appendChild($(id));}
  function me(g=ui.game){return g?.players.find(p=>p.id===state.playerId);}
  function speaker(g=ui.game){if(!g)return null;return ['REVEAL','SPEECH'].includes(g.phase)?g.current_speaker?.id:g.phase==='ACCUSATION'?g.accusation_speaker?.id:g.phase==='JUSTIFICATION'?g.justification_status?.speaker_id:g.phase==='DEBATE'?g.debate_speaker?.id:g.phase==='LAST_WORD'?g.last_word?.speaker_id:null;}
  function known(p,c,g=ui.game){return Boolean(c && (c.revealed||p.id===state.playerId||g?.phase==='FINAL'));}
  function playerCats(p,g=ui.game){const c=[...cats];if(p.cards?.biology&&!p.cards?.gender)c.push('biology');if(p.cards?.baggage&&!p.cards?.backpack)c.push('baggage');if(p.cards?.stolen_baggage)c.push('stolen_baggage');if(p.cards?.traitor&&(p.id===state.playerId||g?.phase==='FINAL'))c.push('traitor');return c.filter(cat=>p.cards?.[cat]);}
  function initials(p){return String(p.name||'?').trim().split(/\s+/).slice(0,2).map(s=>Array.from(s)[0]).join('').toUpperCase();}
  function avatar(p){return `<span class="avatar" aria-hidden="true">${esc(initials(p))}</span>`;}
  function status(p,g=ui.game){const a=[];if(p.id===state.playerId)a.push('Вы');if(p.id===speaker(g))a.push(g.phase==='REVEAL'?'Открывает карточки':'Сейчас говорит');if(p.is_host)a.push('Ведущий');if(p.id.startsWith('bot_'))a.push('Бот');if(!p.connected)a.push('Нет связи');if(!p.is_alive)a.push('Изгнан');else if(p.is_quarantined)a.push('Изолятор');else if(p.is_silenced)a.push('Молчание');return a.join(' · ')||(g?.phase==='LOBBY'?'Подключён':'В бункере');}
  function same(name,data){const sig=JSON.stringify(data);if(ui.signatures[name]===sig)return true;ui.signatures[name]=sig;return false;}
  function invalidate(...keys){keys.forEach(k=>delete ui.signatures[k]);}
  function replace(el,html){
    // Restore keyboard focus and local scroll when relevant server data changes.
    const focus=el.contains(document.activeElement)?document.activeElement:null;
    const id=focus?.id, key=focus?.dataset.focusKey, scroll=el.scrollTop;
    const details=[...el.querySelectorAll('details[open]')].map(d=>d.dataset.key).filter(Boolean);
    el.innerHTML=html;details.forEach(k=>{const d=el.querySelector(`details[data-key="${k}"]`);if(d)d.open=true;});
    el.scrollTop=scroll;
    if(id&&$(id)&&el.contains($(id)))$(id).focus({preventScroll:true});
    else if(key){[...el.querySelectorAll('[data-focus-key]')].find(e=>e.dataset.focusKey===key)?.focus({preventScroll:true});}
  }
  function storageGet(k,session=false){try{return (session?sessionStorage:localStorage).getItem(k);}catch(_){return null;}}
  function storageSet(k,v,session=false){try{(session?sessionStorage:localStorage).setItem(k,v);}catch(_){}}
  const media=matchMedia('(prefers-reduced-motion: reduce)');
  let motion=storageGet('bunker_visual_motion')||'full';if(!['full','calm','minimal'].includes(motion))motion='full';
  function effectiveMotion(){return media.matches&&motion==='full'?'calm':motion;}
  function applyMotion(){refreshClipControls();document.body.dataset.motion=effectiveMotion();if($('visualMotion'))$('visualMotion').value=motion;document.querySelectorAll('video').forEach(v=>{if(effectiveMotion()!=='full'||window.soundFX?.settings.clips===false||document.hidden||v.closest('[style*="display: none"]'))v.pause();});if($('motionSystemNote'))$('motionSystemNote').textContent=media.matches?'В системе включено уменьшение движения. Оно соблюдается и в полном режиме.':'Настройка сохраняется только в этом браузере.';}
  media.addEventListener('change',applyMotion);
  // Resume only an interrupted clip. A completed five-second clip never loops.
  let resumeClipOnVisible=false;
  document.addEventListener('visibilitychange',()=>{
    const v=$('prologueVideoBg');if(!v)return;
    if(document.hidden){resumeClipOnVisible=!v.paused&&!v.ended;v.pause();}
    else if(resumeClipOnVisible&&effectiveMotion()==='full'&&window.soundFX?.settings.clips!==false&&$('cinematicPrologueModal').style.display==='flex'&&ui.game?.phase==='PROLOGUE'&&!v.ended){v.play().catch(()=>{});resumeClipOnVisible=false;}
  });

  function showMobile(name){ui.mobile=name;$('dashWorkspace').dataset.mobile=name;document.querySelectorAll('[data-mobile-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mobileTab===name)));}
  // Follow mode is explicit: a manual dossier stays pinned until the user
  // resumes it. Selecting the *current* participant also resumes following.
  // Reading a dossier over a vote/final is temporary, not a navigation change.
  function syncPlayerFocus(g=ui.game){
    if(!g)return null;
    const activeId=speaker(g);
    const active=g.players.some(p=>p.id===activeId)?activeId:null;
    if(ui.focusId&&!g.players.some(p=>p.id===ui.focusId))ui.follow=true;
    if(ui.follow&&active)ui.focusId=active;
    if(!g.players.some(p=>p.id===ui.focusId))ui.focusId=active||me(g)?.id||g.players[0]?.id||null;
    return active;
  }
  function renderFollowControl(g,active){
    const button=$('dashFindSpeaker');
    const voting=['VOTING','REVOTE','VOTE_RESULTS'].includes(g.phase);
    // Keep the same button/listener accessible between speaking turns without
    // taking any additional height away from the candidate grid.
    const parent=voting?$('dashPlayers').querySelector('.dash-panel-title'):$('dashPlayerControls');
    if(button.parentElement!==parent){
      const focused=document.activeElement===button;
      parent.appendChild(button);
      if(focused)button.focus({preventScroll:true});
    }
    button.hidden=['LOBBY','FINAL'].includes(g.phase);
    button.disabled=false;
    button.dataset.followMode=ui.follow?'auto':'manual';
    button.setAttribute('aria-pressed',String(ui.follow));
    button.textContent=ui.follow?'Авто: вкл.':'Включить авто';
    const message=ui.follow
      ?(active?'Автопереключение включено. Показать текущего участника и следить за следующими ходами.':'Автопереключение включено. Досье сменится, когда появится активный участник.')
      :(active?'Включить автопереключение: перейти к текущему участнику и следить за следующими ходами.':'Включить автопереключение. Оно сработает, когда появится активный участник.');
    button.title=message;button.setAttribute('aria-label',message);
  }
  function resumeFollow(){
    if(!ui.game)return;
    ui.follow=true;ui.view='focus';
    const active=syncPlayerFocus();
    invalidate('players','roster');showMobile('players');
    renderPlayers(ui.game);renderRoster(ui.game);
    const name=ui.game.players.find(p=>p.id===active)?.name;
    $('dashLive').textContent=name?`Автопереключение включено. Сейчас: ${name}.`:'Автопереключение включено. Ожидание следующего участника.';
  }
  function focusPlayer(id){
    const g=ui.game,p=g?.players.find(x=>x.id===id);
    if(!p)return;
    if(['VOTING','REVOTE','VOTE_RESULTS','FINAL'].includes(g.phase)){openDossier(p);return;}
    if(id===speaker(g)){resumeFollow();return;}
    ui.focusId=id;ui.follow=false;ui.view='focus';
    invalidate('players','roster');showMobile('players');
    renderPlayers(g);renderRoster(g);
    $('dashLive').textContent=`Досье ${p.name} закреплено. Для возврата нажмите «Включить авто».`;
  }
  function openUtility(name){closeModals();$('dashUtility').style.display='flex';document.querySelectorAll('.dash-utility-page').forEach(p=>p.hidden=p.id!==`dashUtility-${name}`);$('dashUtilityTitle').textContent={menu:'Меню комнаты',host:'Управление ведущего',bunker:'Паспорт убежища',log:'Бортовой журнал',settings:'Оформление и движение'}[name]||'Меню';if(name==='bunker'&&ui.game?.catastrophe){state.scenarioCollapsed=false;state.lastScenarioSig=null;renderScenario(ui.game);}}
  function setup(){
    const main=$('viewGame'),head=document.querySelector('.hud-header');
    move('hudStatsGroup',head);
    const utilities=make('div','header-tools');
    const b=btn('Убежище',()=>openUtility('bunker'));b.id='dashBunkerButton';b.innerHTML=icon('shield')+'<span>Убежище</span>';
    const log=btn('Журнал',()=>openUtility('log'));log.id='dashLogButton';log.innerHTML=icon('log')+'<span>Журнал</span>';
    const settings=btn('Оформление',()=>openUtility('settings'));settings.id='dashSettingsButton';settings.title='Оформление и движение';settings.setAttribute('aria-label',settings.title);settings.innerHTML=icon('gear');
    const menu=btn('Меню',()=>openUtility('menu'));menu.id='dashMenuButton';utilities.append(b,log,settings,menu);head.appendChild(utilities);
    const utility=make('div','modal-overlay',`<section class="bunker-modal dash-utility" role="document"><header class="modal-header"><h2 id="dashUtilityTitle" class="modal-title">Меню</h2><button id="dashUtilityClose" class="modal-close" aria-label="Закрыть окно">×</button></header><div id="dashUtilityBody" class="modal-body"></div></section>`);utility.id='dashUtility';utility.style.display='none';document.body.appendChild(utility);$('dashUtilityClose').onclick=closeModals;
    for(const name of ['menu','host','bunker','log','settings']){const p=make('div','dash-utility-page');p.id=`dashUtility-${name}`;$('dashUtilityBody').appendChild(p);}
    $('dashUtility-menu').appendChild(document.querySelector('.hud-actions'));
    const host=btn('Управление ведущего',()=>openUtility('host'));host.id='dashHostMenu';$('dashUtility-menu').prepend(host);
    move('hostControlsBar',$('dashUtility-host'));move('hostDebateControls',$('dashUtility-host'));
    move('scenarioHeaderBar',$('dashUtility-bunker'));move('scenarioSection',$('dashUtility-bunker'));
    $('dashUtility-bunker').appendChild(make('p','muted bunker-disclosure','Во время партии здесь только публичные условия. Итог колонии станет известен в финале. Режим информации выбран ведущим в лобби.'));
    $('dashUtility-log').appendChild($('gameLogBox').parentElement);
    $('dashUtility-settings').innerHTML=`<div class="settings-intro">Параметры ниже управляют изображением. Звук настраивается отдельно.</div><label class="form-label" for="visualMotion">Визуальные эффекты</label><select id="visualMotion" class="form-input"><option value="full">Полный — короткие переходы и видео вступления</option><option value="calm">Спокойный — статичные сцены, минимум движения</option><option value="minimal">Минимальный — без фонов и анимации</option></select><p id="motionSystemNote" class="muted"></p><div class="settings-guide"><h3>Управление</h3><p>Enter / пробел — открыть выбранную карточку. Escape — закрыть подробности. Tab — перейти к следующему элементу.</p><p>Нажатие на карточку показывает описание, а кнопка «Открыть» раскрывает её другим игрокам.</p></div>`;
    $('visualMotion').onchange=e=>{motion=e.target.value;storageSet('bunker_visual_motion',motion);applyMotion();};applyMotion();
    for(const mode of ['Create','Join'])$('access'+mode).onclick=()=>{for(const m of ['Create','Join']){$('access'+m+'Pane').hidden=m!==mode;$('access'+m).setAttribute('aria-pressed',String(m===mode));}};
    for(const [input,button] of [['inputJoinRoom','btnJoinRoom'],['inputPlayerName','btnJoinRoom'],['inputHostName','btnCreateRoom']])$(input).addEventListener('keydown',e=>{if(e.key==='Enter')$(button).click();});
    const top=make('section','dash-top');top.id='dashTop';main.prepend(top);top.appendChild(document.querySelector('.phase-banner'));
    const rail=make('nav','dash-phase-track');rail.id='dashPhaseTrack';rail.setAttribute('aria-label','Этапы партии');top.appendChild(rail);
    const roster=make('nav','dash-roster');roster.id='dashRoster';roster.setAttribute('aria-label','Все участники');main.appendChild(roster);
    const lobby=make('section','dash-lobby',`<div class="lobby-hero"><span class="eyebrow">ПЕРЕД ЗАКРЫТИЕМ ШЛЮЗА</span><h1>У каждого есть причина<br>остаться <em>внутри.</em></h1><p>Пригласите друзей, настройте убежище<br>и начните первую речь.</p><div id="lobbyPopulation"></div></div><div id="lobbySettingsSlot"></div>`);lobby.id='dashLobby';main.appendChild(lobby);move('hostLobbySettings',$('lobbySettingsSlot'));
    const wait=make('div','lobby-wait','<span class="eyebrow">ОЖИДАНИЕ СТАРТА</span><h2>Вы в списке участников.</h2><p>Ведущий выбирает параметры партии. Карточки появятся после раздачи.</p>');wait.id='lobbyGuestWait';$('lobbySettingsSlot').appendChild(wait);
    const work=make('div','dash-workspace');work.id='dashWorkspace';work.dataset.mobile='players';main.appendChild(work);
    for(const [id,title,n] of [['dashMine','Ваше досье','01'],['dashPlayers','Участники','02'],['dashActions','Решение и испытание','03']]){const p=make('section','dash-panel',`<header class="dash-panel-title"><span>${n}</span><h2>${title}</h2></header>`);p.id=id;work.appendChild(p);}
    move('myDossierSection',$('dashMine'));const empty=make('p','dash-empty','Ваши карточки появятся после раздачи.');empty.id='dashMyEmpty';$('dashMine').appendChild(empty);
    const controls=make('div','dash-player-controls',`<div class="segmented"><button id="dashViewFocus" class="btn btn-small" aria-pressed="true">Досье</button><button id="dashViewAll" class="btn btn-small" aria-pressed="false">Обзор всех</button></div><button id="dashFindSpeaker" type="button" class="btn btn-secondary btn-small dash-follow-control" aria-pressed="true">Авто: вкл.</button>`);controls.id='dashPlayerControls';$('dashPlayers').appendChild(controls);
    $('dashViewFocus').onclick=()=>{ui.view='focus';invalidate('players');renderPlayers(ui.game);};$('dashViewAll').onclick=()=>{ui.view='all';invalidate('players');renderPlayers(ui.game);};$('dashFindSpeaker').onclick=resumeFollow;
    const speechPanel=make('section','speech-effects');speechPanel.id='speechEffectsPanel';speechPanel.hidden=true;speechPanel.setAttribute('aria-label','Ограничения речи');$('dashPlayers').appendChild(speechPanel);
    const oldPlayers=$('allPlayersGrid').parentElement;move('allPlayersGrid',$('dashPlayers'));oldPlayers.remove();
    move('votingSection',$('dashPlayers'));$('votingSection').innerHTML='<div class="vote-heading"><h2>Кого оставить за шлюзом?</h2><p id="votingProgressBanner" aria-live="polite"></p></div><div id="voteCandidatesGrid" class="vote-grid"></div><p id="thresholdNotice" class="muted"></p>';
    move('voteResultsSection',$('dashPlayers'));$('voteResultsSection').innerHTML='<div class="vote-heading"><h2>Решение участников</h2><p id="voteResultsCountdown"></p></div><div id="voteOutcomeBanner" role="status"></div><div id="voteTallyGrid"></div><div id="voteResultsHostControls"><button id="btnHostNextRoundNow" class="btn btn-primary">Подтвердить и продолжить</button></div>';
    const turn=make('div','dash-priority');turn.id='dashAction-turn';$('dashActions').appendChild(turn);
    move('speakerSpotlight',turn);move('lastWordSection',turn);move('spectatorJoinBanner',turn);
    const help=make('p','dash-turn-help');help.id='dashTurnHelp';turn.appendChild(help);
    for(const id of ['secretPeekAlert','silenceWarning','exileVendettaBox'])move(id,turn);
    const voteAction=make('div','dash-vote-action');voteAction.id='dashAction-vote';$('dashActions').appendChild(voteAction);
    const ev=make('div','dash-event');ev.id='dashAction-event';$('dashActions').appendChild(ev);move('eventChallengeSection',ev);
    const mobile=make('nav','dash-mobile-nav');mobile.setAttribute('aria-label','Разделы экрана');mobile.id='dashMobileNav';for(const [id,title]of[['mine','Мои карты'],['players','Участники'],['actions','Действие']]){const b=btn(title,()=>showMobile(id));b.dataset.mobileTab=id;mobile.appendChild(b);}main.appendChild(mobile);
    main.appendChild($('finalScreenSection'));
    const announce=make('div','sr-only');announce.id='dashLive';announce.setAttribute('aria-live','polite');document.body.appendChild(announce);
    // Stable delegated listeners: timer ticks never accumulate callbacks.
    $('myCardsList').addEventListener('click',e=>{const reveal=e.target.closest('[data-reveal]');if(reveal){revealCard(reveal.dataset.reveal);return;}const special=e.target.closest('[data-special]');if(special){useSpecial(me()?.cards.special);return;}const view=e.target.closest('[data-open-card]');if(view){const p=me();if(p)openDossier({...p,cards:{[view.dataset.openCard]:p.cards[view.dataset.openCard]}});}});
    $('dashRoster').addEventListener('click',e=>{const target=e.target.closest('[data-player]');if(target)focusPlayer(target.dataset.player);});
    $('allPlayersGrid').addEventListener('click',e=>{const p=ui.game?.players.find(p=>p.id===(e.target.closest('[data-player]')?.dataset.player||ui.focusId));if(!p)return;const admin=e.target.closest('[data-admin]');if(admin){if(confirm(`${admin.dataset.admin==='kick'?'Удалить':p.is_alive?'Изгнать':'Вернуть'} игрока ${p.name}?`))sendAction(admin.dataset.admin==='kick'?'HOST_KICK':p.is_alive?'HOST_ELIMINATE':'HOST_RESTORE',admin.dataset.admin==='kick'?{player_id:p.id}:{target_id:p.id});return;}const card=e.target.closest('[data-trait]');if(card){openDossier({...p,cards:{[card.dataset.trait]:p.cards[card.dataset.trait]}});return;}if(e.target.closest('[data-full-dossier]'))openDossier(p);else if(e.target.closest('[data-player]'))focusPlayer(p.id);});
    $('voteCandidatesGrid').addEventListener('click',e=>{const t=e.target.closest('[data-candidate]');if(!t)return;const p=ui.game.players.find(p=>p.id===t.dataset.candidate);if(e.target.closest('[data-vote-details]')){openDossier(p);return;}if(e.target.closest('[data-select-vote]')){ui.voteChoice=p.id;invalidate('vote');renderVote(ui.game);if(matchMedia('(max-width: 1099px)').matches)showMobile('actions');}});
    $('dashAction-vote').addEventListener('click',e=>{if(e.target.closest('[data-confirm-vote]'))castVote(ui.voteChoice);if(e.target.closest('[data-abstain]'))castVote('ABSTAIN');if(e.target.closest('[data-skip-round]'))castVote('SKIP_ROUND');});
    $('eventChallengeSection').addEventListener('click',e=>{const b=e.target.closest('[data-event-action]');if(!b||!state.isHost)return;const a=b.dataset.eventAction;if(a==='resolve'){b.disabled=true;if(!sendAction('RESOLVE_EVENT',{}))b.disabled=false;}if(a==='trigger')sendAction('HOST_TRIGGER_EVENT',{});if(a==='skip')sendAction('SKIP_SORTIE',{skip:!ui.game.events_state?.is_sortie_skipped});});
    $('eventChallengeSection').addEventListener('change',e=>{if(e.target.id==='selectEventVolunteer'&&state.isHost)sendAction('ASSIGN_VOLUNTEER',{volunteer_id:e.target.value});});
    $('btnHostNextRoundNow').onclick=()=>{if(state.isHost&&ui.game?.phase==='VOTE_RESULTS')sendAction('CONFIRM_ELIMINATION',{});};
    $('finalScreenSection').addEventListener('click',e=>{const b=e.target.closest('[data-player]');if(b){const p=ui.game.players.find(p=>p.id===b.dataset.player);if(p)openDossier(p);}});
    initDialogs();showMobile('players');
  }
  function renderRoster(g){if(!g||same('roster',[g.players.map(p=>[p.id,p.name,p.is_alive,p.connected,p.is_host,p.is_silenced,p.is_quarantined]),speaker(g),ui.focusId,g.phase]))return;replace($('dashRoster'),g.players.map((p,i)=>`<button class="roster-token ${p.id===speaker(g)?'is-speaker':''} ${p.id===ui.focusId?'is-selected':''} ${!p.is_alive?'is-exiled':''}" data-player="${esc(p.id)}" data-focus-key="roster-${esc(p.id)}" aria-label="${esc(p.name)}. ${esc(status(p,g))}" aria-pressed="${p.id===ui.focusId}">${avatar(p)}<span class="roster-info"><strong>${esc(p.name)}</strong><small>${esc(status(p,g))}</small></span><span class="roster-number">${String(i+1).padStart(2,'0')}</span></button>`).join(''));}
  function renderPlayers(g){
    if(!g)return;ui.game=g;
    const active=syncPlayerFocus(g);
    renderFollowControl(g,active);
    $('dashViewFocus').setAttribute('aria-pressed',String(ui.view==='focus'));$('dashViewAll').setAttribute('aria-pressed',String(ui.view==='all'));
    if(same('players',[g.players,g.phase,active,ui.focusId,ui.view,ui.follow,state.isHost]))return;
    const grid=$('allPlayersGrid');grid.dataset.view=g.phase==='LOBBY'?'lobby':ui.view;
    if(g.phase==='LOBBY'||ui.view==='all'){
      replace(grid,`<div class="dash-overview-grid">${g.players.map((p,i)=>{const prof=p.cards?.profession;const opened=Object.entries(p.cards||{}).filter(([c,v])=>c!=='traitor'&&v.revealed).length;return `<article class="player-tile ${p.id===active?'is-speaker':''} ${!p.is_alive?'is-exiled':''}" data-player="${esc(p.id)}"><button data-player="${esc(p.id)}" data-focus-key="player-${esc(p.id)}" class="player-tile-main">${avatar(p)}<strong>${esc(p.name)}</strong><span class="player-status">${esc(status(p,g))}</span><span class="player-prof">${g.phase==='LOBBY'?`Участник ${String(i+1).padStart(2,'0')}`:esc(known(p,prof,g)?prof.value:'Профессия скрыта')}</span>${g.phase!=='LOBBY'?`<span class="opened-count">Открыто: ${opened}</span>`:''}</button>${state.isHost&&p.id!==state.playerId?`<button class="btn btn-small admin-button" data-admin="${g.phase==='LOBBY'?'kick':'status'}">${g.phase==='LOBBY'?'Удалить':p.is_alive?'Изгнать':'Вернуть'}</button>`:''}</article>`;}).join('')}</div>`);return;
    }
    const p=g.players.find(p=>p.id===ui.focusId);if(!p){grid.innerHTML='<p class="dash-empty">Нет участников.</p>';return;}
    replace(grid,`<header class="dash-focus-header">${avatar(p)}<div><span class="eyebrow">${!ui.follow?'ПРОСМОТР ЗАКРЕПЛЁН':p.id===active?(g.phase==='REVEAL'?'ОТКРЫВАЕТ КАРТОЧКИ':'СЕЙЧАС ГОВОРИТ'):'ЛИЧНОЕ ДЕЛО'}</span><h2>${esc(p.name)}</h2><p>${esc(status(p,g))}</p></div><button class="btn btn-small btn-secondary" data-full-dossier="true" data-focus-key="full-dossier">Досье целиком</button></header><div class="dash-focus-grid">${playerCats(p,g).map(cat=>{const c=p.cards[cat],k=known(p,c,g);const note=cat==='special'&&c.used?'Использована':c.revealed?'Открыто всем':g.phase==='FINAL'?'Рассекречено':k?'Только вам':'Закрыто';return `<button type="button" class="dash-focus-trait ${k?(c.revealed?'revealed':'private'):'locked'}" data-trait="${cat}" data-focus-key="trait-${cat}" ${!k?'disabled':''}><span class="dash-trait-label">${icon(cat)}${esc(labels[cat]||cat)}</span><strong class="dash-trait-main">${k?esc(c.value):`${icon('lock')} Скрыто`}</strong><span class="dash-trait-note">${esc(note)}</span></button>`;}).join('')}</div>`);
  }
  function revealReason(g,p,cat){const s=g.reveal_status||{};if(!p.is_alive)return 'Вы изгнаны';if(p.is_quarantined)return 'До конца изолятора';if(g.phase!=='REVEAL')return 'Раскрытие только на отдельном этапе открытия';if(!s.is_current_speaker)return 'Дождитесь своего хода открытия';if(s.quota_reached)return 'Норма раскрытия выполнена';if(g.round_number===1&&!p.cards.profession?.revealed&&cat!=='profession')return 'Сначала откройте профессию';return '';}
  // Age V4.2: own cards are keyed by category. A foreign player's reveal quota
  // is NOT part of our render identity. Only the visible card/action changes;
  // DOM identity, keyboard focus and list scroll survive every state snapshot.
  const ownCardSignatures = new WeakMap();
  function textIfChanged(el, value){
    const text=String(value??'');
    if(el.textContent!==text)el.textContent=text;
  }
  function attrIfChanged(el, name, value){
    if(value===null){if(el.hasAttribute(name))el.removeAttribute(name);}
    else if(el.getAttribute(name)!==String(value))el.setAttribute(name,String(value));
  }
  function ownCardView(g,p,cat){
    const c=p.cards[cat],special=cat==='special',secret=cat==='traitor';
    const can=!c.revealed&&!special&&!secret&&!revealReason(g,p,cat);
    let action=null;
    if(can)action={kind:'reveal',disabled:Boolean(ui.revealPending),
      title:'Открыть всем игрокам',aria:`Раскрыть: ${labels[cat]||cat}`,
      html:`${ui.revealPending===cat?'…':icon('eye')}<span>Открыть</span>`};
    if(special&&!c.used)action={kind:'special',disabled:c.available===false||ui.specialPending,
      title:c.unavailable_reason||'Применить спецкарту',aria:null,
      html:`${icon(c.available===false?'lock':'special')}<span>${ui.specialPending?'Отправка':'Применить'}</span>`};
    return {cat,value:String(c.value??''),
      className:`dossier-item ${c.revealed?'revealed':'secret'} ${special?'special-card':''} ${secret?'traitor-card':''} ${can?'can-reveal':''}`,
      note:special&&c.used?'Использована':c.revealed?'Открыто всем':'Только вам',action};
  }
  function patchOwnCard(node,view){
    const signature=JSON.stringify(view);
    if(ownCardSignatures.get(node)===signature)return;
    attrIfChanged(node,'class',view.className);
    const read=node.querySelector('.card-read');
    attrIfChanged(read,'aria-label',`${labels[view.cat]||view.cat}: ${view.value}. Подробнее`);
    textIfChanged(node.querySelector('.dossier-val'),view.value);
    textIfChanged(node.querySelector('.card-note'),view.note);
    let button=node.querySelector('.card-action');
    if(view.action){
      const a=view.action;
      if(!button){button=make('button','card-action');button.type='button';node.querySelector('.card-footer').appendChild(button);}
      attrIfChanged(button,'data-reveal',a.kind==='reveal'?view.cat:null);
      attrIfChanged(button,'data-special',a.kind==='special'?'true':null);
      attrIfChanged(button,'data-focus-key',a.kind==='special'?'use-special':`reveal-${view.cat}`);
      attrIfChanged(button,'title',a.title);
      attrIfChanged(button,'aria-label',a.aria);
      if(button.disabled!==Boolean(a.disabled)){
        const focused=document.activeElement===button;
        button.disabled=Boolean(a.disabled);
        // Disabling a focused submit button otherwise sends focus to <body>
        // before the server acknowledgement can remove that action.
        if(a.disabled&&focused)read.focus({preventScroll:true});
      }
      // Availability changes do not replace the button or its keyboard focus.
      if(button._actionHTML!==a.html){button.innerHTML=a.html;button._actionHTML=a.html;}
    }else if(button){
      const focused=document.activeElement===button;
      button.remove();
      if(focused)read.focus({preventScroll:true});
    }
    ownCardSignatures.set(node,signature);
  }
  function renderOwnCards(list,views,owner){
    // A different viewer/room must never reuse the previous owner's card cache.
    if(list.dataset.owner!==owner){list.replaceChildren();list.dataset.owner=owner;}
    const nodes=new Map([...list.children].map(node=>[node.dataset.cat,node]));
    const order=new Set(views.map(view=>view.cat));
    const focused=document.activeElement;
    let removedFocus=false;
    for(const [cat,node] of nodes){
      if(!order.has(cat)){removedFocus=removedFocus||node.contains(focused);node.remove();}
    }
    views.forEach((view,index)=>{
      let node=nodes.get(view.cat);
      if(!node){
        node=make('article','dossier-item');node.dataset.cat=view.cat;
        node.innerHTML=`<button type="button" class="card-read" data-open-card="${view.cat}" data-focus-key="card-${view.cat}"><span class="dossier-label">${icon(view.cat)}${esc(labels[view.cat]||view.cat)}</span><strong class="dossier-val"></strong></button><div class="card-footer"><span class="card-note"></span></div>`;
      }
      // Do not append existing nodes unnecessarily: moving them loses focus.
      if(list.children[index]!==node)list.insertBefore(node,list.children[index]||null);
      patchOwnCard(node,view);
    });
    const rows=String(Math.ceil(views.length/2));
    if(list.style.getPropertyValue('--rows')!==rows)list.style.setProperty('--rows',rows);
    if(removedFocus)list.querySelector('.card-read')?.focus({preventScroll:true});
  }
  function renderMine(g){
    ui.game=g;const p=me(g);$('myDossierSection').style.display=p&&g.phase!=='LOBBY'?'block':'none';$('dashMyEmpty').hidden=Boolean(p&&g.phase!=='LOBBY');if(!p||g.phase==='LOBBY')return;
    if(ui.revealPending&&(p.cards[ui.revealPending]?.revealed||g.phase!=='REVEAL'||!g.reveal_status?.is_current_speaker))ui.revealPending=null;
    $('silenceWarning').style.display=p.is_silenced&&p.is_alive?'block':'none';$('secretPeekAlert').style.display=p.last_peeked&&p.is_alive?'block':'none';if(p.last_peeked)textIfChanged($('secretPeekText'),`${p.last_peeked.target_name||'Игрок'}: ${p.last_peeked.label||p.last_peeked.category} — ${p.last_peeked.value}`);
    $('exileVendettaBox').style.display=g.exile_vendetta?.can_trigger&&!p.is_alive?'block':'none';
    const s=g.reveal_status||{},hint=!p.is_alive?'Вы на поверхности. Открытые досье доступны.':g.phase==='FINAL'?'Партия завершена.':p.is_quarantined?'Изолятор до конца раунда.':g.phase!=='REVEAL'?'Карточки доступны для чтения. Открытие — в отдельном круге перед Речью 1.':s.is_current_speaker?(s.quota_reached?`Открыто ${s.revealed_count} из ${s.required_count}. Можно завершить открытие.`:g.round_number===1&&!p.cards.profession?.revealed?'Ваш ход: сначала откройте профессию.':`Ваш ход: открыто ${s.revealed_count||0} из ${s.required_count||2}.`):`Открывает карточки: ${s.current_speaker_name||'участник'}.`;
    $('dossierTurnStatus').style.display='block';textIfChanged($('dossierTurnStatus'),hint);attrIfChanged($('dossierTurnStatus'),'class',`dossier-turn-banner ${s.is_current_speaker&&g.phase==='REVEAL'?'is-your-turn':''}`);
    const owner=JSON.stringify([g.room_code,p.id]);
    const views=playerCats(p,g).map(cat=>ownCardView(g,p,cat));
    if(same('mine',[owner,views]))return;
    renderOwnCards($('myCardsList'),views,owner);
  }
  function revealCard(cat){const g=state.gameData,p=me(g);if(!p||!p.cards[cat]||p.cards[cat].revealed||revealReason(g,p,cat)||ui.revealPending)return;ui.revealPending=cat;invalidate('mine');renderMine(g);if(!sendAction('REVEAL_CARD',{category:cat})){ui.revealPending=null;invalidate('mine');renderMine(g);}}
  function eligible(g){let list=g.players.filter(p=>p.id!==state.playerId&&p.is_alive&&!p.has_immunity);if(g.phase==='REVOTE')list=list.filter(p=>(g.revote_status?.candidates||[]).includes(p.id));return list;}
  function renderVote(g){
    ui.game=g;const voting=['VOTING','REVOTE'].includes(g.phase),results=g.phase==='VOTE_RESULTS';$('votingSection').style.display=voting?'flex':'none';$('voteResultsSection').style.display=results?'flex':'none';$('dashAction-vote').hidden=!voting&&!results;$('dashAction-turn').hidden=voting||results;
    if(!voting&&!results)return;
    if(results){renderResults(g);return;}
    const p=me(g),can=Boolean(p?.is_alive&&!p?.is_quarantined),list=eligible(g),receipt=g.voting_status?.my_vote;
    if(receipt===ui.votePending){ui.votePending=null;clearTimeout(ui.voteTimeout);}const pending=Boolean(ui.votePending);
    if(ui.voteChoice&&!list.some(p=>p.id===ui.voteChoice))ui.voteChoice=null;
    const accepted=receipt??null;
    $('votingProgressBanner').textContent=`Проголосовали ${g.voting_status?.votes_cast||0} из ${g.voting_status?.total_voters||0}. Выбор других скрыт.`;
    $('thresholdNotice').textContent=g.phase==='REVOTE'?'Голосование между кандидатами на защиту. Решает простое большинство.':`Для решения без защиты требуется ${g.voting_status?.required_votes??'—'} голосов; иначе — защита и переголосование. Затем доступно вето. Не успевший голосует против себя.`;
    if(!same('vote',[list,g.phase,ui.voteChoice,accepted,can,pending,g.skip_round_info?.can_skip])){
      replace($('voteCandidatesGrid'),list.map(c=>`<article class="vote-candidate ${ui.voteChoice===c.id?'is-selected':''} ${accepted===c.id?'is-confirmed':''}" data-candidate="${esc(c.id)}"><button data-select-vote="true" data-focus-key="vote-${esc(c.id)}" class="candidate-select" ${!can||pending?'disabled':''} aria-pressed="${ui.voteChoice===c.id}">${avatar(c)}<strong>${esc(c.name)}</strong><span>${esc(c.cards?.profession?.revealed?c.cards.profession.value:'Профессия скрыта')}</span><small>${accepted===c.id?'Голос принят':ui.voteChoice===c.id?'Выбран кандидат':esc(status(c,g))}</small></button><button class="candidate-details" data-vote-details="true" data-focus-key="vote-details-${esc(c.id)}" aria-label="Досье: ${esc(c.name)}">Досье ${icon('eye')}</button></article>`).join('')||'<p class="dash-empty">Нет доступных кандидатов.</p>');
      const selected=list.find(p=>p.id===ui.voteChoice),acceptedName=accepted==='ABSTAIN'?'Воздержание':accepted==='SKIP_ROUND'?'Пропуск изгнания':g.players.find(p=>p.id===accepted)?.name;
      replace($('dashAction-vote'),`<div class="vote-confirm-box"><span class="eyebrow">ВАШЕ РЕШЕНИЕ</span><p class="vote-receipt" role="status">${!can?(p?.is_quarantined?'Изолятор: голосование недоступно.':'Вы наблюдаете за голосованием.'):pending?'Отправка голоса…':acceptedName?`Голос принят: ${esc(acceptedName)}.`:'Выберите кандидата в центре.'}</p><button class="btn btn-primary" data-confirm-vote="true" ${!selected||!can||pending?'disabled':''}>${selected?`Голосовать против ${esc(selected.name)}`:'Выберите кандидата'}</button></div>${can&&g.phase==='VOTING'?`<div class="vote-alternatives"><button class="btn btn-secondary" data-abstain="true" ${pending?'disabled':''}>Воздержаться</button>${g.skip_round_info?.can_skip?`<button class="btn btn-secondary skip-vote" data-skip-round="true" ${pending?'disabled':''}>Пропустить изгнание</button><p>При большинстве за пропуск — двойное изгнание в следующем раунде.</p>`:''}</div>`:''}`);
    }
  }
  function castVote(target){const g=state.gameData,p=me(g);if(ui.votePending||!g||!['VOTING','REVOTE'].includes(g.phase)||!p?.is_alive||p.is_quarantined)return;if(target==='SKIP_ROUND'&&!g.skip_round_info?.can_skip)return;if(target==='ABSTAIN'&&g.phase!=='VOTING')return;if(!['ABSTAIN','SKIP_ROUND'].includes(target)&&!eligible(g).some(p=>p.id===target))return;ui.votePending=target;ui.pendingVoteContext=`${g.room_code}:${g.round_number}:${g.phase}`;invalidate('vote');renderVote(g);if(!sendAction('CAST_VOTE',{target_id:target})){ui.votePending=null;invalidate('vote');renderVote(g);return;}clearTimeout(ui.voteTimeout);ui.voteTimeout=setTimeout(()=>{if(ui.votePending){ui.votePending=null;invalidate('vote');renderVote(state.gameData);showToast('Подтверждение голоса не получено. Проверьте связь.','warning');}},8000);}
  function voteAck(msg){const g=state.gameData;if(ui.pendingVoteContext!==`${g?.room_code}:${g?.round_number}:${g?.phase}`)return;if(msg.target_id!==ui.votePending)return;ui.votePending=null;clearTimeout(ui.voteTimeout);g.voting_status={...g.voting_status,my_vote:msg.target_id};invalidate('vote');renderVote(g);window.soundFX?.playVoteCast();}
  function renderResults(g){
    const r=g.vote_results||{};$('voteResultsCountdown').textContent=g.timer?.is_paused?'Таймер на паузе':`До следующего этапа: ${g.timer?.seconds_left||0} сек.`;
    if(same('results',[r,state.isHost]))return;
    let text=r.veto_used?'Вето принято. Изгнание отменено.':r.skipped_round?'Изгнание пропущено. В следующем раунде — двойное.':r.threshold_failed?'Нет действительных голосов против кандидатов. Никто не изгнан.':r.eliminated_name?`Кандидат на выход: ${r.eliminated_name}. Окно для вето ещё открыто.`:'Подсчёт завершён. Ожидание следующего этапа.';
    $('voteOutcomeBanner').textContent=text;
    replace($('voteTallyGrid'),(r.detailed_tally||[]).map(t=>`<div class="vote-tally-item"><span class="vote-tally-name">${esc(t.player_name)}</span><strong class="vote-tally-stat">${Number(t.votes)||0} гол.</strong></div>`).join('')+(r.abstain_count?`<div class="vote-tally-item"><span>Воздержались</span><strong>${Number(r.abstain_count)} голосов</strong></div>`:''));
    $('voteResultsHostControls').hidden=!state.isHost;
    replace($('dashAction-vote'),`<div class="vote-confirm-box"><span class="eyebrow">${r.veto_used?'РЕШЕНИЕ ИЗМЕНЕНО':'РЕШЕНИЕ ЕЩЁ НЕ ОКОНЧАТЕЛЬНО'}</span><p>${esc(text)}</p><p class="muted">Спецкарты применяются из вашего досье слева.</p></div>`);
  }
  function renderEvent(g){
    ui.game=g;const st=g.events_state||{},ev=st.active_event,box=$('eventChallengeSection');
    $('hudEventsBadge').textContent=(st.resolved_history||[]).length;box.style.display='flex';
    const unknown=g.information_mode==='uncertainty',modeLabel=unknown?'Неизвестность':'Погружение';
    if(!ev){
      if(same('event',[null,state.isHost,g.events_enabled,g.phase,st.last_resolved,unknown]))return;
      replace(box,`<div class="event-empty"><span class="eyebrow">ИСПЫТАНИЯ · ${modeLabel}</span>${icon('shield')}<h3>${g.events_enabled===false?'Испытания отключены':'Системы под наблюдением'}</h3><p>${g.events_enabled===false?'В этой партии нет кризисов и вылазок.':'Новая авария или вылазка появится здесь.'}</p>${state.isHost&&g.events_enabled!==false&&!['LOBBY','FINAL','PROLOGUE'].includes(g.phase)?'<button class="btn btn-secondary" data-event-action="trigger">Вытянуть испытание</button>':''}<div id="lastEventInline" class="last-event-inline"></div></div>`);
      showInlineResult(st.last_resolved);return;
    }
    const o=st.current_odds,surface=ev.type==='SURFACE_EVENT',skipped=Boolean(st.is_sortie_skipped);
    const vol=g.players.find(p=>p.id===(st.assigned_volunteer_id||st.volunteer_id)&&p.is_alive);
    if(same('event',[ev,o,skipped,g.players.map(p=>[p.id,p.name,p.is_alive]),vol?.id,state.isHost,st.last_resolved,unknown]))return;
    const eventFocus=document.activeElement?.id,scroll=box.querySelector('.event-scroll')?.scrollTop||0;
    const assessment=skipped?'<strong class="event-chance-label">Вылазка отменена</strong><p>Никто не выйдет на поверхность.</p>':unknown?
      '<strong class="event-chance-label">Исход неизвестен</strong><p>Оценка шанса недоступна. Обсудите риски и решите, как действовать.</p>':
      `<strong class="event-chance-label" data-level="${esc(o?.level||'unknown')}">${esc(o?.label||'Недостаточно сведений')}</strong><p>${esc(o?.description||'Сначала определите, кто и как будет действовать.')}</p>`;
    replace(box,`<article class="crisis-card ${surface?'surface':'bunker'}" data-event-id="${esc(ev.id)}"><header class="event-heading"><span class="eyebrow">${surface?'ВЫЛАЗКА НА ПОВЕРХНОСТЬ':'АВАРИЯ В БУНКЕРЕ'}</span><h3>${esc(ev.title)}</h3></header><div class="event-assessment"><span class="event-mode-label">${modeLabel}</span>${assessment}</div>${surface?`<div class="event-executor">${state.isHost?`<label for="selectEventVolunteer">Доброволец</label><select id="selectEventVolunteer" class="form-input" ${skipped?'disabled':''}><option value="" disabled ${!vol?'selected':''}>Назначьте добровольца</option>${g.players.filter(p=>p.is_alive).map(p=>`<option value="${esc(p.id)}" ${p.id===vol?.id?'selected':''}>${esc(p.name)}</option>`).join('')}</select>`:`<span>Доброволец</span><strong>${esc(vol?.name||'Не назначен')}</strong>`}</div>`:''}<div class="event-scroll"><p class="event-description">${esc(ev.description)}</p>${ev.conditions?.length?`<div class="event-conditions"><h4>Условия</h4>${ev.conditions.map(c=>`<p>${esc(c)}</p>`).join('')}</div>`:''}</div><footer id="eventActionControls" class="event-controls">${state.isHost?`<button class="btn btn-primary" data-event-action="resolve">${skipped?'Подтвердить отмену':'Разрешить испытание'}</button><div class="event-secondary">${surface?`<button class="btn btn-secondary btn-small" data-event-action="skip">${skipped?'Возобновить':'Пропустить вылазку'}</button>`:''}<button class="btn btn-secondary btn-small" data-event-action="trigger">Сменить испытание</button></div>`:'<p class="muted">Испытание разрешится после голосования или по команде ведущего.</p>'}<div id="lastEventInline" class="last-event-inline"></div></footer></article>`);
    const scroller=box.querySelector('.event-scroll');if(scroller)scroller.scrollTop=scroll;
    if(eventFocus==='selectEventVolunteer')$('selectEventVolunteer')?.focus({preventScroll:true});showInlineResult(st.last_resolved);
  }
  function showInlineResult(r){
    const el=$('lastEventInline');if(!el||!r)return;
    const signature=JSON.stringify(r);if(el.dataset.resultSignature===signature)return;el.dataset.resultSignature=signature;
    const outcome=r.outcome||window.bunkerResults?.eventOutcome(r)||(r.is_skipped?'Вылазка отменена':r.is_success?'Успех':'Провал');
    el.innerHTML=`<button class="event-result-link" type="button"><span class="last-event-outcome">${esc(outcome)} · посмотреть итог</span><span class="last-event-name">${esc(r.event_title||r.title||'Испытание')}</span><span class="last-event-effect">${esc(r.consequence||'Последствия доступны в результате.')}</span></button>`;
    el.querySelector('button').onclick=()=>showEventResult(r,true);
  }
  function showEventResult(r,explicit=false){
    if(!r)return;showInlineResult(r);
    if(window.bunkerResults){if(explicit)window.bunkerResults.openEvent(r);return;}
    if(!explicit){showToast(`${r.outcome||r.title||'Испытание'}: ${r.description||''}`,r.is_success?'success':r.is_skipped?'info':'warning');return;}
    closeModals();$('diceModalTitle').textContent=r.event_title||'Итог испытания';$('diceTargetDisplay').textContent=r.outcome||'Результат';
    $('diceNumberDisplay').textContent=r.is_skipped?'—':r.is_success?'✓':'×';$('diceNumberDisplay').classList.remove('dice-rolling');
    $('diceOutcomeContainer').style.display='block';$('diceOutcomeTitle').textContent=r.title||'';
    $('diceOutcomeDesc').textContent=[r.description,r.consequence].filter(Boolean).join(' ');$('diceBoostNotice').style.display='none';
    $('btnDiceModalAccept').style.display='inline-flex';$('modalEventDice').style.display='flex';
  }
  function openDossier(player){
    if(!player)return;closeModals();const g=state.gameData||ui.game;$('dossierModalPlayerName').textContent=player.name;$('dossierModalStatus').textContent=status(player,g);$('dossierModalStatus').style.color='var(--text-muted)';const list=$('dossierModalCardsList');const entries=Object.entries(player.cards||{}).filter(([c])=>c!=='traitor'||player.id===state.playerId||g?.phase==='FINAL');list.classList.toggle('single-card',entries.length===1);
    list.innerHTML=entries.map(([cat,c])=>{const k=known(player,c,g);return `<article class="detail-card ${c.revealed?'revealed':k?'private':'locked'}"><div class="detail-label">${icon(cat)}<span>${esc(labels[cat]||c.label||cat)}</span><small>${cat==='special'&&c.used?'Использована':c.revealed?'Открыто всем':g?.phase==='FINAL'?'Рассекречено':k?'Только вам':'Закрыто'}</small></div><h3>${k?esc(c.value):'Скрыто'}</h3>${k&&c.details?`<p class="detail-description">${esc(c.details)}</p>`:''}${cat==='special'&&k&&c.available===false?`<p class="detail-restriction">${esc(c.unavailable_reason||'Сейчас недоступна')}</p>`:''}${!k?'<p class="muted">Участник ещё не открыл эту характеристику.</p>':''}</article>`;}).join('');$('modalPlayerDossier').style.display='flex';
  }
  function picker(title,promptText,choices,onConfirm,confirmLabel='Продолжить'){
    openTargetPickerModal(title,promptText,choices,onConfirm);const list=$('targetPickerList');
    list.querySelectorAll('.modal-candidate-item').forEach((item,i)=>{item.tabIndex=0;item.setAttribute('role','radio');item.setAttribute('aria-checked',String(i===0));item.addEventListener('click',()=>list.querySelectorAll('[role="radio"]').forEach(x=>x.setAttribute('aria-checked',String(x===item))));item.addEventListener('keydown',e=>{if(e.key===' '||e.key==='Enter'){e.preventDefault();item.click();}if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();const items=[...list.children];items[(i+(e.key==='ArrowDown'?1:-1)+items.length)%items.length].focus();}});});list.setAttribute('role','radiogroup');list.setAttribute('aria-label','Выберите вариант');$('btnTargetPickerConfirm').textContent=confirmLabel;
  }
  function textPicker(title, prompt, config, onConfirm){
    picker(title,prompt,[],()=>{});
    const list=$('targetPickerList');list.removeAttribute('role');list.removeAttribute('aria-label');
    const label=make('label','form-label');label.htmlFor='speechOptionInput';label.textContent=config.label;
    const input=make('input','form-input');input.id='speechOptionInput';input.type='text';input.maxLength=config.max_length;input.placeholder=config.placeholder||'';input.autocomplete='off';
    const error=make('p','speech-input-error');error.setAttribute('role','alert');
    list.replaceChildren(label,input,error);
    const old=$('btnTargetPickerConfirm'),button=old.cloneNode(true);old.replaceWith(button);
    button.textContent='Продолжить';
    button.onclick=()=>{
      const value=input.value.trim();
      if(!value){error.textContent='Введите текст.';input.focus();return;}
      if(config.single_word&&!/^[\p{L}]+(?:[-’'][\p{L}]+)*$/u.test(value)){error.textContent='Нужно одно слово без пробелов и цифр.';input.focus();return;}
      closeModals();onConfirm(value);
    };
    input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();button.click();}};
    input.focus();
  }
  function useSpecial(card){
    const g=state.gameData,p=me(g);
    if(!p||!card||card.used||ui.specialPending)return;
    if(card.available===false){showToast(card.unavailable_reason||'Сейчас недоступна','warning');return;}
    const context={room:g.room_code,phase:g.phase,round:g.round_number,turn:g.turn_id,id:card.card_id};ui.actionContext=context;
    const valid=()=>{const now=state.gameData,c=me(now)?.cards.special;return now?.room_code===context.room&&now.phase===context.phase&&now.round_number===context.round&&now.turn_id===context.turn&&c?.card_id===context.id&&!c.used&&c.available!==false;};
    const execute=targetId=>{
      if(!valid())return;
      const target=state.gameData.players.find(x=>x.id===targetId)||p;
      const options=(card.category_options||{})[target.id]||[],selected=[],needed=Math.min(card.selection_count||1,options.length);
      let optionText='';
      const confirm=()=>{
        if(!valid()){showToast('Ход изменился. Выберите действие заново.','warning');return;}
        const describe=selected.map(cat=>labels[cat]||cat).join(', ');
        picker(`Применить: ${card.value}`,`${card.details||''}\n\nЦель: ${target.name}${describe?' · '+describe:''}.${optionText?'\n'+card.input_config.label+': '+optionText:''}`,[{id:'confirm',name:target.name}],()=>{
          if(!valid()){showToast('Состояние изменилось. Выберите действие заново.','warning');return;}
          const fresh=me(state.gameData).cards.special;
          if(card.target==='player'&&fresh.target_ids&&!fresh.target_ids.includes(target.id)){showToast('Цель больше недоступна.','warning');return;}
          const freshOptions=(fresh.category_options||{})[target.id]||[];
          if(selected.some(c=>!freshOptions.includes(c))){showToast('Доступные категории изменились.','warning');return;}
          const payload={expected_turn_id:context.turn};
          if(card.target==='player')payload.target_player_id=target.id;
          if(selected.length)payload.categories=selected;
          if(card.input_config)payload.option_text=optionText;
          ui.specialPending=true;invalidate('mine');renderMine(state.gameData);
          if(!sendAction('USE_SPECIAL_CARD',payload)){specialAck();}
          else {clearTimeout(ui.specialTimeout);ui.specialTimeout=setTimeout(()=>{if(ui.specialPending){specialAck();showToast('Нет подтверждения спецкарты. Проверьте связь.','warning');}},8000);}
        },'Применить карту');
      };
      const configure=()=>card.input_config?textPicker(card.value,`Ограничение для ${target.name}.`,card.input_config,value=>{optionText=value;confirm();}):confirm();
      const next=()=>{
        if(!valid())return;
        const current=state.gameData.players.find(x=>x.id===target.id)||target;
        picker(`Спецкарта: ${card.value}`,`Выберите характеристику ${selected.length+1} из ${needed}. Скрытое содержимое соперника не показывается.`,options.filter(c=>!selected.includes(c)).map(cat=>{const c=current.cards[cat];return {id:cat,name:`${labels[cat]||cat}${known(current,c,state.gameData)?': '+c.value:' — скрыто'}`};}),cat=>{selected.push(cat);if(selected.length<needed)next();else configure();});
      };
      if(card.choose_category&&needed)next();else configure();
    };
    if(card.target==='player'){
      const candidates=g.players.filter(x=>x.is_alive&&(card.target_ids?card.target_ids.includes(x.id):(x.id!==p.id||card.allow_self)));
      if(!candidates.length){showToast('Нет допустимой цели.','warning');return;}
      picker(`Спецкарта: ${card.value}`,'Выберите участника.',candidates,execute);
    }else execute(p.id);
  }
  function promptAck(){
    clearTimeout(ui.promptTimeout);ui.promptPending=null;invalidate('speechEffects');
    if(state.gameData)renderSpeechEffects(state.gameData);
  }
  function renderSpeechEffects(g){
    const panel=$('speechEffectsPanel'),effects=g.speech_effects||[];
    panel.hidden=!effects.length||['LOBBY','PROLOGUE','FINAL'].includes(g.phase);
    if(panel.hidden)return;
    if(same('speechEffects',[effects,state.playerId,ui.promptPending]))return;
    const render=e=>`<article class="speech-effect ${e.active?'is-active':''}" data-effect-id="${esc(e.id)}"><div class="speech-effect-title"><strong>${esc(e.title)}</strong><span>${e.active?'Сейчас':'На ближайшую речь'} · ${esc(e.target_name)}</span></div><p>${esc(e.instruction)}</p>${e.card_id==='speech_prompter'?`<p class="speech-prompt-count">Слова от ${esc(e.author_name)}: ${e.prompts.length} / 3</p><ol class="speech-prompt-list">${e.prompts.map(word=>`<li>${esc(word)}</li>`).join('')}</ol>`:''}${e.can_prompt?`<form class="speech-prompt-form" data-effect-id="${esc(e.id)}"><label for="prompt-${esc(e.id)}">Следующее слово</label><div><input id="prompt-${esc(e.id)}" class="form-input" maxlength="32" autocomplete="off" placeholder="Например, кабачок" ${ui.promptPending?'disabled':''}><button class="btn btn-primary btn-small" ${ui.promptPending?'disabled':''}>${ui.promptPending?'Отправка…':'Подбросить слово'}</button></div></form>`:''}</article>`;
    const active=effects.filter(e=>e.active),pending=effects.filter(e=>!e.active);
    panel.innerHTML=active.map(render).join('')+(pending.length?`<details class="speech-pending"><summary>Ожидают выступления: ${pending.length}</summary>${pending.map(render).join('')}</details>`:'');
    panel.querySelectorAll('.speech-prompt-form').forEach(form=>form.onsubmit=event=>{
      event.preventDefault();if(ui.promptPending)return;
      const current=(state.gameData.speech_effects||[]).find(e=>e.id===form.dataset.effectId);
      if(!current?.can_prompt){showToast('Эта речь уже закончилась или стоит на паузе.','warning');return;}
      const input=form.querySelector('input'),word=input.value.trim();
      if(!/^[\p{L}]+(?:[-’'][\p{L}]+)*$/u.test(word)){showToast('Введите одно слово без пробелов и цифр.','warning');input.focus();return;}
      ui.promptPending=current.id;invalidate('speechEffects');renderSpeechEffects(state.gameData);
      if(!sendAction('SPEECH_PROMPT',{target_id:current.target_id,effect_id:current.id,index:current.prompts.length,word})){promptAck();return;}
      ui.promptTimeout=setTimeout(()=>{if(ui.promptPending){promptAck();showToast('Нет подтверждения подсказки. Проверьте связь.','warning');}},8000);
    });
  }
  function specialAck(){clearTimeout(ui.specialTimeout);ui.specialPending=false;invalidate('mine');if(state.gameData)renderMine(state.gameData);}
  function actionError(){promptAck();ui.votePending=null;ui.revealPending=null;clearTimeout(ui.voteTimeout);specialAck();invalidate('vote','mine','event');if(state.gameData){renderVote(state.gameData);renderMine(state.gameData);renderEvent(state.gameData);}}
  function disconnected(){clearTimeout(ui.promptTimeout);ui.promptPending=null;window.soundFX?.setScene({connected:false,prologue:false});$('prologueVideoBg')?.pause();window.bunkerResults?.disconnected();ui.votePending=null;ui.revealPending=null;ui.specialPending=false;clearTimeout(ui.voteTimeout);clearTimeout(ui.specialTimeout);invalidate('mine','vote');}
  function renderAgeCare(ev){
    let box=$('finalAgeCare');
    if(!ev.care_note){box?.remove();return;}
    if(!box){box=make('section','final-age-care');box.id='finalAgeCare';$('finalKeyReasons').insertAdjacentElement('afterend',box);}
    box.innerHTML=`<header><h3>Забота о команде</h3></header><p>${esc(ev.care_note)}</p><p class="muted">Возраст и здоровье учитываются вместе с помощью команды. Это игровая модель, не медицинский прогноз.</p>`;
  }
  function renderFinal(g){
    const el=$('finalScreenSection'),ev=g.final_evaluation;el.style.display=g.phase==='FINAL'&&ev?'block':'none';if(g.phase!=='FINAL'||!ev){$('finalAgeCare')?.remove();return;}if(same('final',[ev,g.players]))return;
    $('finalTitle').textContent=ev.title||'Итоги партии';$('finalVaultDoorStatus').textContent=ev.is_success?'Убежище выдержало. Колония сохраняет устойчивость.':'Команда не закрыла потребности убежища.';
    $('survivalGauge').textContent=ev.is_success?'✓':'×';$('survivalGauge').className=`final-rating ${ev.is_success?'success':'fail'}`;$('finalText').textContent=ev.text||'';$('finalFullText').textContent=ev.text||'';const p=me(g);$('finalPersonalResult').textContent=p?(p.is_alive?'Вы остались в бункере.':'Вы оказались на поверхности.'):'Вы наблюдали за этой партией.';
    const needs=Object.entries(ev.breakdown?.needs||{});$('finalNeeds').innerHTML=needs.map(([key,n],i)=>`<div class="balance-need narrative-need" data-tier="${esc(n.tier||'limited')}">${icon(['air','food','health','shield','people'][i])}<span>${esc(n.label)}</span><strong>${esc(n.status||'Не определено')}</strong></div>`).join('');
    const draw=p=>`<button class="final-player" data-player="${esc(p.id)}">${avatar(p)}<span><strong>${esc(p.name)}</strong><small>${esc(p.cards?.profession?.value||'Досье')}</small></span></button>`;
    $('finalSurvivors').innerHTML=g.players.filter(p=>p.is_alive).map(draw).join('')||'<p>Никто не остался.</p>';$('finalExiles').innerHTML=g.players.filter(p=>!p.is_alive).map(draw).join('')||'<p>Никто не изгнан.</p>';
    $('finalProsList').innerHTML=(ev.pros||[]).map(p=>`<li>${esc(p)}</li>`).join('');$('finalConsList').innerHTML=(ev.cons||[]).map(p=>`<li>${esc(p)}</li>`).join('');
    const reasons=[...(ev.cons||[]).slice(0,1),...(ev.pros||[]).slice(0,1)];$('finalKeyReasons').innerHTML=reasons.map(r=>`<p>${esc(r)}</p>`).join('');
    renderAgeCare(ev);
    $('finalAchievementsContainer').hidden=true;
    $('finalAchievementsList').innerHTML=(ev.achievements||[]).map(a=>`<article class="achievement-card"><span class="achievement-badge">${esc(a.badge||'✓')}</span><div><strong>${esc(a.title)}</strong><p>${esc(a.player_name||'')}</p><small>${esc(a.desc||'')}</small></div></article>`).join('')||'<p class="muted">Особых заслуг в этой партии нет.</p>';
  }
  function clipAllowed(){return effectiveMotion()==='full'&&window.soundFX?.settings.clips!==false;}
  function refreshClipControls(){
    const v=$('prologueVideoBg'),sound=$('btnPrologueSound'),fx=window.soundFX;
    if(!v||!sound)return;
    if(!clipAllowed()&&!v.paused)v.pause();
    const playingSound=!!(fx?.consent&&fx.enabled&&fx.settings.videoEnabled&&fx.settings.video>0&&fx.volume>0);
    sound.textContent=playingSound?'Звук видео: вкл.':'Звук видео: выкл.';
    sound.setAttribute('aria-pressed',String(playingSound));
    sound.title=fx&&!fx.enabled?'Общий звук выключен. Включите его в «Звук и видео».':'Громкость видео настраивается отдельно; общее отключение имеет приоритет.';
    sound.disabled=!clipAllowed();
    if($('btnPrologueReplay')){$('btnPrologueReplay').disabled=!clipAllowed();$('btnPrologueReplay').textContent=clipAllowed()?'Повторить 5 секунд':'Видео отключено';}
  }
  window.addEventListener('bunker-audio-change',refreshClipControls);
  function prologue(g){
    if(g.phase!=='PROLOGUE'||!g.catastrophe)return;
    const modal=$('cinematicPrologueModal'),v=$('prologueVideoBg'),key=`bunker_prologue_${g.room_code}_${state.playerId}`;
    if(storageGet(key,true)==='entered'){if(g.is_registered)sendAction('ENTER_BUNKER');return;}
    $('prologueCatastropheTitle').textContent=g.catastrophe.title;
    $('prologueCatastropheDesc').textContent=`${g.catastrophe.description} ${g.catastrophe.hazard||''} Срок изоляции: ${g.catastrophe.duration_years} лет.`;
    $('prologueCapacityNotice').textContent=`${g.bunker_capacity} мест на ${g.total_players} участников.`;
    $('prologueHeroesGrid').innerHTML=g.players.map(p=>`<div class="prologue-hero-card">${avatar(p)}<span>${esc(p.name)}</span></div>`).join('');
    const id=g.catastrophe.id;
    const valid=!!id&&/^[a-z0-9_]+$/.test(id);
    v.loop=false;v.onplaying=()=>window.soundFX?.setScene({prologue:true});
    v.onpause=v.onended=()=>window.soundFX?.setScene({prologue:false});
    v.onerror=()=>{window.soundFX?.setScene({prologue:false});v.pause();v.removeAttribute('src');v.load();};
    window.soundFX?.attachMedia(v);
    if(valid)v.poster=`/static/images/catastrophes/${id}.jpg?v=4.6.0`;
    const replay=()=>{
      if(!valid||!clipAllowed()||document.hidden)return;
      if(!v.getAttribute('src'))v.src=`/static/videos/catastrophes/${id}.mp4?v=4.6.0`;
      v.currentTime=0;window.soundFX?.attachMedia(v);v.play().catch(()=>window.soundFX?.setScene({prologue:false}));
    };
    $('btnPrologueSound').onclick=()=>{
      const fx=window.soundFX;if(!fx)return;
      if(!fx.consent){fx.chooseSound(true);fx.setSetting('videoEnabled',true);}
      else if(!fx.enabled){window.bunkerAudioSettings?.open();return;}
      else {fx.unlock();fx.setSetting('videoEnabled',!fx.settings.videoEnabled);}
      refreshClipControls();
    };
    if($('btnPrologueReplay'))$('btnPrologueReplay').onclick=replay;
    if($('btnPrologueAudioSettings'))$('btnPrologueAudioSettings').onclick=()=>window.bunkerAudioSettings?.open();
    const close=()=>{
      modal.style.display='none';v.pause();resumeClipOnVisible=false;
      window.soundFX?.setScene({prologue:false});storageSet(key,'entered',true);
      if(state.gameData?.phase==='PROLOGUE'&&state.gameData.is_registered)sendAction('ENTER_BUNKER');
    };
    $('btnPrologueEnter').onclick=close;$('btnPrologueClose').onclick=close;
    modal.style.display='flex';refreshClipControls();
    if(valid&&clipAllowed()){v.src=`/static/videos/catastrophes/${id}.mp4?v=4.6.0`;replay();}
    else {v.pause();v.removeAttribute('src');v.load();window.soundFX?.setScene({prologue:false});}
  }
  function initDialogs(){
    let current=null,returnFocus=null;const overlays=()=>[...document.querySelectorAll('.modal-overlay,.cinematic-prologue-overlay')];
    const controls=m=>[...m.querySelectorAll('button,input,select,textarea,a[href],[tabindex="0"],summary')].filter(e=>!e.disabled&&e.getClientRects().length&&!e.closest('[hidden]'));
    const observer=new MutationObserver(()=>{const active=overlays().filter(m=>m.style.display!=='none'&&m.getClientRects().length).at(-1)||null;if(active===current)return;if(active){if(!current)returnFocus=document.activeElement;current=active;active.setAttribute('role','dialog');active.setAttribute('aria-modal','true');let title=active.querySelector('.modal-title,.prologue-title');if(title){if(!title.id)title.id='dialog-title-'+active.id;active.setAttribute('aria-labelledby',title.id);}const background=[$('viewWelcome'),$('viewGame'),document.querySelector('.hud-header')];background.forEach(e=>{e.inert=true;});requestAnimationFrame(()=>controls(active)[0]?.focus());}else{current=null;[$('viewWelcome'),$('viewGame'),document.querySelector('.hud-header')].forEach(e=>{e.inert=false;});if(returnFocus?.isConnected&&returnFocus.getClientRects().length)returnFocus.focus({preventScroll:true});else $('dashMenuButton').focus({preventScroll:true});returnFocus=null;}});
    overlays().forEach(m=>{observer.observe(m,{attributes:true,attributeFilter:['style']});m.addEventListener('click',e=>{if(e.target===m){if(m.id==='cinematicPrologueModal')$('btnPrologueClose').click();else closeModals();}});});
    document.addEventListener('keydown',e=>{if(!current||$('audioSettingsDialog')?.open)return;if(e.key==='Escape'){e.preventDefault();if(current.id==='cinematicPrologueModal')$('btnPrologueClose').click();else closeModals();return;}if(e.key!=='Tab')return;const list=controls(current),first=list[0],last=list.at(-1);if(!list.length){e.preventDefault();return;}if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}});
  }
  function update(g){
    window.soundFX?.setScene({phase:g.phase,catastrophe:g.catastrophe?.id||'',review:!!g.result_review,connected:true});
    ui.game=g;if(ui.room!==g.room_code){ui.room=g.room_code;ui.phase=null;ui.follow=true;ui.focusId=null;ui.view='focus';ui.lastSpeaker=null;ui.voteChoice=null;ui.votePending=null;ui.signatures={};}
    if(['LOBBY','FINAL'].includes(ui.phase)&&g.phase!==ui.phase){ui.follow=true;ui.focusId=null;ui.view='focus';ui.lastSpeaker=null;invalidate('players','roster');}
    const lobby=g.phase==='LOBBY',final=g.phase==='FINAL',voting=['VOTING','REVOTE','VOTE_RESULTS'].includes(g.phase),active=speaker(g);
    document.body.classList.add('dashboard-active');document.body.classList.toggle('dashboard-lobby',lobby);document.body.classList.toggle('dashboard-final',final);document.body.dataset.phase=g.phase;
    $('dashLobby').hidden=!lobby;$('lobbyGuestWait').hidden=state.isHost||!g.is_registered;const join=$('spectatorJoinBanner');if(lobby&&join.parentElement!==$('lobbySettingsSlot'))$('lobbySettingsSlot').appendChild(join);else if(!lobby&&join.parentElement!==$('dashAction-turn'))$('dashAction-turn').appendChild(join);$('dashRoster').hidden=lobby||final;$('dashWorkspace').hidden=final;$('dashTop').hidden=final;$('dashMobileNav').hidden=lobby||final;
    $('dashHostMenu').hidden=!state.isHost||lobby;$('dashBunkerButton').hidden=lobby;$('dashLogButton').hidden=lobby;$('dashMenuButton').hidden=false;
    $('dashPlayerControls').hidden=lobby||voting;$('allPlayersGrid').hidden=voting;
    if(ui.phase!==g.phase){if(ui.phase!==null)closeModals();ui.phase=g.phase;ui.voteChoice=null;ui.votePending=null;ui.revealPending=null;clearTimeout(ui.voteTimeout);ui.actionContext=null;invalidate('mine','vote','event');$('dashLive').textContent=phases[g.phase]||g.phase;if(voting)showMobile('players');else if(g.phase==='REVEAL'&&g.reveal_status?.is_current_speaker)showMobile('mine');else if(g.phase!=='PROLOGUE')showMobile('players');}
    if(g.phase!=='PROLOGUE'&&$('cinematicPrologueModal').style.display!=='none'){$('cinematicPrologueModal').style.display='none';$('prologueVideoBg').pause();window.soundFX?.setScene({prologue:false});}
    syncPlayerFocus(g);
    if(ui.lastSpeaker!==active){if(active&&g.phase==='REVEAL'&&g.reveal_status?.is_current_speaker)showMobile('mine');ui.lastSpeaker=active;}
    const steps=[['REVEAL','Открытие'],['SPEECH','Речь 1'],['ACCUSATION','Речь 2'],['VOTING','Голосование'],['JUSTIFICATION','Защита'],['REVOTE','Переголосование'],['VOTE_RESULTS','Вето'],['LAST_WORD','Последнее слово']];
    if(!same('track',[g.phase,g.round_number])){$('dashPhaseTrack').innerHTML=`<span class="dash-round">${lobby?'Сбор':g.phase==='PROLOGUE'?'Вступление':`Раунд ${g.round_number||1}`}</span>`+steps.map(([id,label])=>`<span class="dash-step ${id===g.phase||(id==='ACCUSATION'&&g.phase==='DEBATE')?'current':''}">${label}</span>`).join('');}
    const pause=g.timer?.is_paused;$('timerBox').classList.toggle('is-paused',Boolean(pause));$('timerBox').querySelector('.svg-timer-sub').textContent=pause?'ПАУЗА':'ОСТАЛОСЬ';$('phaseTitle').textContent=g.phase_context?.title||phases[g.phase]||$('phaseTitle').textContent;
    const name=g.players.find(p=>p.id===active)?.name;$('phaseDesc').textContent=name?`${name}${g.round_direction==='reverse'?' · обратный порядок':''}`:voting?'Выбор других игроков скрыт до результата':lobby?'Пригласите друзей по ссылке комнаты.':g.phase==='PROLOGUE'?'Ознакомьтесь со сценарием.':$('phaseDesc').textContent;
    if(g.phase_context&&!['LOBBY','PROLOGUE','FINAL'].includes(g.phase)){$('phaseDesc').textContent=[g.phase_context.speaker_name,g.phase_context.next_label?'Далее: '+g.phase_context.next_label:''].filter(Boolean).join(' · ');}
    $('lobbyPopulation').textContent=`Участников: ${g.total_players} · Мест: ${g.bunker_capacity}`;
    $('dashAction-turn').hidden=voting;let help=lobby?'':g.phase==='PROLOGUE'?'Ожидание входа участников в бункер.':g.phase==='REVEAL'?(g.reveal_status?.is_current_speaker?'Ваши 60 секунд на открытие. Раскройте положенные карточки слева. После всего круга начнётся Речь 1.':'Каждый по очереди открывает карточки за 60 секунд. Речь 1 начнётся, когда закончат все.') : g.phase==='SPEECH'?(g.speech_status?.is_current_speaker?'Теперь ваша Речь 1. Объясните свою пользу по открытым карточкам; раскрытие уже завершено.':'Слушайте Речь 1. Карточки уже открыты; досье всех участников доступны для просмотра.'):(phases[g.phase]||'Ожидание следующего этапа.');$('dashTurnHelp').textContent=['JUSTIFICATION','REVOTE','VOTING','VOTE_RESULTS','LAST_WORD'].includes(g.phase)&&g.phase_context?g.phase_context.instruction:help;
    const spk=$('speakerProgress');if(spk&&active){const turn=['REVEAL','SPEECH'].includes(g.phase)?g.current_speaker:g.accusation_speaker;const count=turn?` · ${turn.index+1} из ${turn.total}`:'';spk.textContent=(g.phase==='REVEAL'?'ОТКРЫТИЕ':g.phase==='SPEECH'?'РЕЧЬ 1':g.phase==='ACCUSATION'?'РЕЧЬ 2':'СЛОВО УЧАСТНИКУ')+count;}
    renderSpeechEffects(g);renderPlayers(g);renderRoster(g);renderMine(g);renderVote(g);renderEvent(g);renderFinal(g);window.bunkerLobby?.render(g);window.bunkerResults?.render(g);
  }
  function reset(){window.bunkerResults?.reset();window.bunkerLobby?.reset();disconnected();ui.game=null;ui.room=null;ui.phase=null;ui.signatures={};ui.focusId=null;ui.follow=true;ui.view='focus';ui.lastSpeaker=null;document.body.classList.remove('dashboard-active','dashboard-lobby','dashboard-final');delete document.body.dataset.phase;$('dashLobby').hidden=true;$('cinematicPrologueModal').style.display='none';$('prologueVideoBg').pause();$('dashBunkerButton').hidden=true;$('dashLogButton').hidden=true;closeModals();window.soundFX?.setScene({phase:'WELCOME',catastrophe:'',review:false,prologue:false,connected:true});}
  window.bunkerDashboard={update,renderPlayers,renderMine,renderVote,renderEvent,renderFinal,openDossier,useSpecial,prologue,showEventResult,voteAck,specialAck,promptAck,actionError,disconnected,reset,pageVotes(){},openUtility};
  setup();$('dashBunkerButton').hidden=true;$('dashLogButton').hidden=true;
})();
