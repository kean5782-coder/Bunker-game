/** Lobby V2. Room state is authoritative; drafts are never silently used at start. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = v => escapeHtml(String(v ?? ''));
  const ui = {game:null, catalog:null, loading:false, pending:null, pendingTimer:null,
    queued:{}, tab:'general', room:null, lastRevision:null, rosterSig:null, online:false};
  const labels = {classic:'Классика',blitz:'Блиц',discussion:'Без спешки',first_game:'Первая партия',custom:'Свои правила'};
  const presetDescriptions = {classic:'60 / 30 сек · полный рандом',blitz:'30 / 15 сек · мало мест',discussion:'90 / 45 сек · больше слова',first_game:'Без испытаний и спецкарт'};
  const paths = {
    door:'M4 3h13v18H4V3m3 0 13 4v14l-13-3V3m9 8v3',
    people:'M9 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6m7 1a3 3 0 0 1 0 6M2 21v-5a5 5 0 0 1 10 0v5m4 0v-5a5 5 0 0 0-1-3',
    check:'m4 12 5 5L20 6',settings:'M4 6h16M4 12h16M4 18h16M8 3v6m8 0v6M9 15v6',
    clock:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18m0 4v6l4 2',
    shield:'M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6l-9-4',
    bolt:'m13 2-9 12h7l-1 8 10-13h-8l1-7',
    eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12m10-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
    copy:'M8 8h12v13H8V8m-3 8H3V3h12v2',plus:'M12 4v16M4 12h16',
    bot:'M5 6h14v14H5V6m7 0V2M2 10v6m20-6v6M8 11h1m6 0h1m-7 5h6',
    lock:'M6 10h12v11H6V10m3 0V6a3 3 0 0 1 6 0v4m-3 4v3',
    arrow:'M4 12h15m-6-6 6 6-6 6',save:'M3 3h15l3 3v15H3V3m4 0v7h10V3M7 21v-7h10v7',
    shuffle:'M3 5h4l10 14h4m-4-4 4 4-4 3M3 19h4l10-14h4m-4-3 4 3-4 4',
    radio:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8m-8-4a11 11 0 0 0 0 16m16-16a11 11 0 0 1 0 16'
  };
  const icon = name => `<svg class="lc-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name]||paths.settings}"/></svg>`;
  const choice = (key,label,options,note='') => `<label class="lc-field" for="lc-${key}"><span>${label}</span><select id="lc-${key}" data-lobby-key="${key}">${options.map(([v,t])=>`<option value="${v}">${t}</option>`).join('')}</select>${note?`<small>${note}</small>`:''}</label>`;
  const number = (key,label,min,max,note='',step=1) => `<label class="lc-field" for="lc-${key}"><span>${label}</span><div class="lc-number"><input id="lc-${key}" data-lobby-key="${key}" type="number" min="${min}" max="${max}" step="${step}" inputmode="numeric"><span>${key==='capacity'?'мест':'сек'}</span></div>${note?`<small>${note}</small>`:''}</label>`;
  const toggle = (key,title,note,ico='shield') => `<label class="lc-toggle" for="lc-${key}"><span class="lc-toggle-icon">${icon(ico)}</span><span class="lc-toggle-copy"><strong>${title}</strong><small>${note}</small></span><input id="lc-${key}" type="checkbox" data-lobby-key="${key}"><span class="lc-switch" aria-hidden="true"></span></label>`;
  const capMode = [['auto','Автоматически'],['manual','Задать вручную']];
  function setup(){
    const root=document.createElement('section');root.id='lobbyControlRoom';root.className='lc-root';root.hidden=true;
    root.setAttribute('aria-label','Подготовка партии');
    root.innerHTML=`
      <header class="lc-heading"><div><span class="lc-kicker"><i></i> КОМАНДНЫЙ ПУНКТ / ПОДГОТОВКА</span><h1>Соберите тех, <em>кто останется.</em></h1></div><div class="lc-sync" id="lcSync" role="status">Ожидание сервера</div></header>
      <nav class="lc-mobile-nav" aria-label="Разделы лобби"><button data-lc-mobile="settings" aria-pressed="true">Настройки</button><button data-lc-mobile="crew">Участники</button><button data-lc-mobile="brief">Сценарий</button></nav>
      <div class="lc-layout" id="lcLayout" data-mobile="settings">
      <aside class="lc-crew lc-surface" aria-labelledby="lcCrewHeading">
        <div class="lc-invite"><span class="lc-eyebrow">КОД ВАШЕЙ КОМНАТЫ</span><div class="lc-code-line"><strong id="lcRoomCode">----</strong><button id="lcCopyCode" class="lc-icon-button" title="Скопировать код" aria-label="Скопировать код">${icon('copy')}</button><span id="lcLockBadge">Вход открыт</span></div><button id="lcCopyLink" class="lc-button lc-button-quiet">${icon('radio')} Пригласить друзей</button></div>
        <div class="lc-crew-heading"><h2 id="lcCrewHeading">Экипаж</h2><span id="lcCrewCount">0 / 20</span></div>
        <div class="lc-roster" id="lcRoster" aria-label="Список участников"></div>
        <div class="lc-ready-panel"><div id="lcSpectatorSlot"></div><button id="lcReady" class="lc-button lc-button-ready">${icon('check')} Я готов</button><p id="lcReadyHelp">Готовность подтверждается сервером.</p></div>
        <div class="lc-bot-panel" id="lcBots"><div class="lc-bot-title">${icon('bot')}<strong>Добавить ботов</strong><span id="lcBotCount">0</span></div><div class="lc-bot-controls"><label class="sr-only" for="lcBotNumber">Количество ботов</label><input id="lcBotNumber" type="number" min="1" max="19" value="5"><button id="lcAddBots" class="lc-button">${icon('plus')} Добавить</button></div><div class="lc-bot-links"><button id="lcFillBots">До 6 участников</button><button id="lcRemoveBots">Убрать ботов</button></div></div>
      </aside>
      <section class="lc-settings lc-surface" aria-label="Настройки партии">
        <div class="lc-presets" role="group" aria-label="Готовые наборы правил">${['classic','blitz','discussion','first_game'].map((key,i)=>`<button type="button" data-preset="${key}" aria-pressed="false"><span class="lc-preset-number">0${i+1}</span><strong>${labels[key]}</strong><small>${presetDescriptions[key]}</small></button>`).join('')}</div>
        <div class="lc-settings-header"><nav class="lc-tabs" role="tablist" aria-label="Категории настроек">${[['general','Основное'],['scenario','Мир и сценарий'],['rules','Правила и время']].map(([k,t])=>`<button id="lc-tab-${k}" data-tab="${k}" role="tab" aria-controls="lc-pane-${k}" aria-selected="${k==='general'}" tabindex="${k==='general'?0:-1}">${t}</button>`).join('')}</nav><span class="lc-profile-label" id="lcProfileLabel">Классика</span></div>
        <p class="lc-guest-note" id="lcGuestNote" hidden>Вы видите общие настройки. Менять их может ведущий.</p>
        <div class="lc-settings-scroll" id="lcSettingsScroll">
        <section id="lc-pane-general" role="tabpanel" aria-labelledby="lc-tab-general">
          <div class="lc-section-heading"><span>01 / СОСТАВ И ИНФОРМАЦИЯ</span><p id="lcDealHelp" aria-live="polite"></p></div>
          <div class="lc-fields lc-fields-five">${choice('deal_mode','Раздача карточек',[['full_random','Полный рандом'],['balanced','С подстраховкой']])}${choice('max_players','Лимит участников',Array.from({length:18},(_,i)=>[i+3,`${i+3} человек`]))}${choice('capacity_mode','Мест в бункере',capMode)}${number('capacity','Вместимость',1,19)}${choice('information_mode','Информация',[['immersion','Погружение'],['uncertainty','Неизвестность']])}</div>
          <div class="lc-capacity-note" id="lcCapacityNote"></div>
          <div class="lc-section-heading lc-section-spaced"><span>02 / МЕХАНИКИ ПАРТИИ</span></div>
          <div class="lc-toggles">${toggle('enable_events','Испытания и вылазки','Аварии, опасные вылазки и решения команды','bolt')}${toggle('enable_traitor','Тайный предатель','Одна скрытая миссия саботажа','eye')}${toggle('enable_special_cards','Спецкарты','Обмены, спасение и особые действия','shuffle')}${toggle('require_ready','Готовность всех','Старт после подтверждения участников','check')}</div>
          <p class="lc-inline-note">После изменения настроек или состава готовность сбрасывается. Ведущий подтверждает её запуском.</p>
        </section>
        <section id="lc-pane-scenario" role="tabpanel" aria-labelledby="lc-tab-scenario" hidden>
          <div class="lc-section-heading"><span>01 / МИР ЗА ГЕРМОШЛЮЗОМ</span><p>Случайный выбор происходит на сервере при старте.</p></div>
          <div class="lc-fields">${choice('catastrophe_id','Катастрофа',[['random','Случайная из 25']])}${choice('bunker_id','Убежище',[['random','Случайное из 20']])}</div>
          <details class="lc-world-details"><summary>Описание катастрофы и оснащение убежища <span>Подробнее</span></summary><div class="lc-world-description" id="lcWorldDescription"></div></details>
          <div class="lc-fields lc-section-spaced">${choice('event_difficulty','Сложность испытаний',[['easy','Мягкая'],['normal','Обычная'],['hard','Суровая']],'Общая сложность испытаний. Точные расчёты не показываются.')}${choice('game_mode','Режим вместимости',[['STANDARD','Стандарт · половина состава'],['METEORITE','Метеорит · 1–2 места']],'Влияет на автоматическую вместимость и раскрытие «По режиму».')}</div>
          ${toggle('show_prologue','Кинематографическое вступление','Знакомство с катастрофой перед кругом открытия карточек','door')}
        </section>
        <section id="lc-pane-rules" role="tabpanel" aria-labelledby="lc-tab-rules" hidden>
          <div class="lc-section-heading"><span>01 / ТЕМП ПАРТИИ</span><p id="lcRevealTiming"><strong>Открытие: 60 сек каждому</strong> → Речь 1 → Речь 2. Общих дебатов нет.</p></div>
          <div class="lc-fields lc-fields-three">${number('speech_duration','Первая речь',30,180,'Шаг 2 секунды',2)}<div class="lc-field"><span>Вторая речь</span><output id="lcSecondSpeech" class="lc-readout">30 <small>сек</small></output><small>Автоматически ½ первой</small></div>${number('voting_duration','Голосование',10,120)}${number('justification_duration','Защита кандидата',15,120)}${number('revote_duration','Переголосование',10,90)}${number('last_word_duration','Последнее слово',10,90)}</div>
          <div class="lc-section-heading lc-section-spaced"><span>02 / ПОРЯДОК И ИНФОРМАЦИЯ</span></div>
          <p class="lc-inline-note" id="lcInformationHelp" aria-live="polite"></p>
          <div class="lc-fields">${choice('initial_reveal','Что открыто при старте',[['mode','По режиму игры'],['closed','Все характеристики скрыты'],['profession','Профессия'],['profession_health','Профессия и здоровье']])}${choice('speaker_order','Очередность участников',[['join','В порядке подключения'],['random','Перемешать перед раздачей']],'В чётных раундах порядок разворачивается.')}</div>
          <p class="lc-inline-note">Закрытые характеристики не показываются другим игрокам. Нормы раскрытия и тайное голосование сохранены.</p>
        </section>
        </div>
        <div class="lc-profile-tools"><span>${icon('save')} Профиль</span><button id="lcSaveProfile" title="Скачать общие настройки в JSON без имён и ключей">Сохранить</button><button id="lcLoadProfile">Загрузить</button><button id="lcResetProfile">Сбросить</button><input id="lcProfileFile" type="file" accept=".json,application/json" hidden><span id="lcRevision" class="lc-revision">v1</span></div>
      </section>
      <aside class="lc-brief lc-surface" aria-label="Сводка партии">
        <div class="lc-scene" id="lcScene"><div class="lc-scene-grid" aria-hidden="true"></div><span class="lc-scene-marker">ОБЪЕКТ / ЗАСЕКРЕЧЕНО</span><span class="lc-scene-icon" aria-hidden="true">${icon('door')}</span><div class="lc-scene-caption"><span class="lc-eyebrow">ЗА ПРЕДЕЛАМИ БУНКЕРА</span><h2 id="lcSceneTitle">Неизвестная угроза</h2><p id="lcSceneSubtitle">Случайный сценарий при старте</p></div></div>
        <div class="lc-brief-scroll"><div class="lc-bunker-brief"><span class="lc-eyebrow">ВАШЕ УБЕЖИЩЕ</span><strong id="lcBunkerTitle">Случайный объект</strong><p id="lcBunkerDetails">Характеристики определятся при старте.</p></div>
        <div class="lc-seat-stat"><div><strong id="lcSeats">—</strong><span>мест внутри</span></div><div><strong id="lcOutside">—</strong><span>останутся снаружи</span></div></div><div id="lcSeatDots" class="lc-seat-dots" aria-hidden="true"></div>
        <div class="lc-brief-rules" id="lcBriefRules"></div><p class="lc-fairness">Возраст и здоровье могут увеличить потребность в помощи; поддержка команды важна. Карты и роли пока скрыты.</p></div>
      </aside>
      </div>
      <footer class="lc-footer"><div class="lc-launch-state"><span class="lc-launch-lamp" id="lcLaunchLamp"></span><div><strong id="lcLaunchTitle">Проверка шлюза</strong><p id="lcLaunchMessage">Добавьте участников и выберите настройки.</p></div></div><button id="lcLockRoom" class="lc-button lc-button-quiet">${icon('lock')} Закрыть вход</button><button id="lcStart" class="lc-button lc-launch">Закрыть шлюз и начать ${icon('arrow')}</button></footer>
      <div class="lc-message" id="lcMessage" role="status" hidden></div>`;
    $('viewGame').prepend(root);
    root.addEventListener('change',e=>{
      const el=e.target.closest('[data-lobby-key]');if(!el)return;
      if(el.type==='number'&&!el.checkValidity()){notice(el.validationMessage,true);el.value=ui.game.lobby.settings[el.dataset.lobbyKey];return;}
      const value=el.type==='checkbox'?el.checked:el.type==='number'||el.dataset.lobbyKey==='max_players'?Number(el.value):el.value;
      queueSettings({[el.dataset.lobbyKey]:value,preset:'custom'});
    });
    root.addEventListener('click',e=>{
      const preset=e.target.closest('[data-preset]');if(preset){applyPreset(preset.dataset.preset);return;}
      const tab=e.target.closest('[data-tab]');if(tab){setTab(tab.dataset.tab);return;}
      const mobile=e.target.closest('[data-lc-mobile]');if(mobile){$('lcLayout').dataset.mobile=mobile.dataset.lcMobile;root.querySelectorAll('[data-lc-mobile]').forEach(b=>b.setAttribute('aria-pressed',String(b===mobile)));return;}
      const kick=e.target.closest('[data-lc-kick]');if(kick){const p=ui.game?.players.find(x=>x.id===kick.dataset.lcKick);if(p&&confirm(`Удалить участника «${p.name}» из комнаты?`))command('HOST_KICK',{player_id:p.id});}
    });
    root.querySelector('.lc-tabs').addEventListener('keydown',e=>{const keys=['ArrowLeft','ArrowRight','Home','End'];if(!keys.includes(e.key))return;e.preventDefault();const tabs=['general','scenario','rules'];let i=tabs.indexOf(ui.tab);i=e.key==='Home'?0:e.key==='End'?2:(i+(e.key==='ArrowRight'?1:2))%3;setTab(tabs[i]);$('lc-tab-'+tabs[i]).focus();});
    $('lcStart').onclick=start;
    $('lcReady').onclick=()=>command('SET_LOBBY_READY',{ready:!ui.game?.lobby?.ready?.[state.playerId],expected_revision:ui.game?.lobby?.revision});
    $('lcAddBots').onclick=()=>{const el=$('lcBotNumber');if(!el.checkValidity()){el.reportValidity();return;}command('ADD_BOTS',{count:Number(el.value)});};
    $('lcFillBots').onclick=()=>command('ADD_BOTS',{count:Math.max(1,6-(ui.game?.total_players||1))});
    $('lcRemoveBots').onclick=()=>{if(confirm('Удалить всех ботов из этой комнаты?'))command('REMOVE_BOTS',{});};
    $('lcLockRoom').onclick=()=>queueSettings({room_locked:!ui.game.lobby.settings.room_locked});
    $('lcCopyCode').onclick=()=>copy(ui.game?.room_code,'Код комнаты скопирован.');
    $('lcCopyLink').onclick=()=>copy(inviteUrl(),(state.networkInfo?.connection_mode==='porthole'?'Ссылка скопирована. Сначала друзья должны подключиться в Porthole.':'Ссылка скопирована. Отправьте её друзьям.'));
    $('lcSaveProfile').onclick=exportProfile;
    $('lcLoadProfile').onclick=()=>$('lcProfileFile').click();
    $('lcProfileFile').onchange=async e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;try{if(file.size>32*1024)throw Error('Файл настроек слишком большой (не более 32 КБ).');const data=JSON.parse(await file.text());if(data.schema_version!==1||data.app!=='bunker-lobby'||!data.settings||Array.isArray(data.settings))throw Error('Это не профиль настроек Бункера версии 1.');const unknown=Object.keys(data.settings).filter(k=>!(k in (ui.catalog?.defaults||{})));if(unknown.length)throw Error('Неизвестные поля: '+unknown.join(', '));queueSettings({...ui.catalog.defaults,...data.settings,preset:'custom',room_locked:ui.game.lobby.settings.room_locked});}catch(err){notice('Профиль не загружен: '+err.message,true);}};
    $('lcResetProfile').onclick=()=>{if(confirm('Вернуть настройки «Классика»? Готовность участников будет сброшена.'))applyPreset('classic');};
  }
  function notice(text,error=false){const box=$('lcMessage');box.textContent=text;box.classList.toggle('is-error',error);box.hidden=false;clearTimeout(ui.noticeTimer);ui.noticeTimer=setTimeout(()=>box.hidden=true,error?10000:5000);}
  function connected(){return ui.online&&state.ws?.readyState===1;}
  function busy(){return Boolean(ui.pending)||Object.keys(ui.queued).length>0;}
  function command(action,payload){
    if(!ui.game||ui.game.phase!=='LOBBY'||!connected()){notice('Нет связи с сервером. Дождитесь переподключения.',true);return false;}
    if(ui.pending){notice('Дождитесь подтверждения предыдущего действия.',true);return false;}
    ui.pending={action,payload};
    if(!sendAction(action,payload)){ui.pending=null;notice('Действие не отправлено.',true);render(ui.game);return false;}
    clearTimeout(ui.pendingTimer);ui.pendingTimer=setTimeout(()=>{if(!ui.pending)return;ui.pending=null;ui.queued={};notice('Сервер не подтвердил действие. Проверьте связь и текущее состояние комнаты.',true);render(ui.game);},8000);
    render(ui.game);return true;
  }
  function queueSettings(patch){
    if(!state.isHost||ui.game?.phase!=='LOBBY')return;
    if(!connected()){notice('Нет связи. Настройки не сохранены.',true);render(ui.game);return;}
    Object.assign(ui.queued,patch);flushSettings();
  }
  function flushSettings(){
    if(ui.pending||!Object.keys(ui.queued).length)return;
    const patch=ui.queued;ui.queued={};
    command('UPDATE_LOBBY_SETTINGS',{settings:patch,expected_revision:ui.game.lobby.revision});
  }
  function applyPreset(key){
    if(!ui.catalog){notice('Список сценариев ещё загружается.',true);return;}
    const current=ui.game.lobby.settings;
    queueSettings({...ui.catalog.presets[key],max_players:current.max_players,room_locked:current.room_locked,require_ready:current.require_ready,information_mode:current.information_mode||'immersion'});
  }
  function setTab(tab){ui.tab=tab;for(const key of ['general','scenario','rules']){$('lc-pane-'+key).hidden=key!==tab;const b=$('lc-tab-'+key);b.setAttribute('aria-selected',String(key===tab));b.tabIndex=key===tab?0:-1;} $('lcSettingsScroll').scrollTop=0;}
  async function loadCatalog(){if(ui.loading||ui.catalog)return;ui.loading=true;try{const res=await fetch('/api/lobby-options');if(!res.ok)throw Error('HTTP '+res.status);const data=await res.json();if(!data.defaults||!Array.isArray(data.catastrophes)||!Array.isArray(data.bunkers))throw Error('Некорректный каталог');ui.catalog=data;for(const [key,list,label] of [['catastrophe_id',data.catastrophes,'Случайная'],['bunker_id',data.bunkers,'Случайное']]){const select=$('lc-'+key);select.innerHTML=`<option value="random">${label} из ${list.length}</option>`+list.map(o=>`<option value="${esc(o.id)}">${esc(o.title||o.name)}</option>`).join('');}render(ui.game);}catch(err){notice('Не удалось получить каталог сценариев. Переподключитесь или обновите страницу. '+err.message,true);}finally{ui.loading=false;}}
  function syncField(el,value,enabled){
    if(document.activeElement!==el||el.type==='checkbox'||el.tagName==='SELECT'){
      if(el.type==='checkbox')el.checked=Boolean(value);else el.value=String(value);
    }
    el.disabled=!enabled;
  }
  function renderRoster(g){
    const l=g.lobby,sig=JSON.stringify([g.players.map(p=>[p.id,p.name,p.connected,p.is_host]),l.ready,g.is_host,ui.pending?.action]);
    if(sig===ui.rosterSig)return;ui.rosterSig=sig;
    const wrap=$('lcRoster');wrap.classList.toggle('is-many',g.players.length>=5);const scroll=wrap.scrollTop,focus=document.activeElement?.dataset?.lcKick;
    wrap.innerHTML=g.players.map((p,i)=>{const bot=p.id.startsWith('bot_'),isMe=p.id===state.playerId,ready=l.ready[p.id];const status=!p.connected?'Нет связи':p.is_host?'Ведущий':bot?'Бот подключён':ready?'Готов к старту':'Изучает настройки';return `<article class="lc-person ${ready?'is-ready':''} ${!p.connected?'is-offline':''}"><span class="lc-person-avatar">${bot?icon('bot'):esc(Array.from(p.name||'?').slice(0,2).join('').toUpperCase())}</span><div><strong title="${esc(p.name)}">${esc(p.name)}${isMe?'<small> · вы</small>':''}</strong><span><i></i>${status}</span></div>${g.is_host&&p.id!==state.playerId?`<button class="lc-person-remove" data-lc-kick="${esc(p.id)}" aria-label="Удалить участника ${esc(p.name)}" title="Удалить из комнаты" ${ui.pending?'disabled':''}>×</button>`:`<span class="lc-person-number">${String(i+1).padStart(2,'0')}</span>`}</article>`;}).join('');
    wrap.scrollTop=scroll;if(focus)[...wrap.querySelectorAll('[data-lc-kick]')].find(e=>e.dataset.lcKick===focus)?.focus({preventScroll:true});
  }
  function render(g){
    if(!g)return;
    const active=g.phase==='LOBBY'&&g.lobby;
    $('lobbyControlRoom').hidden=!active;document.body.classList.toggle('lobby-v2',Boolean(active));
    if(!active){ui.game=g;clearTimeout(ui.pendingTimer);ui.pending=null;ui.queued={};return;}
    if(ui.room!==g.room_code){ui.room=g.room_code;ui.pending=null;ui.queued={};ui.rosterSig=null;ui.lastRevision=null;setTab('general');$('lcMessage').hidden=true;}
    ui.game=g;ui.online=state.ws?.readyState===1;
    if(!g.is_registered&&$('spectatorJoinBanner'))$('lcSpectatorSlot').appendChild($('spectatorJoinBanner'));
    loadCatalog();
    const l=g.lobby,s=l.settings,host=g.is_host,capacity=l.effective_capacity;
    // ACK and state can arrive in either order. Edits are confirmed by revision, not optimism.
    if(ui.pending?.action==='UPDATE_LOBBY_SETTINGS'&&l.revision>ui.pending.payload.expected_revision){
      const sent=ui.pending.payload.settings;
      if(Object.keys(sent).every(k=>k==='preset'||s[k]===sent[k])){clearTimeout(ui.pendingTimer);ui.pending=null;queueMicrotask(flushSettings);}
    }
    const edits={...s,...(ui.pending?.action==='UPDATE_LOBBY_SETTINGS'?ui.pending.payload.settings:{}),...ui.queued};
    $('lcRoomCode').textContent=g.room_code;$('lcCrewCount').textContent=`${g.total_players} / ${s.max_players}`;
    $('lcRevision').textContent=`v${l.revision}`;
    $('lcProfileLabel').textContent=labels[s.preset]||'Свои правила';
    $('lcSync').textContent=!connected()?'Связь потеряна':ui.pending||Object.keys(ui.queued).length?'Сохраняем изменения…':'Настройки сохранены';
    $('lcSync').classList.toggle('is-pending',busy()||!connected());
    for(const el of $('lobbyControlRoom').querySelectorAll('[data-lobby-key]'))syncField(el,edits[el.dataset.lobbyKey],host&&connected()&&(!ui.pending||ui.pending.action==='UPDATE_LOBBY_SETTINGS'));
    $('lc-capacity').disabled=!host||!connected()||edits.capacity_mode==='auto';
    if(edits.capacity_mode==='auto')$('lc-capacity').value=capacity;
    $('lc-event_difficulty').disabled=!host||!connected()||!edits.enable_events;
    $('lc-catastrophe_id').disabled=!host||!connected()||!ui.catalog;
    $('lc-bunker_id').disabled=!host||!connected()||!ui.catalog;
    $('lcInformationHelp').textContent=edits.information_mode==='uncertainty'?'Шансы скрыты: только условия, решения команды и последствия.':'Шанс: низкий / средний / высокий. Без процентов и оценки людей.';
    $('lcDealHelp').textContent=edits.deal_mode==='balanced'?'В группе будут медик и техник. Меньше тяжёлых сочетаний, слабым персонажам — полезные карты.':'Карты равновероятны. Без обязательных профессий, лимитов болезней и помощи слабым персонажам.';
    $('lcSecondSpeech').innerHTML=`${edits.speech_duration/2} <small>сек</small>`;
    $('lcGuestNote').hidden=host;
    $('lc-information_mode').title='Общий режим для всех участников. Меняет только ведущий до начала партии.';
    $('lcCapacityNote').innerHTML=`${icon('people')} <span><b>${capacity}</b> из <b>${g.total_players}</b> останутся в бункере${s.capacity_mode==='auto'?' · пересчитывается при входе участников':''}.</span>`;
    for(const b of document.querySelectorAll('[data-preset]')){b.setAttribute('aria-pressed',String(b.dataset.preset===s.preset));b.disabled=!host||!connected()||!ui.catalog;}
    $('lcLoadProfile').disabled=!host||!connected()||!ui.catalog;$('lcResetProfile').disabled=!host||!connected()||!ui.catalog;
    $('lcSaveProfile').disabled=busy();
    const me=g.players.find(p=>p.id===state.playerId),mineReady=l.ready[state.playerId];
    $('lcReady').hidden=host||!me;
    $('lcReady').disabled=busy()||!connected();
    $('lcReady').innerHTML=icon('check')+(mineReady?'Готов · отменить':'Я готов к старту');$('lcReady').classList.toggle('is-ready',Boolean(mineReady));
    $('lcReadyHelp').textContent=host?`Готовы ${l.ready_count} из ${g.total_players}. Вы подтверждаете готовность запуском.`:mineReady?'Вы подтвердили текущие настройки.':s.require_ready?'Проверьте настройки и подтвердите готовность.':'Подтверждение готовности необязательно.';
    $('lcBots').hidden=!host;
    const bots=g.players.filter(p=>p.id.startsWith('bot_')).length,free=s.max_players-g.total_players;
    $('lcBotCount').textContent=`в комнате: ${bots}`;$('lcBotNumber').max=Math.max(1,free);
    $('lcAddBots').disabled=busy()||!connected()||free<=0;
    $('lcFillBots').disabled=busy()||!connected()||g.total_players>=6||s.max_players<6;
    $('lcRemoveBots').disabled=busy()||!connected()||bots===0;
    $('lcLockRoom').hidden=!host;$('lcLockRoom').disabled=busy()||!connected();
    $('lcLockRoom').innerHTML=icon('lock')+(s.room_locked?'Открыть вход':'Закрыть вход');
    $('lcLockBadge').textContent=s.room_locked?'Вход закрыт':'Вход открыт';$('lcLockBadge').classList.toggle('is-locked',s.room_locked);
    $('lcStart').hidden=!host;$('lcStart').disabled=!l.can_start||busy()||!connected();
    $('lcLaunchLamp').classList.toggle('is-ready',l.can_start&&connected()&&!busy());
    $('lcLaunchTitle').textContent=!connected()?'Нет связи с сервером':busy()?'Сервер подтверждает действие':l.can_start?(host?'Всё готово. Можно закрывать шлюз.':'Всё готово. Ждём ведущего.'):'Подготовка продолжается';
    $('lcLaunchMessage').textContent=!connected()?'Неподтверждённые настройки не используются при старте.':busy()?'Запуск доступен только с подтверждёнными настройками.':l.blockers[0]||`${g.total_players} участников · ${capacity} мест · открытие 60 сек · речи ${s.speech_duration} / ${s.speech_duration/2} сек`;
    $('lcLaunchMessage').title=l.blockers.join('\n');
    renderRoster(g);renderBrief(s,g.total_players,capacity);
    ui.lastRevision=l.revision;
    if(!ui.pending&&Object.keys(ui.queued).length)queueMicrotask(flushSettings);
  }
  function renderBrief(s,n,capacity){
    const cat=ui.catalog?.catastrophes.find(x=>x.id===s.catastrophe_id),bunker=ui.catalog?.bunkers.find(x=>x.id===s.bunker_id);
    const scene=$('lcScene');scene.classList.toggle('has-scene',Boolean(cat));
    const image=cat&&/^[a-z0-9_]+$/.test(cat.id)?`linear-gradient(0deg,rgba(12,17,21,.97),rgba(12,17,21,.14)),url('/static/images/catastrophes/${cat.id}.jpg')`:'';
    if(scene.style.backgroundImage!==image)scene.style.backgroundImage=image;
    $('lcSceneTitle').textContent=cat?.title||'Неизвестная угроза';
    $('lcSceneSubtitle').textContent=cat?`Изоляция: ${cat.duration_years} лет`:'Случайный сценарий при старте';
    $('lcBunkerTitle').textContent=bunker?.name||'Случайный объект';
    $('lcBunkerDetails').textContent=bunker?`${bunker.size_sqm} м² · запасов на ${bunker.supplies_years} лет`:'Один из 20 объектов с разным оснащением.';
    const world=`<strong>${esc(cat?.title||'Сценарий остаётся неизвестным')}</strong><p>${esc(cat?.description||'Катастрофа выбирается один раз при запуске. Все участники увидят один и тот же мир; персонажи ещё не созданы.')}</p>${bunker?`<div class="lc-world-bunker"><strong>${esc(bunker.name)}</strong><p>${esc(bunker.description)}</p><small>Оснащение: ${esc(bunker.facilities.join(' · '))}</small><p class="lc-world-threat">Угроза: ${esc(bunker.threat)}</p></div>`:''}`;
    if($('lcWorldDescription').innerHTML!==world)$('lcWorldDescription').innerHTML=world;
    $('lcSeats').textContent=capacity;$('lcOutside').textContent=Math.max(0,n-capacity);
    $('lcSeatDots').innerHTML=Array.from({length:n},(_,i)=>`<i class="${i<capacity?'inside':''}"></i>`).join('');
    let reveal=s.initial_reveal;if(reveal==='mode')reveal=s.game_mode==='METEORITE'?'profession_health':'closed';
    const rows=[['shuffle',s.deal_mode==='balanced'?'Раздача с подстраховкой':'Полный рандом · как выпадет'],['eye',s.information_mode==='uncertainty'?'Неизвестность · без оценки шансов':'Погружение · словесная оценка шансов'],['clock',`Открытие 60 сек → Речи ${s.speech_duration} / ${s.speech_duration/2} сек`],['shield',`Голосование ${s.voting_duration} сек`],['eye',{closed:'Характеристики скрыты',profession:'Профессии открыты',profession_health:'Профессия и здоровье открыты'}[reveal]],['bolt',s.enable_events?`Испытания: ${{easy:'мягкие',normal:'обычные',hard:'суровые'}[s.event_difficulty]}`:'Без испытаний'],['shuffle',s.enable_special_cards?'Спецкарты включены':'Без спецкарт']];
    $('lcBriefRules').innerHTML=rows.map(([ico,text])=>`<div>${icon(ico)}<span>${text}</span></div>`).join('');
  }
  function start(){if(!ui.game?.lobby?.can_start||busy())return;command('START_GAME',{expected_revision:ui.game.lobby.revision});}
  function onMessage(msg){
    if(!ui.pending)return;
    if(msg.type==='ERROR'||msg.type==='ACTION_ERROR'){
      if(msg.action&&msg.action!==ui.pending.action)return;
      clearTimeout(ui.pendingTimer);ui.pending=null;ui.queued={};notice(msg.message||msg.error||'Действие отклонено сервером.',true);render(ui.game);return;
    }
    if(msg.type==='ACTION_OK'&&msg.action===ui.pending.action){
      // Settings ACK includes the revision; the matching state snapshot confirms the values.
      if(msg.action==='UPDATE_LOBBY_SETTINGS'){
        if(msg.revision===ui.game?.lobby?.revision){ui.pending=null;clearTimeout(ui.pendingTimer);queueMicrotask(flushSettings);}
      }else{ui.pending=null;clearTimeout(ui.pendingTimer);if(msg.action==='ADD_BOTS')notice(`Добавлено ботов: ${msg.added}. Ожидаем подключения.`);}
      render(ui.game);
    }
  }
  function disconnected(){ui.online=false;ui.pending=null;ui.queued={};clearTimeout(ui.pendingTimer);if(ui.game?.phase==='LOBBY')render(ui.game);}
  function reset(){ui.game=null;ui.pending=null;ui.queued={};ui.room=null;clearTimeout(ui.pendingTimer);$('lobbyControlRoom').hidden=true;document.body.classList.remove('lobby-v2');}
  function inviteUrl(){let origin=location.origin;if(state.networkInfo?.connection_mode!=='porthole'&&['localhost','127.0.0.1','::1','[::1]'].includes(location.hostname)){origin=state.networkInfo?.share_url||state.networkInfo?.local_url||origin;}
    try{const url=new URL(origin);url.pathname='/';url.search='';url.hash='';url.searchParams.set('room',ui.game.room_code);return url.href;}catch(_){return `${location.origin}/?room=${ui.game.room_code}`;}}
  async function copy(text,success){try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(text);}else{const input=document.createElement('textarea');input.value=text;input.style.cssText='position:fixed;left:0;top:0;opacity:0';document.body.appendChild(input);input.select();const ok=document.execCommand('copy');input.remove();if(!ok)throw Error('Копирование запрещено браузером.');}notice(success);}catch(_){window.prompt('Скопируйте и отправьте друзьям:',text);}}
  function exportProfile(){if(!ui.game?.lobby)return;const settings={...ui.game.lobby.settings,room_locked:false};const blob=new Blob([JSON.stringify({app:'bunker-lobby',schema_version:1,settings},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='bunker_lobby_profile.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);notice('Профиль сохранён в JSON. Имена, код комнаты и ключи в него не входят.');}
  window.bunkerLobby={render,onMessage,disconnected,reset,start,queueSettings,setTab,exportProfile};
  setup();
})();
