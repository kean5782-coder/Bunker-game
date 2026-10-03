/* Personal media settings; not a host setting and never sent to the server. */
(() => {
  'use strict';
  const fx=window.soundFX;
  if(!fx)return;
  const $=id=>document.getElementById(id);
  const dialog=document.createElement('dialog');dialog.id='audioSettingsDialog';dialog.className='audio-dialog';
  dialog.setAttribute('aria-labelledby','audioDialogTitle');
  const row=(key,label,note)=>`<div class="audio-channel"><div><label for="audio-${key}-volume">${label}</label><small>${note}</small></div><label class="audio-enable"><input id="audio-${key}-enabled" type="checkbox" aria-label="${label}: включить"/><span>Вкл.</span></label><input id="audio-${key}-volume" aria-label="${label}: громкость" type="range" min="0" max="1" step=".01"/><output for="audio-${key}-volume" id="audio-${key}-value"></output></div>`;
  dialog.innerHTML=`<header class="audio-titlebar"><div><span class="eyebrow">ЛИЧНЫЕ НАСТРОЙКИ</span><h2 id="audioDialogTitle">Звук и видео</h2></div><button type="button" id="audioClose" class="btn btn-secondary" aria-label="Закрыть настройки звука">✕</button></header>
  <div class="audio-body"><section class="audio-master"><div><strong>Общая громкость</strong><small>Управляет всеми каналами, включая ролики.</small></div><button type="button" id="audioMasterToggle" class="btn btn-primary"></button><input type="range" id="audioMasterVolume" aria-label="Общая громкость" min="0" max="1" step=".01"/><output for="audioMasterVolume" id="audioMasterValue"></output></section>
  <p class="audio-status" id="audioStatus" role="status"></p>
  <div class="audio-grid"><section class="audio-card"><h3>Громкость каналов</h3>
    ${row('ambient','Эмбиент','Вентиляция и оборудование за стеной')}
    ${row('effects','Эффекты интерфейса','Карточки, кнопки и спецкарты')}
    ${row('notifications','Важные сигналы','Таймер, смена этапа и тревога')}
    ${row('video','Звук роликов','Тихая дорожка коротких сцен катастроф')}
    <div class="audio-test-row"><button class="btn btn-secondary btn-sm" type="button" id="audioPreviewAmbient">Послушать фон</button><button class="btn btn-secondary btn-sm" type="button" id="audioPreviewEffect">Проверить сигнал</button></div>
  </section><section class="audio-card audio-options"><span class="eyebrow">ПРОФИЛЬ</span><h3>Реалистичный бункер</h3><p>Без мелодий, голосов и сердцебиения. Редкие механические детали — раз в 40–90 секунд, только вне речей.</p>
    <label><input id="audio-duckSpeech" type="checkbox"/><span>Приглушать фон во время речей</span></label>
    <label><input id="audio-accents" type="checkbox"/><span>Редкие щелчки, воздух в трубах и скрип металла</span></label>
    <label><input id="audio-exterior" type="checkbox"/><span>Тихая внешняя среда катастрофы</span></label>
    <label><input id="audio-muteHidden" type="checkbox"/><span>Выключать звук в фоновой вкладке</span></label>
    <label><input id="audio-soft" type="checkbox"/><span>Мягкие эффекты и уведомления</span></label>
    <label><input id="audio-clips" type="checkbox"/><span>Показывать короткие ролики катастроф</span></label>
    <small>Без ролика остаются иллюстрация и все условия партии. Общесистемное уменьшение движения также соблюдается.</small>
  </section></div>
  <details class="audio-sources"><summary>Происхождение звуков и помощь</summary><p>В этой сборке используются локальные звуковые слои, созданные синтезом. Это не полевые записи Freesound. Вентиляция, гул механизмов и детали воспроизводятся независимо; API-ключей в игре нет.</p><p>«Послушать фон» явно включает звук и эмбиент. Для общей тишины выключите звук сверху. Ползунки сами не снимают выключение.</p><button type="button" class="btn btn-secondary btn-sm" id="audioRetry">Повторить загрузку аудиофайлов</button><a class="btn btn-secondary btn-sm" href="/static/audio/realistic_bunker/ABOUT_AUDIO.html" target="_blank" rel="noopener">Описание звуков</a></details>
  </div><footer class="audio-footer">Настройки сохраняются в этом браузере. Другие участники выбирают свою громкость.</footer>`;
  document.body.appendChild(dialog);
  const top=document.createElement('button');top.id='btnAudioSettings';top.type='button';top.className='btn btn-secondary btn-sm header-audio';top.title='Звук и видео — личные настройки';top.setAttribute('aria-label',top.title);top.innerHTML='<span aria-hidden="true">♫</span><span class="header-audio-label">Звук</span>';
  (document.querySelector('.header-tools')||document.querySelector('.hud-header')).prepend(top);
  const menu=document.createElement('button');menu.className='btn btn-secondary';menu.type='button';menu.textContent='Звук и видео';menu.id='btnOpenAudioFromVisual';
  $('dashUtility-settings')?.prepend(menu);
  const open=()=>{if(typeof closeModals==='function')closeModals();update();if(!dialog.open)dialog.showModal();};
  window.bunkerAudioSettings={open,close:()=>dialog.close()};
  top.onclick=open;menu.onclick=open;$('audioClose').onclick=()=>dialog.close();
  dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
  $('audioMasterToggle').onclick=()=>{if(!fx.consent||!fx.enabled){fx.chooseSound(true);if(fx.volume===0)fx.setVolume(.55);}else fx.toggleSound();};
  $('audioMasterVolume').oninput=e=>fx.setVolume(e.target.value);
  for(const key of ['ambient','effects','notifications','video']) {
    $(`audio-${key}-volume`).oninput=e=>fx.setSetting(key,e.target.value);
    $(`audio-${key}-enabled`).onchange=e=>{if(key==='ambient'){if(fx.ambientEnabled!==e.target.checked)fx.toggleAmbient();}else fx.setSetting(key+'Enabled',e.target.checked);};
  }
  for(const key of ['duckSpeech','accents','exterior','muteHidden','soft','clips'])$(`audio-${key}`).onchange=e=>fx.setSetting(key,e.target.checked);
  $('audioPreviewAmbient').onclick=()=>fx.previewAmbient();
  $('audioPreviewEffect').onclick=()=>{if(!fx.enabled||!fx.consent)fx.chooseSound(true);else fx.unlock();fx.playTick(false);};
  $('audioRetry').onclick=()=>fx.retryAmbient();
  const consent=document.createElement('section');consent.className='audio-consent';consent.id='audioConsent';consent.setAttribute('aria-label','Включение звука');
  consent.innerHTML='<div><strong>Как войти в бункер?</strong><small>Фон тихий; громкость можно изменить в любой момент.</small></div><div><button class="btn btn-primary btn-sm" id="audioConsentYes" type="button">Со звуком</button><button class="btn btn-secondary btn-sm" id="audioConsentNo" type="button">Без звука</button></div>';
  document.querySelector('.welcome-access')?.appendChild(consent);
  $('audioConsentYes').onclick=()=>fx.chooseSound(true);$('audioConsentNo').onclick=()=>fx.chooseSound(false);
  function update(){
    consent.hidden=fx.consent;
    top.dataset.muted=String(!fx.enabled||fx.volume===0||!fx.consent);
    $('audioMasterToggle').textContent=fx.enabled&&fx.consent?'Выключить весь звук':'Включить звук';
    $('audioMasterToggle').setAttribute('aria-pressed',String(fx.enabled&&fx.consent));
    $('audioMasterVolume').value=fx.volume;$('audioMasterValue').textContent=Math.round(fx.volume*100)+'%';
    $('audioStatus').textContent=fx.status();
    for(const key of ['ambient','effects','notifications','video']){
      $(`audio-${key}-volume`).value=fx.settings[key];$(`audio-${key}-value`).textContent=Math.round(fx.settings[key]*100)+'%';
      $(`audio-${key}-enabled`).checked=key==='ambient'?fx.ambientEnabled:fx.settings[key+'Enabled'];
    }
    for(const key of ['duckSpeech','accents','exterior','muteHidden','soft','clips'])$(`audio-${key}`).checked=fx.settings[key];
  }
  window.addEventListener('bunker-audio-change',update);update();
})();
