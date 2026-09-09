/**
 * Bunk-Net Client Engine: WebSockets, UI rendering, Modals, Host Controls, Audio Sync, Animations.
 */

// Application State
const state = {
  roomCode: null,
  playerId: null,
  playerName: null,
  isHost: false,
  ws: null,
  gameData: null,
  networkInfo: null,
  selectedVoteTarget: null,
  lastPhase: null,
  lastSpeakerId: null,
  lastSecondsLeft: -1,
  reconnectAttempts: 0,
  maxPhaseSeconds: 60,
  heartbeatInterval: null,
  activeModal: null,
  lastActiveEventId: null,
  lastActiveEventOddsSig: null,
  lastPlayersSig: null,
  lastMyCardsSig: null,
  lastScenarioSig: null,
  lastLogLength: 0,
  prologueShownForRoom: null,
  scenarioCollapsed: false
};

// --- Top-level Robust Bot Launch ---
window._isAddingBots = false;
window.addBotsToCurrentRoom = async function(count = 5) {
  if (window._isAddingBots) return;
  window._isAddingBots = true;

  const btn = document.getElementById('btnAddBotsLobby');
  if (btn) btn.disabled = true;

  const hudCode = document.getElementById('hudRoomCode')?.textContent?.trim();
  const roomCode = (state.roomCode || (state.gameData && state.gameData.room_code) || new URLSearchParams(window.location.search).get('room') || hudCode || '').trim().toUpperCase();

  if (!roomCode || roomCode === '----') {
    showToast('Комната не определена!', 'danger');
    if (btn) btn.disabled = false;
    window._isAddingBots = false;
    return;
  }

  showToast(`🤖 Запуск ${count} ИИ-ботов в бункер...`, 'info');
  try {
    if (window.soundFX && typeof window.soundFX.playVoteCast === 'function') {
      window.soundFX.playVoteCast();
    } else if (window.soundFX && typeof window.soundFX.playClick === 'function') {
      window.soundFX.playClick();
    }
  } catch (_) {}

  try {
    const res = await fetch(`/api/room/${roomCode}/add-bots`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count: count })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`✅ Успешно добавлено ${data.added} ботов!`, 'success');
    } else {
      showToast(data.detail || 'Добавление ботов через резервный канал...', 'warning');
      sendAction('ADD_BOTS', { count: count });
    }
  } catch (err) {
    console.warn('HTTP fallback to WS for add-bots:', err);
    sendAction('ADD_BOTS', { count: count });
  } finally {
    setTimeout(() => {
      if (btn) btn.disabled = false;
      window._isAddingBots = false;
    }, 1200);
  }
};

const ALL_ACHIEVEMENTS = [
  { badge: '💉', title: 'Ангел-хранитель', desc: 'Спас здоровье колонии медицинскими навыками (Профессия: Медицина)' },
  { badge: '⚙️', title: 'Хранитель систем', desc: 'Держал энергоблок и фильтры в рабочем состоянии (Профессия: Инженерия / Техника)' },
  { badge: '🌱', title: 'Кормилец колонии', desc: 'Обеспечил бункер питанием и чистой водой (Профессия: Агрономия / Питание)' },
  { badge: '🛡️', title: 'Щит рубежей', desc: 'Защищал гермошлюзы и поддерживал дисциплину (Профессия: Охрана / Безопасность)' },
  { badge: '📚', title: 'Хранитель знаний', desc: 'Сохранил научный потенциал и культурное наследие (Профессия: Наука / Образование)' },
  { badge: '🎭', title: 'Мастер убеждения', desc: 'Сумел выжить вопреки серьезным слабостям досье (Критические болезни / Бесполезная профессия)' },
  { badge: '⚡', title: 'Критический триумф', desc: 'Выбросил натуральный критический успех (≤ 5) во время кризиса' },
  { badge: '🎯', title: 'Ищейка на диверсантов', desc: 'Своевременно разоблачил и изгнал тайного предателя до финала' },
  { badge: '☠️', title: 'Голос из пепла', desc: 'Выжил на поверхности после изгнания и отомстил бункеру Вендеттой' }
];

function getCatastropheIllustration(catId) {
  if (catId) {
    return `
      <div style="position: relative; width: 100%; max-width: 280px; height: 110px; border-radius: 8px; overflow: hidden; border: 1px solid rgba(0, 240, 255, 0.35); box-shadow: 0 0 16px rgba(0, 240, 255, 0.2);">
        <video src="/static/videos/catastrophes/${catId}.mp4" poster="/static/images/catastrophes/${catId}.jpg" autoplay muted loop playsinline style="width: 100%; height: 100%; object-fit: cover; display: block;"></video>
        <div style="position: absolute; bottom: 0; left: 0; right: 0; padding: 3px 8px; background: rgba(0,0,0,0.7); font-size: 10px; color: var(--accent-cyan); font-family: var(--font-hud); letter-spacing: 1px; display: flex; align-items: center; justify-content: space-between;">
          <span>🔴 ОПЕРАТИВНАЯ СВОДКА</span>
          <span style="color: var(--accent-danger);">СУДНЫЙ ДЕНЬ</span>
        </div>
      </div>
    `;
  }
  return '';
}

// --- Initialization ---
document.addEventListener('DOMContentLoaded', async () => {
  // Check URL query params for direct room link (e.g. ?room=ABCD)
  const params = new URLSearchParams(window.location.search);
  const roomParam = params.get('room');
  if (roomParam) {
    const code = roomParam.trim().toUpperCase();
    const joinInput = document.getElementById('inputJoinRoom');
    if (joinInput) joinInput.value = code;
    checkDirectRoomLink(code);
  }

  // Load network info
  fetchNetworkInfo();

  // Setup Sound buttons
  setupSoundButtons();

  // Bind forms and buttons
  document.getElementById('btnCreateRoom').addEventListener('click', handleCreateRoom);
  document.getElementById('btnJoinRoom').addEventListener('click', handleJoinRoom);
  document.getElementById('btnCopyDiscord').addEventListener('click', copyDiscordLink);
  document.getElementById('btnCopyShareLink').addEventListener('click', copyDiscordLink);

  // HUD & Spectator action buttons
  const btnClaimHost = document.getElementById('btnClaimHost');
  if (btnClaimHost) btnClaimHost.addEventListener('click', handleClaimHost);

  const btnLeaveRoom = document.getElementById('btnLeaveRoom');
  if (btnLeaveRoom) btnLeaveRoom.addEventListener('click', handleLeaveRoom);

  const btnSpectatorJoin = document.getElementById('btnSpectatorJoin');
  if (btnSpectatorJoin) btnSpectatorJoin.addEventListener('click', handleSpectatorJoin);

  const btnSpectatorClaimHost = document.getElementById('btnSpectatorClaimHost');
  if (btnSpectatorClaimHost) btnSpectatorClaimHost.addEventListener('click', handleSpectatorClaimHost);

  const btnDirectJoinPlayer = document.getElementById('btnDirectJoinPlayer');
  if (btnDirectJoinPlayer) {
    btnDirectJoinPlayer.addEventListener('click', () => {
      const name = document.getElementById('inputDirectName').value.trim() || 'Игрок';
      const codeSpan = document.getElementById('detectedRoomCode');
      const code = (codeSpan && codeSpan.textContent ? codeSpan.textContent : roomParam || '').trim().toUpperCase();
      joinRoomWithCode(code, name);
    });
  }

  const btnDirectClaimHost = document.getElementById('btnDirectClaimHost');
  if (btnDirectClaimHost) {
    btnDirectClaimHost.addEventListener('click', () => {
      const name = document.getElementById('inputDirectName').value.trim() || 'Ведущий';
      const codeSpan = document.getElementById('detectedRoomCode');
      const code = (codeSpan && codeSpan.textContent ? codeSpan.textContent : roomParam || '').trim().toUpperCase();
      claimHostWithCode(code, name);
    });
  }

  // Setup Modals
  setupModals();

  // Setup Game and Host Controls buttons
  setupGameAndHostButtons();

  // Discord Report Button on final screen
  const btnReport = document.getElementById('btnCopyDiscordReport');
  if (btnReport) {
    btnReport.addEventListener('click', generateDiscordReport);
  }

  // Collapsible scenario accordion toggle
  const btnToggleScenario = document.getElementById('btnToggleScenario');
  if (btnToggleScenario) {
    btnToggleScenario.addEventListener('click', () => {
      state.scenarioCollapsed = !state.scenarioCollapsed;
      const scenSec = document.getElementById('scenarioSection');
      const icon = document.getElementById('scenarioToggleIcon');
      const text = document.getElementById('scenarioToggleText');
      if (state.scenarioCollapsed) {
        if (scenSec) scenSec.style.display = 'none';
        if (icon) icon.textContent = '▶️';
        if (text) text.textContent = 'Развернуть данные бункера и катастрофы';
      } else {
        if (scenSec) scenSec.style.display = 'grid';
        if (icon) icon.textContent = '🔽';
        if (text) text.textContent = 'Свернуть данные бункера и катастрофы';
      }
    });
  }

  // Auto-reconnect from localStorage if available
  tryRestoreSession();
});

function setupSoundButtons() {
  const btnSound = document.getElementById('btnToggleSound');
  const sliderVol = document.getElementById('soundVolumeSlider');
  const labelVol = document.getElementById('soundVolumeLabel');

  const updateSoundUI = () => {
    if (btnSound && window.soundFX) {
      btnSound.textContent = window.soundFX.enabled ? '🔊 Звук: ВКЛ' : '🔇 Звук: ВЫКЛ';
    }
    if (sliderVol && window.soundFX) {
      sliderVol.value = window.soundFX.volume;
    }
    if (labelVol && window.soundFX) {
      labelVol.textContent = `${Math.round(window.soundFX.volume * 100)}%`;
    }
  };

  if (sliderVol && window.soundFX) {
    sliderVol.value = window.soundFX.volume;
    if (labelVol) {
      labelVol.textContent = `${Math.round(window.soundFX.volume * 100)}%`;
    }

    sliderVol.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      window.soundFX.setVolume(val);
      if (labelVol) {
        labelVol.textContent = `${Math.round(val * 100)}%`;
      }
      if (btnSound) {
        btnSound.textContent = window.soundFX.enabled ? '🔊 Звук: ВКЛ' : '🔇 Звук: ВЫКЛ';
      }
    });

    sliderVol.addEventListener('change', () => {
      if (window.soundFX && window.soundFX.enabled) {
        window.soundFX.playClick();
      }
    });
  }

  if (btnSound && window.soundFX) {
    btnSound.addEventListener('click', () => {
      const enabled = window.soundFX.toggleSound();
      if (enabled && window.soundFX.volume === 0) {
        window.soundFX.setVolume(0.5);
      }
      updateSoundUI();
      showToast(enabled ? 'Звуковые эффекты включены' : 'Звуковые эффекты отключены');
    });
    updateSoundUI();
  }

  const btnAmbient = document.getElementById('btnToggleAmbient');
  if (btnAmbient && window.soundFX) {
    btnAmbient.addEventListener('click', () => {
      const enabled = window.soundFX.toggleAmbient();
      btnAmbient.textContent = enabled ? '📻 Гул: ВКЛ' : '📻 Гул: ВЫКЛ';
      showToast(enabled ? 'Низкочастотный гул бункера включен' : 'Гул бункера отключен');
    });
    btnAmbient.textContent = window.soundFX.ambientEnabled ? '📻 Гул: ВКЛ' : '📻 Гул: ВЫКЛ';
    if (window.soundFX.ambientEnabled) {
      window.soundFX.startAmbient();
    }
  }
}

async function fetchNetworkInfo() {
  try {
    const res = await fetch('/api/network-info');
    if (res.ok) {
      state.networkInfo = await res.json();
      const extSpan = document.getElementById('networkExternal');
      const locSpan = document.getElementById('networkLocal');
      if (extSpan && (state.networkInfo.display_url || state.networkInfo.external_url)) {
        extSpan.textContent = state.networkInfo.display_url || state.networkInfo.external_url;
      } else if (extSpan && state.networkInfo.external_ip) {
        extSpan.textContent = `http://${state.networkInfo.external_ip}:${state.networkInfo.port}`;
      } else if (extSpan) {
        extSpan.textContent = 'Локальный режим (без белого IP)';
      }
      if (locSpan) {
        locSpan.textContent = state.networkInfo.local_url;
      }
    }
  } catch (err) {
    console.error('Failed to fetch network info:', err);
  }
}

// --- Session Persistence ---
function saveSession() {
  if (state.roomCode && state.playerId) {
    localStorage.setItem('bunker_session', JSON.stringify({
      roomCode: state.roomCode,
      playerId: state.playerId,
      playerName: state.playerName,
      isHost: state.isHost
    }));
  }
}

async function checkDirectRoomLink(code) {
  try {
    const res = await fetch(`/api/room/${code}`);
    if (res.ok) {
      const roomInfo = await res.json();
      const banner = document.getElementById('welcomeRoomDetectedBanner');
      const codeSpan = document.getElementById('detectedRoomCode');
      if (banner && codeSpan) {
        codeSpan.textContent = code;
        banner.style.display = 'block';
      }
    }
  } catch (e) {
    console.warn('Could not verify direct room link:', e);
  }
}

function tryRestoreSession() {
  try {
    const saved = localStorage.getItem('bunker_session');
    if (saved) {
      const parsed = JSON.parse(saved);
      const params = new URLSearchParams(window.location.search);
      const urlRoom = params.get('room');
      
      // If URL explicitly points to another room, don't restore old session for a different room
      if (urlRoom && urlRoom.toUpperCase() !== parsed.roomCode) {
        return;
      }

      state.roomCode = parsed.roomCode;
      state.playerId = parsed.playerId;
      state.playerName = parsed.playerName;
      state.isHost = Boolean(parsed.isHost);
      connectWebSocket();
    }
  } catch (e) {
    console.warn('Session restore error:', e);
  }
}

// --- Room Creation & Joining ---
async function handleCreateRoom() {
  const hostName = document.getElementById('inputHostName').value.trim() || 'Ведущий';
  const enableTraitor = document.getElementById('checkEnableTraitor').checked;
  const checkEvents = document.getElementById('checkEnableEvents');
  const enableEvents = checkEvents ? checkEvents.checked : true;

  try {
    const res = await fetch('/api/room/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host_name: hostName,
        enable_traitor: enableTraitor,
        enable_events: enableEvents
      })
    });
    const data = await res.json();
    state.roomCode = data.room_code;
    state.playerId = data.host_id;
    state.playerName = hostName;
    state.isHost = true;

    saveSession();

    // Update address bar without reload
    const newUrl = `${window.location.origin}${window.location.pathname}?room=${state.roomCode}`;
    window.history.pushState({ path: newUrl }, '', newUrl);

    connectWebSocket();
  } catch (err) {
    showToast('Ошибка создания комнаты: ' + err.message, 'danger');
  }
}

async function joinRoomWithCode(code, name) {
  if (!code) {
    showToast('Введите код комнаты!', 'warning');
    return;
  }

  try {
    const res = await fetch('/api/room/join', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ room_code: code, player_name: name || 'Беженец' })
    });

    if (!res.ok) {
      const err = await res.json();
      showToast(err.detail || 'Не удалось войти в комнату', 'danger');
      return;
    }

    const data = await res.json();
    state.roomCode = data.room_code;
    state.playerId = data.player_id;
    state.playerName = name || 'Беженец';
    state.isHost = Boolean(data.is_host);

    saveSession();

    const newUrl = `${window.location.origin}${window.location.pathname}?room=${state.roomCode}`;
    window.history.pushState({ path: newUrl }, '', newUrl);

    connectWebSocket();
    showToast(`Вы вошли в бункер как ${state.playerName}!`, 'success');
  } catch (err) {
    showToast('Ошибка подключения к комнате: ' + err.message, 'danger');
  }
}

async function claimHostWithCode(code, name) {
  if (!code) {
    showToast('Введите код комнаты!', 'warning');
    return;
  }

  try {
    const res = await fetch(`/api/room/${code}/claim-host`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        player_name: name || 'Ведущий',
        player_id: state.playerId || undefined
      })
    });

    if (!res.ok) {
      const err = await res.json();
      showToast(err.detail || 'Не удалось занять место Ведущего', 'danger');
      return;
    }

    const data = await res.json();
    state.roomCode = data.room_code;
    state.playerId = data.player_id;
    state.playerName = data.player_name || 'Ведущий';
    state.isHost = true;

    saveSession();

    const newUrl = `${window.location.origin}${window.location.pathname}?room=${state.roomCode}`;
    window.history.pushState({ path: newUrl }, '', newUrl);

    connectWebSocket();
    showToast('👑 Вы успешно заняли роль Ведущего бункера!', 'success');
  } catch (err) {
    showToast('Ошибка при получении роли ведущего: ' + err.message, 'danger');
  }
}

async function handleJoinRoom() {
  const code = document.getElementById('inputJoinRoom').value.trim().toUpperCase();
  const name = document.getElementById('inputPlayerName').value.trim() || 'Беженец';
  await joinRoomWithCode(code, name);
}

function handleClaimHost() {
  const name = state.playerName || 'Ведущий';
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    sendAction('CLAIM_HOST', { name: name });
    state.isHost = true;
    saveSession();
    showToast('👑 Запрос на получение роли Ведущего отправлен...', 'info');
  } else if (state.roomCode) {
    claimHostWithCode(state.roomCode, name);
  }
}

function handleSpectatorJoin() {
  const nameInput = document.getElementById('spectatorPlayerName');
  const name = (nameInput ? nameInput.value.trim() : '') || state.playerName || 'Беженец';
  state.playerName = name;
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    sendAction('JOIN_LOBBY', { name: name });
    state.isHost = false;
    saveSession();
    showToast(`📱 Вы вошли в лобби как ${name}!`, 'success');
  } else if (state.roomCode) {
    joinRoomWithCode(state.roomCode, name);
  }
}

function handleSpectatorClaimHost() {
  const nameInput = document.getElementById('spectatorPlayerName');
  const name = (nameInput ? nameInput.value.trim() : '') || state.playerName || 'Ведущий';
  state.playerName = name;
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    sendAction('CLAIM_HOST', { name: name });
    state.isHost = true;
    saveSession();
    showToast('👑 Вы запросили место Ведущего бункера!', 'success');
  } else if (state.roomCode) {
    claimHostWithCode(state.roomCode, name);
  }
}

function handleLeaveRoom() {
  if (!confirm('Вы уверены, что хотите выйти из комнаты в главное меню?')) {
    return;
  }
  if (state.ws) {
    try {
      state.ws.close();
    } catch (e) {}
    state.ws = null;
  }
  stopHeartbeat();
  localStorage.removeItem('bunker_session');
  state.roomCode = null;
  state.playerId = null;
  state.playerName = null;
  state.isHost = false;
  state.gameData = null;

  // Clear query param in address bar
  const cleanUrl = window.location.origin + window.location.pathname;
  window.history.pushState({ path: cleanUrl }, '', cleanUrl);

  // Switch view
  document.getElementById('viewGame').style.display = 'none';
  document.getElementById('viewWelcome').style.display = 'block';
  const btnLeave = document.getElementById('btnLeaveRoom');
  if (btnLeave) btnLeave.style.display = 'none';
  const btnDiscord = document.getElementById('btnCopyDiscord');
  if (btnDiscord) btnDiscord.style.display = 'none';
  const btnClaim = document.getElementById('btnClaimHost');
  if (btnClaim) btnClaim.style.display = 'none';

  updateConnectionBadge('disconnected');
  showToast('Вы вышли из комнаты', 'info');
}

// --- WebSocket Connection & Heartbeat ---
function connectWebSocket() {
  if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/${state.roomCode}/${state.playerId}`;

  updateConnectionBadge('connecting');
  state.ws = new WebSocket(wsUrl);

  state.ws.onopen = () => {
    state.reconnectAttempts = 0;
    updateConnectionBadge('connected');
    document.getElementById('viewWelcome').style.display = 'none';
    document.getElementById('viewGame').style.display = 'block';
    const btnLeave = document.getElementById('btnLeaveRoom');
    if (btnLeave) btnLeave.style.display = 'inline-flex';
    const btnDiscord = document.getElementById('btnCopyDiscord');
    if (btnDiscord) btnDiscord.style.display = 'inline-flex';
    window.soundFX.playVaultDoor();
    startHeartbeat();
  };

  state.ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'STATE_UPDATE') {
        handleStateUpdate(msg.state);
      } else if (msg.type === 'PLAY_SOUND') {
        if (msg.sound === 'siren') {
          window.soundFX.playSiren();
          triggerScreenShake();
        } else if (msg.sound === 'elimination') {
          window.soundFX.playElimination();
          triggerScreenShake();
        }
      } else if (msg.type === 'PONG') {
        // Heartbeat ACK
      } else if (msg.type === 'ERROR') {
        showToast(msg.message || 'Ошибка действия', 'danger');
      }
    } catch (e) {
      console.error('WS parse error:', e);
    }
  };

  state.ws.onclose = (event) => {
    stopHeartbeat();
    updateConnectionBadge('disconnected');
    if (event && event.code === 4004) {
      localStorage.removeItem('bunker_session');
      document.getElementById('viewGame').style.display = 'none';
      document.getElementById('viewWelcome').style.display = 'block';
      const btnLeave = document.getElementById('btnLeaveRoom');
      if (btnLeave) btnLeave.style.display = 'none';
      const btnDiscord = document.getElementById('btnCopyDiscord');
      if (btnDiscord) btnDiscord.style.display = 'none';
      const btnClaim = document.getElementById('btnClaimHost');
      if (btnClaim) btnClaim.style.display = 'none';
      showToast('Комната закрыта или сервер был перезапущен', 'warning');
      return;
    }
    scheduleReconnect();
  };

  state.ws.onerror = () => {
    updateConnectionBadge('disconnected');
  };
}

function updateConnectionBadge(status) {
  const badge = document.getElementById('hudConnectionStatus');
  if (!badge) return;

  if (status === 'connected') {
    badge.innerHTML = '<span class="live-dot success"></span> СВЯЗЬ АКТИВНА';
  } else if (status === 'connecting') {
    badge.innerHTML = '<span class="live-dot"></span> ПОДКЛЮЧЕНИЕ...';
  } else {
    badge.innerHTML = '<span class="live-dot danger"></span> ПОИСК СИГНАЛА...';
  }
}

function startHeartbeat() {
  stopHeartbeat();
  state.heartbeatInterval = setInterval(() => {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ action: 'PING' }));
    }
  }, 15000);
}

function stopHeartbeat() {
  if (state.heartbeatInterval) {
    clearInterval(state.heartbeatInterval);
    state.heartbeatInterval = null;
  }
}

function scheduleReconnect() {
  state.reconnectAttempts++;
  const delay = Math.min(1000 * Math.pow(1.5, state.reconnectAttempts), 8000);
  setTimeout(() => {
    if (state.roomCode && state.playerId) {
      connectWebSocket();
    }
  }, delay);
}

function sendAction(action, payload = {}) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ action, payload }));
  }
}

// --- Screen Shake & Cinematic Banner ---
function triggerScreenShake() {
  document.body.classList.add('shake-active');
  setTimeout(() => document.body.classList.remove('shake-active'), 500);
}

function showCinematicPhaseAlert(title, subtitle, type = 'cyan') {
  const banner = document.getElementById('cinematicPhaseBanner');
  const titleEl = document.getElementById('cinematicAlertTitle');
  const subEl = document.getElementById('cinematicAlertSub');
  if (!banner || !titleEl || !subEl) return;

  titleEl.textContent = title;
  subEl.textContent = subtitle;

  banner.className = `cinematic-phase-overlay phase-alert-enter ${type === 'danger' ? 'danger' : type === 'warning' ? 'warning' : ''}`;
  titleEl.style.color = type === 'danger' ? 'var(--accent-danger)' : type === 'warning' ? 'var(--accent-amber)' : 'var(--accent-cyan)';
  banner.style.display = 'block';

  window.soundFX.playPhaseTransition();

  setTimeout(() => {
    banner.classList.remove('phase-alert-enter');
    banner.classList.add('phase-alert-exit');
    setTimeout(() => {
      banner.style.display = 'none';
      banner.classList.remove('phase-alert-exit');
    }, 400);
  }, 2800);
}

// --- State Handling and Render ---
function handleStateUpdate(game) {
  state.gameData = game;
  const wasHost = state.isHost;
  state.isHost = Boolean(game.is_host);

  if (!wasHost && state.isHost) {
    saveSession();
    showToast('👑 Вы управляете комнатой как Ведущий!', 'success');
  }

  // Header display
  document.getElementById('hudRoomCode').textContent = game.room_code;
  document.getElementById('hudAliveCount').textContent = `${game.alive_count} / ${game.total_players}`;
  document.getElementById('hudCapacity').textContent = game.bunker_capacity;

  // Toggle HUD Claim Host button
  const btnClaim = document.getElementById('btnClaimHost');
  if (btnClaim) {
    btnClaim.style.display = (!state.isHost && game.can_claim_host) ? 'inline-flex' : 'none';
  }

  // Spectator unregistered banner
  const specBanner = document.getElementById('spectatorJoinBanner');
  if (specBanner) {
    const isUnregistered = !game.is_registered;
    specBanner.style.display = isUnregistered ? 'flex' : 'none';
    const specJoinBtn = document.getElementById('btnSpectatorJoin');
    if (specJoinBtn) {
      specJoinBtn.style.display = (game.phase === 'LOBBY') ? 'inline-block' : 'none';
    }
    const specClaimBtn = document.getElementById('btnSpectatorClaimHost');
    if (specClaimBtn) {
      specClaimBtn.style.display = (game.can_claim_host) ? 'inline-block' : 'none';
    }
  }

  // Phase transition cinematic banner and audio triggers
  if (state.lastPhase !== game.phase) {
    handlePhaseTransition(game.phase);
    state.lastPhase = game.phase;
    state.selectedVoteTarget = null; // Сброс выбранной цели голосования при смене фазы
  }

  // Cinematic prologue on game start
  if (game.phase !== 'LOBBY' && game.catastrophe && state.prologueShownForRoom !== game.room_code) {
    state.prologueShownForRoom = game.room_code;
    triggerCinematicPrologue(game);
  }

  // Ticking sound & heartbeat for last seconds of timer
  if (game.timer && game.timer.seconds_left > 0 && !game.timer.is_paused) {
    const sec = game.timer.seconds_left;
    if (sec <= 5 && state.lastSecondsLeft !== sec) {
      window.soundFX.playTick(true);
      window.soundFX.playTensionHeartbeat();
      state.lastSecondsLeft = sec;
    } else if (sec <= 10 && state.lastSecondsLeft !== sec) {
      window.soundFX.playTick(false);
      state.lastSecondsLeft = sec;
    }
  }

  // Render Host Admin Controls Bar (if host)
  renderHostControls(game);

  // Render Phase Banner and Circular Timer
  renderPhaseBanner(game);

  // Render Catastrophe & Bunker specs
  renderScenario(game);

  // Render My Dossier (Mobile / Player View)
  renderMyDossier(game);

  // Render Voting section & Tiebreaker
  renderVotingSection(game);

  // Render All Players Grid
  renderPlayersGrid(game);

  // Render Event Log
  renderGameLog(game);

  // Render Active Event / Challenge (if present)
  renderActiveEvent(game);

  // Render Final Evaluation (if FINAL phase)
  renderFinalScreen(game);

  // Synchronized dice roll modal for all players
  const lastRes = game.events_state ? game.events_state.last_resolved : null;
  if (lastRes && lastRes.resolved_at) {
    if (state.lastSeenResolvedAt === undefined) {
      // First load or reconnect: record without triggering popup
      state.lastSeenResolvedAt = lastRes.resolved_at;
    } else if (lastRes.resolved_at > state.lastSeenResolvedAt) {
      state.lastSeenResolvedAt = lastRes.resolved_at;
      openDiceModal(lastRes);
    }
  }
}

function handlePhaseTransition(phase) {
  if (phase === 'SPEECH') {
    showCinematicPhaseAlert('⚡ ФАЗА ЗАЩИТНЫХ РЕЧЕЙ', 'Каждый кандидат вскрывает карту и доказывает свою полезность', 'cyan');
    window.soundFX.playCardReveal();
  } else if (phase === 'COLLECTIVE_DISCUSSION') {
    showCinematicPhaseAlert('🗣️ КОЛЛЕКТИВНОЕ ОБСУЖДЕНИЕ', '60 секунд открытого микрофона для всех выживших!', 'warning');
    window.soundFX.playVaultDoor();
  } else if (phase === 'ACCUSATION') {
    showCinematicPhaseAlert('⚖️ РАУНД ОБВИНЕНИЙ', 'По 30 секунд каждому на претензии и аргументы перед голосованием!', 'warning');
    window.soundFX.playCardReveal();
  } else if (phase === 'DEBATE') {
    showCinematicPhaseAlert('🗣️ ПООЧЕРЕДНЫЕ ДЕБАТЫ', 'По 1 минуте на каждого кандидата. Аргументируйте или передайте слово!', 'warning');
    window.soundFX.playVaultDoor();
  } else if (phase === 'VOTING') {
    showCinematicPhaseAlert('🚨 ТАЙНОЕ ГОЛОСОВАНИЕ', 'У вас 15 секунд! Не успевшие голосуют против себя.', 'danger');
    window.soundFX.playSiren();
    triggerScreenShake();
  } else if (phase === 'JUSTIFICATION') {
    showCinematicPhaseAlert('🛡️ ОПРАВДАТЕЛЬНАЯ РЕЧЬ', 'Порог 70% не набран или ничья: кандидаты держат защиту по 30 сек!', 'warning');
    window.soundFX.playVaultDoor();
  } else if (phase === 'REVOTE') {
    showCinematicPhaseAlert('🚨 ПЕРЕГОЛОСОВАНИЕ (15 СЕК)', 'Голосуйте строго между кандидатами на оправдание!', 'danger');
    window.soundFX.playSiren();
    triggerScreenShake();
  } else if (phase === 'VOTE_RESULTS') {
    showCinematicPhaseAlert('📊 ПОДСЧЕТ ГОЛОСОВ', 'Большинство выбрало жертву. Время для права Вето!', 'warning');
    window.soundFX.playElimination();
  } else if (phase === 'FINAL') {
    showCinematicPhaseAlert('🚪 ГЕРМОШЛЮЗ ЗАПЕРТ!', 'Врата бункера заблокированы. Расчет выживаемости колонии...', 'cyan');
    window.soundFX.playVaultDoor();
  }
}

// --- UI Render Sub-routines ---

function renderHostControls(game) {
  const hostBar = document.getElementById('hostControlsBar');
  if (!state.isHost) {
    hostBar.style.display = 'none';
    const lobbyControls = document.getElementById('hostLobbySettings');
    if (lobbyControls) lobbyControls.style.display = 'none';
    return;
  }
  hostBar.style.display = 'flex';

  const pauseBtn = document.getElementById('btnHostPause');
  const isPaused = game.timer ? game.timer.is_paused : false;
  pauseBtn.textContent = isPaused ? '▶️ Продолжить' : '⏸️ Пауза';

  // Toggle lobby start controls
  const lobbyControls = document.getElementById('hostLobbySettings');
  if (lobbyControls) {
    lobbyControls.style.display = game.phase === 'LOBBY' ? 'block' : 'none';
  }

  // Sync lobby traitor toggle
  const checkLobbyTraitor = document.getElementById('checkLobbyTraitor');
  if (checkLobbyTraitor && game.phase === 'LOBBY') {
    checkLobbyTraitor.checked = Boolean(game.enable_traitor);
  }

  // Sync lobby events toggle
  const checkLobbyEvents = document.getElementById('checkLobbyEvents');
  if (checkLobbyEvents && game.phase === 'LOBBY') {
    checkLobbyEvents.checked = Boolean(game.events_enabled !== false);
  }

  // Tiebreaker button
  const btnTiebreaker = document.getElementById('btnHostTiebreaker');
  if (btnTiebreaker) {
    const isTie = game.vote_results && game.vote_results.is_tie && game.phase === 'VOTE_RESULTS';
    btnTiebreaker.style.display = isTie ? 'inline-flex' : 'none';
  }

  // Discussion skip button in host bar
  const btnHostSkipDiscBar = document.getElementById('btnHostSkipDiscBar');
  if (btnHostSkipDiscBar) {
    btnHostSkipDiscBar.style.display = (game.phase === 'COLLECTIVE_DISCUSSION') ? 'inline-flex' : 'none';
  }
  const btnForceDebate = document.getElementById('btnForceDebate');
  if (btnForceDebate) {
    if (game.phase === 'COLLECTIVE_DISCUSSION') {
      btnForceDebate.textContent = '🗣️ К обвинениям';
    } else {
      btnForceDebate.textContent = '🗣️ К дебатам';
    }
  }
}

function renderPhaseBanner(game) {
  const titleEl = document.getElementById('phaseTitle');
  const descEl = document.getElementById('phaseDesc');
  const timerBox = document.getElementById('timerBox');
  const timerDigits = document.getElementById('timerDigits');
  const svgTimerBar = document.getElementById('svgTimerBar');
  const speakerSpot = document.getElementById('speakerSpotlight');

  const dirHint = game.round_direction === 'reverse' ? ' 🔄 Порядок: Обратный (реверс раунда)' : ' ➡️ Порядок: Прямой';

  const phaseNames = {
    'LOBBY': { title: 'ШЛЮЗ БУНКЕРА: СБОР ВЫЖИВШИХ', desc: 'Ожидание подключения игроков. Раздайте ссылку друзьям в Discord!' },
    'PROLOGUE': { title: 'КАТАСТРОФА: АКТИВАЦИЯ БУНКЕРА', desc: 'Ознакомьтесь с условиями катаклизма и нажмите «В бункер» для начала игры.' },
    'SPEECH': { title: 'ЗАЩИТНАЯ РЕЧЬ', desc: `Кандидат выступает и открывает характеристики.${dirHint}.` },
    'COLLECTIVE_DISCUSSION': { title: 'КОЛЛЕКТИВНОЕ ОБСУЖДЕНИЕ (60 СЕК)', desc: 'Открытый микрофон: свободное обсуждение кандидатов и открытых карт.' },
    'ACCUSATION': { title: 'РАУНД ОБВИНЕНИЙ И АРГУМЕНТОВ', desc: `По 30 секунд на каждого игрока: аргументируйте подозрения перед голосованием.${dirHint}.` },
    'DEBATE': { title: 'ПООЧЕРЕДНЫЕ ДЕБАТЫ', desc: 'По 1 минуте на каждого игрока: аргументируйте свою пользу или передайте слово.' },
    'VOTING': { title: 'ТАЙНОЕ ГОЛОСОВАНИЕ (15 СЕК)', desc: '15 сек на выбор. Не успевшие проголосовать голосуют против себя!' },
    'JUSTIFICATION': { title: 'ОПРАВДАТЕЛЬНАЯ РЕЧЬ (30 СЕК)', desc: 'Порог 70% не набран или ничья: кандидаты доказывают свою незаменимость.' },
    'REVOTE': { title: 'ПЕРЕГОЛОСОВАНИЕ (15 СЕК)', desc: 'Голосование строго между кандидатами на оправдание. Простое большинство!' },
    'VOTE_RESULTS': { title: 'ИТОГИ ГОЛОСОВАНИЯ', desc: 'Подсчет голосов. Время для применения права Вето.' },
    'LAST_WORD': { title: 'ПОСЛЕДНЕЕ СЛОВО ИЗГНАННОГО', desc: 'Изгнанный кандидат произносит прощальную речь перед запечатыванием гермошлюза (15 секунд).' },
    'FINAL': { title: 'ГЕРМОШЛЮЗ ЗАПЕРТ: ФИНАЛ', desc: 'Подсчет шансов колонии на выживание в бункере.' }
  };

  const pInfo = phaseNames[game.phase] || { title: game.phase, desc: '' };
  titleEl.textContent = pInfo.title;
  descEl.textContent = pInfo.desc;

  // Circular SVG Timer
  if (game.phase !== 'LOBBY' && game.phase !== 'FINAL' && game.phase !== 'PROLOGUE') {
    timerBox.style.display = 'flex';
    const sec = game.timer ? game.timer.seconds_left : 0;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    timerDigits.textContent = `${m}:${s < 10 ? '0' : ''}${s}`;

    const totalCircumference = 264;
    const timers = game.timers_config || {};
    let maxSec = 60;
    if (game.phase === 'COLLECTIVE_DISCUSSION') maxSec = timers.discussion || 60;
    else if (game.phase === 'ACCUSATION') maxSec = timers.accusation || 30;
    else if (game.phase === 'JUSTIFICATION') maxSec = timers.justification || 30;
    else if (game.phase === 'REVOTE') maxSec = timers.revote || 15;
    else if (game.phase === 'DEBATE') maxSec = timers.debate || 60;
    else if (game.phase === 'SPEECH') maxSec = timers.speech || 45;
    else if (game.phase === 'VOTING') maxSec = timers.voting || 15;
    else if (game.phase === 'VOTE_RESULTS') maxSec = 10;
    else if (game.phase === 'LAST_WORD') maxSec = timers.last_word || 15;

    const progress = Math.max(0, Math.min(1, sec / maxSec));
    const offset = totalCircumference - (progress * totalCircumference);
    svgTimerBar.style.strokeDashoffset = offset;

    if (sec <= 10 && !game.timer.is_paused) {
      svgTimerBar.classList.add('urgent');
      timerBox.classList.add('timer-urgent');
    } else {
      svgTimerBar.classList.remove('urgent');
      timerBox.classList.remove('timer-urgent');
    }
  } else {
    timerBox.style.display = 'none';
  }

  // Last Word Section Handling
  const lastWordSection = document.getElementById('lastWordSection');
  if (lastWordSection) {
    if (game.phase === 'LAST_WORD') {
      lastWordSection.style.display = 'block';
      const lwSpeakerName = document.getElementById('lastWordSpeakerName');
      const btnFinishLw = document.getElementById('btnFinishLastWord');
      if (lwSpeakerName) {
        lwSpeakerName.textContent = (game.last_word && game.last_word.speaker_name) ? game.last_word.speaker_name : 'Изгнанный игрок';
      }
      if (btnFinishLw) {
        const canFinish = state.isHost || (game.last_word && game.last_word.is_me);
        btnFinishLw.style.display = canFinish ? 'inline-flex' : 'none';
      }
    } else {
      lastWordSection.style.display = 'none';
    }
  }

  // Active Speaker Spotlight (SPEECH, COLLECTIVE_DISCUSSION, ACCUSATION, JUSTIFICATION, DEBATE)
  const isSpeech = (game.phase === 'SPEECH' && game.current_speaker);
  const isCollective = (game.phase === 'COLLECTIVE_DISCUSSION');
  const isAccusation = (game.phase === 'ACCUSATION' && game.accusation_speaker);
  const isJustification = (game.phase === 'JUSTIFICATION' && game.justification_status && game.justification_status.active);
  const isDebate = (game.phase === 'DEBATE' && game.debate_speaker);

  if (isSpeech || isCollective || isAccusation || isJustification || isDebate) {
    speakerSpot.style.display = 'flex';
    const spkNameEl = document.getElementById('speakerName');
    const spkProgEl = document.getElementById('speakerProgress');
    const nextBtn = document.getElementById('btnNextSpeaker');
    const passAccBtn = document.getElementById('btnPassAccusation');
    const passJustBtn = document.getElementById('btnPassJustification');
    const passDebateBtn = document.getElementById('btnPassDebate');
    const hostDebateBox = document.getElementById('hostDebateControls');
    const badgeEl = document.getElementById('speakerRevealBadge');
    const skipDiscBtn = document.getElementById('btnHostSkipDiscussion');
    const skipVoteBtn = document.getElementById('btnHostSkipToVoting');

    // Default button display resets
    if (nextBtn) nextBtn.style.display = 'none';
    if (passAccBtn) passAccBtn.style.display = 'none';
    if (passJustBtn) passJustBtn.style.display = 'none';
    if (passDebateBtn) passDebateBtn.style.display = 'none';
    if (skipDiscBtn) skipDiscBtn.style.display = 'none';
    if (skipVoteBtn) skipVoteBtn.style.display = 'none';

    if (isSpeech) {
      if (spkNameEl && spkNameEl.textContent !== game.current_speaker.name) {
        spkNameEl.textContent = game.current_speaker.name;
      }

      const spkProgText = `Спикер ${game.current_speaker.index + 1} из ${game.current_speaker.total}`;
      if (spkProgEl && spkProgEl.getAttribute('data-text') !== spkProgText) {
        spkProgEl.setAttribute('data-text', spkProgText);
        spkProgEl.innerHTML = `
          <span>${spkProgText}</span>
          <span class="audio-bars-wrapper">
            <span class="audio-bar"></span><span class="audio-bar"></span><span class="audio-bar"></span><span class="audio-bar"></span>
          </span>
        `;
      }

      const spStatus = game.speech_status;
      if (badgeEl && spStatus) {
        badgeEl.style.display = 'inline-block';
        badgeEl.textContent = `Вскрыто: ${spStatus.revealed_count} / ${spStatus.required_count}`;
        if (spStatus.can_proceed || state.isHost) {
          badgeEl.className = spStatus.can_proceed ? 'reveal-progress-badge ready' : 'reveal-progress-badge waiting';
          if (nextBtn) {
            nextBtn.disabled = false;
            nextBtn.style.opacity = '1';
            nextBtn.title = 'Передать слово следующему';
          }
        } else {
          badgeEl.className = 'reveal-progress-badge waiting';
          if (nextBtn) {
            nextBtn.disabled = true;
            nextBtn.style.opacity = '0.5';
            nextBtn.title = `Спикер должен вскрыть карты (${spStatus.revealed_count}/${spStatus.required_count}) перед передачей слова!`;
          }
        }
      }

      if (nextBtn) {
        const canAdvance = state.isHost || (game.current_speaker && game.current_speaker.id === state.playerId);
        nextBtn.style.display = canAdvance ? 'inline-flex' : 'none';
      }

    } else if (isCollective) {
      if (spkNameEl) spkNameEl.textContent = '🎙️ Все выжившие (Открытый микрофон)';
      if (spkProgEl) {
        spkProgEl.innerHTML = `<span>КОЛЛЕКТИВНОЕ ОБСУЖДЕНИЕ (60 сек)</span>`;
      }
      if (badgeEl) {
        badgeEl.style.display = 'inline-block';
        badgeEl.className = 'reveal-progress-badge ready';
        badgeEl.textContent = 'Свободный микрофон';
      }
      if (skipDiscBtn) skipDiscBtn.style.display = state.isHost ? 'inline-flex' : 'none';
      if (skipVoteBtn) skipVoteBtn.style.display = state.isHost ? 'inline-flex' : 'none';

    } else if (isAccusation) {
      const accSp = game.accusation_speaker;
      if (spkNameEl && spkNameEl.textContent !== accSp.name) {
        spkNameEl.textContent = accSp.name;
      }
      const accProgText = `ОБВИНЕНИЯ: Спикер ${accSp.index + 1} из ${accSp.total}`;
      if (spkProgEl && spkProgEl.getAttribute('data-text') !== accProgText) {
        spkProgEl.setAttribute('data-text', accProgText);
        spkProgEl.innerHTML = `
          <span>${accProgText}</span>
          <span class="audio-bars-wrapper">
            <span class="audio-bar"></span><span class="audio-bar"></span><span class="audio-bar"></span><span class="audio-bar"></span>
          </span>
        `;
      }
      if (badgeEl) {
        badgeEl.style.display = 'inline-block';
        badgeEl.className = 'reveal-progress-badge ready';
        badgeEl.textContent = '30 сек на претензии';
      }
      if (passAccBtn) {
        const canPass = state.isHost || accSp.is_current;
        passAccBtn.style.display = canPass ? 'inline-flex' : 'none';
      }

    } else if (isJustification) {
      const just = game.justification_status;
      if (spkNameEl && spkNameEl.textContent !== just.speaker_name) {
        spkNameEl.textContent = just.speaker_name || 'Кандидат';
      }
      const justProgText = `ОПРАВДАНИЕ: Кандидат ${just.index + 1} из ${just.total}`;
      if (spkProgEl && spkProgEl.getAttribute('data-text') !== justProgText) {
        spkProgEl.setAttribute('data-text', justProgText);
        spkProgEl.innerHTML = `
          <span>${justProgText}</span>
          <span class="audio-bars-wrapper">
            <span class="audio-bar"></span><span class="audio-bar"></span><span class="audio-bar"></span><span class="audio-bar"></span>
          </span>
        `;
      }
      if (badgeEl) {
        badgeEl.style.display = 'inline-block';
        badgeEl.className = 'reveal-progress-badge ready';
        badgeEl.textContent = '30 сек на защиту';
      }
      if (passJustBtn) {
        const canPass = state.isHost || just.is_current;
        passJustBtn.style.display = canPass ? 'inline-flex' : 'none';
      }

    } else if (isDebate) {
      if (spkNameEl && spkNameEl.textContent !== game.debate_speaker.name) {
        spkNameEl.textContent = game.debate_speaker.name;
      }
      const debProgText = `ДЕБАТЫ: Спикер ${game.debate_speaker.index + 1} из ${game.debate_speaker.total}`;
      if (spkProgEl && spkProgEl.getAttribute('data-text') !== debProgText) {
        spkProgEl.setAttribute('data-text', debProgText);
        spkProgEl.innerHTML = `
          <span>${debProgText}</span>
          <span class="audio-bars-wrapper">
            <span class="audio-bar"></span><span class="audio-bar"></span><span class="audio-bar"></span><span class="audio-bar"></span>
          </span>
        `;
      }
      if (badgeEl) {
        badgeEl.style.display = 'inline-block';
        badgeEl.className = 'reveal-progress-badge ready';
        badgeEl.textContent = '1 минута на выступление';
      }
      const isMyDebateTurn = Boolean(game.debate_speaker.id === state.playerId);
      if (passDebateBtn) {
        passDebateBtn.style.display = (state.isHost || isMyDebateTurn) ? 'inline-flex' : 'none';
      }
    }

    // Host grant debate dropdown
    if (hostDebateBox) {
      if (state.isHost && (isSpeech || isAccusation || isDebate)) {
        hostDebateBox.style.display = 'inline-flex';
        const sel = document.getElementById('selectHostGrantDebate');
        if (sel) {
          const alive = (game.players || []).filter(p => p.is_alive);
          const curVal = sel.value;
          sel.innerHTML = alive.map(p => `
            <option value="${p.id}" ${p.id === curVal ? 'selected' : ''}>${escapeHtml(p.name)}</option>
          `).join('');
        }
      } else {
        hostDebateBox.style.display = 'none';
      }
    }
  } else {
    speakerSpot.style.display = 'none';
  }
}

function renderScenario(game) {
  const scenarioBox = document.getElementById('scenarioSection');
  const headerBar = document.getElementById('scenarioHeaderBar');
  if (game.phase === 'LOBBY' || !game.catastrophe) {
    if (scenarioBox) scenarioBox.style.display = 'none';
    if (headerBar) headerBar.style.display = 'none';
    return;
  }
  if (headerBar) headerBar.style.display = 'flex';
  if (scenarioBox) {
    scenarioBox.style.display = state.scenarioCollapsed ? 'none' : 'grid';
  }

  // Dynamic Catastrophe Theme
  if (game.catastrophe && game.catastrophe.id) {
    const cid = game.catastrophe.id;
    let theme = 'nuclear';
    if (cid.includes('ice') || cid.includes('winter') || cid.includes('cold')) theme = 'ice_age';
    else if (cid.includes('virus') || cid.includes('bio') || cid.includes('zombie') || cid.includes('epidemic')) theme = 'biohazard';
    else if (cid.includes('cosmic') || cid.includes('radiation') || cid.includes('alien')) theme = 'cosmic';
    else if (cid.includes('flare') || cid.includes('fire') || cid.includes('meteor') || cid.includes('asteroid')) theme = 'fire';
    else if (cid.includes('flood') || cid.includes('water') || cid.includes('acid')) theme = 'flood';
    else if (cid.includes('ai') || cid.includes('robot') || cid.includes('nanite') || cid.includes('cyber')) theme = 'ai';
    document.documentElement.setAttribute('data-theme', theme);
  }

  const scenSig = `${game.catastrophe.title}_${game.bunker ? game.bunker.capacity + '_' + game.bunker.threat : ''}`;
  if (state.lastScenarioSig === scenSig) {
    return;
  }
  state.lastScenarioSig = scenSig;

  // Catastrophe Illustration
  const illustrContainer = document.getElementById('catastropheIllustration');
  if (illustrContainer && game.catastrophe) {
    illustrContainer.innerHTML = getCatastropheIllustration(game.catastrophe.id);
  }

  // Catastrophe
  document.getElementById('catastropheTitle').textContent = game.catastrophe.title;
  document.getElementById('catastropheDesc').textContent = game.catastrophe.description;
  document.getElementById('catastropheHazard').textContent = `⚠️ Опасность: ${game.catastrophe.hazard}`;
  document.getElementById('catastropheDuration').textContent = `Срок изоляции: ${game.catastrophe.duration_years} лет`;

  // Bunker
  if (game.bunker) {
    const bTitle = document.getElementById('bunkerTitle');
    if (bTitle) bTitle.textContent = game.bunker.name || 'Бункер';
    document.getElementById('bunkerSize').textContent = `${game.bunker.size_sqm} м²`;
    document.getElementById('bunkerDesc').textContent = game.bunker.description;
    document.getElementById('bunkerThreat').textContent = `⚠️ Угроза бункера: ${game.bunker.threat}`;

    const facContainer = document.getElementById('bunkerFacilities');
    facContainer.innerHTML = '';
    (game.bunker.facilities || []).forEach(fac => {
      const pill = document.createElement('span');
      pill.className = 'facility-pill';
      pill.textContent = `🛠️ ${fac}`;
      facContainer.appendChild(pill);
    });
  }
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>"']/g, m => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[m]);
}

function renderMyDossier(game) {
  const mySection = document.getElementById('myDossierSection');
  const me = game.players.find(p => p.id === state.playerId);

  if (!me || game.phase === 'LOBBY') {
    mySection.style.display = 'none';
    return;
  }
  mySection.style.display = 'block';

  // Silence Warning
  const silenceWarning = document.getElementById('silenceWarning');
  if (silenceWarning) {
    silenceWarning.style.display = (me.is_silenced && me.is_alive) ? 'block' : 'none';
  }

  // Secret Peek Alert
  const secretPeekAlert = document.getElementById('secretPeekAlert');
  const secretPeekText = document.getElementById('secretPeekText');
  if (secretPeekAlert && secretPeekText) {
    if (me.last_peeked && me.is_alive) {
      secretPeekAlert.style.display = 'block';
      secretPeekText.textContent = `${me.last_peeked.target_name || 'Игрок'}: ${me.last_peeked.label || me.last_peeked.category} — «${me.last_peeked.value}» (${me.last_peeked.details || ''})`;
    } else {
      secretPeekAlert.style.display = 'none';
    }
  }

  // Exile Vendetta Box
  const exileVendettaBox = document.getElementById('exileVendettaBox');
  if (exileVendettaBox) {
    const canVendetta = Boolean(game.exile_vendetta && game.exile_vendetta.can_trigger && !me.is_alive);
    exileVendettaBox.style.display = canVendetta ? 'block' : 'none';
  }

  const container = document.getElementById('myCardsList');
  const turnStatusEl = document.getElementById('dossierTurnStatus');

  const isSpeechPhase = (game.phase === 'SPEECH');
  const spStatus = game.speech_status || {};
  const isMyTurn = Boolean(spStatus.is_current_speaker && isSpeechPhase);
  const currentSpeakerName = spStatus.current_speaker_name || (game.current_speaker ? game.current_speaker.name : 'другой игрок');
  const quotaReached = Boolean(spStatus.quota_reached);
  const revealedCount = spStatus.revealed_count || 0;
  const isRoundOne = (game.round_number === 1);
  const profRevealed = Boolean(me.cards.profession && me.cards.profession.revealed);
  const requiredCount = spStatus.required_count || (isRoundOne ? 1 : 2);

  // Dynamic Turn Status Banner (#dossierTurnStatus)
  if (turnStatusEl) {
    if (game.phase === 'LOBBY' || game.phase === 'FINAL') {
      turnStatusEl.style.display = 'none';
    } else if (!me.is_alive) {
      turnStatusEl.className = 'dossier-turn-banner waiting-turn';
      turnStatusEl.style.display = 'flex';
      turnStatusEl.innerHTML = `<span>☠️ <strong>ВЫ ИЗГНАНЫ НА ПОВЕРХНОСТЬ.</strong> Все ваши характеристики рассекречены. Вы наблюдаете за оставшимися колонистами.</span><span class="badge badge-danger">Изгнан</span>`;
    } else if (game.phase === 'LAST_WORD') {
      turnStatusEl.className = 'dossier-turn-banner waiting-turn';
      turnStatusEl.style.display = 'flex';
      turnStatusEl.innerHTML = `<span>🎙️ <strong>ФАЗА ПОСЛЕДНЕГО СЛОВА:</strong> Врата открыты. Изгнанный кандидат произносит прощальную речь.</span><span class="badge badge-amber">Последнее слово</span>`;
    } else if (!isSpeechPhase) {
      turnStatusEl.className = 'dossier-turn-banner waiting-turn';
      turnStatusEl.style.display = 'flex';
      const phaseTitleMap = {
        'COLLECTIVE_DISCUSSION': 'КОЛЛЕКТИВНОЕ ОБСУЖДЕНИЕ',
        'ACCUSATION': 'РАУНД ОБВИНЕНИЙ',
        'DEBATE': 'ОБЩИЕ ДЕБАТЫ',
        'VOTING': 'ТАЙНОЕ ГОЛОСОВАНИЕ',
        'JUSTIFICATION': 'ОПРАВДАТЕЛЬНАЯ РЕЧЬ',
        'REVOTE': 'ПЕРЕГОЛОСОВАНИЕ',
        'VOTE_RESULTS': 'ИТОГИ ГОЛОСОВАНИЯ'
      };
      const pTitle = phaseTitleMap[game.phase] || game.phase;
      turnStatusEl.innerHTML = `<span>🔒 Вскрытие характеристик заблокировано — сейчас фаза <strong>${escapeHtml(pTitle)}</strong>. Черты вскрываются только во время своей речи!</span>`;
    } else if (isMyTurn) {
      if (quotaReached) {
        turnStatusEl.className = 'dossier-turn-banner my-turn-done';
        turnStatusEl.style.display = 'flex';
        turnStatusEl.innerHTML = `<span>✅ <strong>Норма вскрытия на этот ход выполнена!</strong> (${revealedCount} из ${requiredCount}). Завершите вашу речь или передайте слово.</span><span class="badge badge-success">Норма выполнена</span>`;
      } else {
        turnStatusEl.className = 'dossier-turn-banner my-turn-active';
        turnStatusEl.style.display = 'flex';
        if (isRoundOne && !profRevealed) {
          turnStatusEl.innerHTML = `<span>🎙️ <strong>СЕЙЧАС ВАШ ХОД!</strong> В 1-м раунде базовое правило требует вскрыть <strong>Профессию</strong>!</span><span class="badge badge-amber" style="animation: pulseGlowAmber 1.2s infinite;">Вскройте профессию</span>`;
        } else {
          const remaining = Math.max(1, requiredCount - revealedCount);
          turnStatusEl.innerHTML = `<span>🎙️ <strong>СЕЙЧАС ВАШ ХОД!</strong> Раскройте характеристику (${revealedCount} из ${requiredCount}, осталось: ${remaining})</span><span class="badge badge-amber" style="animation: pulseGlowAmber 1.2s infinite;">Вскройте черту</span>`;
        }
      }
    } else {
      turnStatusEl.className = 'dossier-turn-banner waiting-turn';
      turnStatusEl.style.display = 'flex';
      turnStatusEl.innerHTML = `<span>⏳ Сейчас выступает: <strong>${escapeHtml(currentSpeakerName)}</strong>. Ваши кнопки вскрытия заблокированы до вашего хода.</span><span class="badge badge-cyan">Ожидание хода</span>`;
    }
  }

  const cardsSig = [
    JSON.stringify(me.cards),
    game.phase,
    game.round_number,
    me.is_alive,
    me.is_silenced,
    Boolean(me.last_peeked),
    isMyTurn,
    quotaReached,
    revealedCount,
    requiredCount,
    currentSpeakerName
  ].join('::');

  if (state.lastMyCardsSig === cardsSig && container.children.length > 0) {
    return;
  }
  state.lastMyCardsSig = cardsSig;

  container.innerHTML = '';

  // Блок 1 (Вариант 1Б): 11 характеристик персонажа
  const cardCategories = [
    'gender', 'body', 'trait', 'profession', 'health', 
    'hobby', 'phobia', 'big_inventory', 'backpack', 'fact', 
    'special'
  ];
  if ('biology' in me.cards && !('gender' in me.cards)) cardCategories.push('biology');
  if ('baggage' in me.cards && !('backpack' in me.cards)) cardCategories.push('baggage');
  if ('stolen_baggage' in me.cards) cardCategories.push('stolen_baggage');
  if ('traitor' in me.cards) {
    cardCategories.push('traitor');
  }

  cardCategories.forEach(cat => {
    const card = me.cards[cat];
    if (!card) return;

    const isTraitor = (cat === 'traitor');
    const item = document.createElement('div');
    item.className = `dossier-item ${card.revealed ? 'revealed' : 'secret'} ${cat === 'special' ? 'special-card' : ''} ${isTraitor ? 'traitor-card' : ''}`;
    item.setAttribute('data-cat', cat);

    const iconDiv = document.createElement('div');
    iconDiv.className = 'dossier-icon';
    iconDiv.textContent = card.icon || '📜';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'dossier-content';

    const labelDiv = document.createElement('div');
    labelDiv.className = 'dossier-label';
    labelDiv.style.display = 'flex';
    labelDiv.style.alignItems = 'center';
    labelDiv.style.gap = '8px';

    const labelText = document.createElement('span');
    labelText.textContent = card.label || cat;
    labelDiv.appendChild(labelText);

    // Stamp indicator
    if (isTraitor) {
      const stamp = document.createElement('span');
      stamp.className = 'stamp-traitor';
      stamp.textContent = '☣️ ДИВЕРСАНТ';
      labelDiv.appendChild(stamp);
    } else if (card.revealed) {
      const stamp = document.createElement('span');
      stamp.className = 'stamp-revealed';
      stamp.textContent = 'РАССЕКРЕЧЕНО';
      labelDiv.appendChild(stamp);
    } else {
      const stamp = document.createElement('span');
      stamp.className = 'stamp-classified';
      stamp.textContent = 'СЕКРЕТНО';
      labelDiv.appendChild(stamp);
    }

    const valDiv = document.createElement('div');
    valDiv.className = 'dossier-val';
    valDiv.textContent = card.value;

    const subDiv = document.createElement('div');
    subDiv.className = 'dossier-sub';
    subDiv.textContent = card.details;

    contentDiv.appendChild(labelDiv);
    contentDiv.appendChild(valDiv);
    contentDiv.appendChild(subDiv);

    item.appendChild(iconDiv);
    item.appendChild(contentDiv);

    // Reveal Button (for standard hidden cards)
    if (!card.revealed && cat !== 'special' && !isTraitor) {
      const btnRev = document.createElement('button');

      if (!isSpeechPhase) {
        btnRev.className = 'btn btn-secondary btn-sm reveal-btn btn-locked';
        btnRev.disabled = true;
        btnRev.textContent = '🔒 Недоступно';
        btnRev.title = 'Вскрывать характеристики можно только во время фазы защитной речи!';
      } else if (!isMyTurn) {
        btnRev.className = 'btn btn-secondary btn-sm reveal-btn btn-locked';
        btnRev.disabled = true;
        btnRev.textContent = '🔒 Не ваш ход';
        btnRev.title = `Сейчас выступает ${currentSpeakerName}. Дождитесь своей очереди речи!`;
      } else if (quotaReached) {
        btnRev.className = 'btn btn-secondary btn-sm reveal-btn btn-quota-done';
        btnRev.disabled = true;
        btnRev.textContent = `✅ Норма (${revealedCount}/${requiredCount})`;
        btnRev.title = `Вы уже раскрыли максимум характеристик на этот ход (${requiredCount}). Больше открыть нельзя!`;
      } else if (isRoundOne && !profRevealed && cat !== 'profession') {
        btnRev.className = 'btn btn-secondary btn-sm reveal-btn btn-locked';
        btnRev.disabled = true;
        btnRev.textContent = '🔒 Нужна Профессия';
        btnRev.title = 'В 1-м раунде сначала необходимо обязательно открыть Профессию!';
      } else {
        // Allowed to reveal
        btnRev.disabled = false;
        if (isRoundOne && cat === 'profession') {
          btnRev.className = 'btn btn-primary btn-sm reveal-btn pulse-ready';
          btnRev.textContent = '👁️ Вскрыть Профессию';
          btnRev.title = 'Рассекретить профессию!';
        } else {
          btnRev.className = 'btn btn-amber btn-sm reveal-btn pulse-ready';
          const nextNum = revealedCount + 1;
          btnRev.textContent = `👁️ Вскрыть (${nextNum}/${requiredCount})`;
          btnRev.title = `Рассекретить характеристику (${nextNum} из ${requiredCount})`;
        }

        btnRev.addEventListener('click', (e) => {
          e.stopPropagation();
          // Foolproof protection: disable immediately to prevent double-click / rapid spam
          btnRev.disabled = true;
          btnRev.textContent = '⏳ Вскрытие...';
          sendAction('REVEAL_CARD', { category: cat });
          item.classList.add('card-revealed-anim');
          window.soundFX.playCardReveal();
          window.soundFX.playStampSlam();
        });
      }
      item.appendChild(btnRev);
    } else if (cat === 'special' && !card.used) {
      const btnUse = document.createElement('button');
      btnUse.className = 'btn btn-primary btn-sm reveal-btn';
      btnUse.textContent = '⚡ Применить';
      btnUse.addEventListener('click', () => handleUseSpecial(card));
      item.appendChild(btnUse);
    }

    container.appendChild(item);
  });
}

// --- Special Card Modal Execution ---
function handleUseSpecial(card) {
  if (card.target === 'player') {
    const aliveOther = state.gameData.players.filter(p => p.id !== state.playerId && p.is_alive);
    if (!aliveOther.length) {
      showToast('Нет подходящих кандидатов для применения карты', 'warning');
      return;
    }

    openTargetPickerModal(
      `Спецкарта: «${card.value}»`,
      `Выберите цель среди кандидатов для применения эффекта карты:`,
      aliveOther,
      (targetId) => {
        sendAction('USE_SPECIAL_CARD', { target_player_id: targetId });
        const targetPlayer = aliveOther.find(p => p.id === targetId);
        showToast(`Спецкарта «${card.value}» применена на: ${targetPlayer ? targetPlayer.name : ''}!`);
        window.soundFX.playStampSlam();
      }
    );
  } else {
    if (confirm(`Активировать спецкарту «${card.value}»?`)) {
      sendAction('USE_SPECIAL_CARD', {});
      showToast(`Спецкарта «${card.value}» активирована!`);
      window.soundFX.playStampSlam();
    }
  }
}

// --- Voting Section & Vote Results ---
function renderVotingSection(game) {
  const voteSection = document.getElementById('votingSection');
  const voteResultsSection = document.getElementById('voteResultsSection');
  const tieNotice = document.getElementById('tiebreakerNotice');
  const thresholdNotice = document.getElementById('thresholdNotice');
  const progressBanner = document.getElementById('votingProgressBanner');
  const btnAbstain = document.getElementById('btnVoteAbstain');
  const me = game.players.find(p => p.id === state.playerId);

  // If in VOTE_RESULTS phase: show vote results screen, hide voting form
  if (game.phase === 'VOTE_RESULTS') {
    if (voteSection) voteSection.style.display = 'none';
    if (voteResultsSection) {
      renderVoteResultsSection(game);
    }
    return;
  }

  // If not in VOTING or REVOTE phase or player not alive: hide both
  const isVoting = (game.phase === 'VOTING');
  const isRevote = (game.phase === 'REVOTE');
  if (voteResultsSection) voteResultsSection.style.display = 'none';

  if ((!isVoting && !isRevote) || !me || !me.is_alive) {
    if (voteSection) voteSection.style.display = 'none';
    return;
  }
  voteSection.style.display = 'block';

  // Live Voting Progress Banner
  if (progressBanner && game.voting_status) {
    const cast = game.voting_status.votes_cast || 0;
    const total = game.voting_status.total_voters || 0;
    const allDone = game.voting_status.all_voted;
    const phaseLabel = isRevote ? 'Переголосование' : 'Голосование';
    if (allDone) {
      progressBanner.innerHTML = `<span>✅ Все участники (${total}) проголосовали! Переход к подсчету...</span>`;
    } else {
      progressBanner.innerHTML = `<span>🗳️ ${phaseLabel}: принято <strong>${cast} из ${total}</strong> (15 сек таймер, AFK = голос против себя)</span>`;
    }
  }

  // Tiebreaker notice
  const isTie = game.vote_results && game.vote_results.is_tie;
  if (tieNotice) {
    tieNotice.style.display = isTie ? 'block' : 'none';
  }

  // Threshold and Rules Notice (Вариант 5Б)
  if (thresholdNotice) {
    thresholdNotice.className = 'threshold-notice';
    if (isRevote) {
      thresholdNotice.innerHTML = `⚖️ <strong>ПЕРЕГОЛОСОВАНИЕ (15 сек):</strong> Голосуйте строго за одного из кандидатов, произнесших оправдательную речь. Побеждает простое большинство голосов!`;
    } else {
      thresholdNotice.innerHTML = `🛡️ <strong>ПРАВИЛО 70% И ОПРАВДАНИЕ:</strong> При ≥ 70% голосов кандидат изгоняется моментально! При < 70% или ничьей запускается оправдательная речь (30 сек) и переголосование (15 сек). Таймер: 15 сек. Не успевшие голосуют против себя!`;
    }
  }

  // Wire Abstain Button (only in standard voting)
  if (btnAbstain) {
    if (isRevote) {
      btnAbstain.style.display = 'none';
    } else {
      btnAbstain.style.display = 'block';
      if (state.selectedVoteTarget === 'ABSTAIN') {
        btnAbstain.classList.add('selected');
        btnAbstain.innerHTML = `<span>✅ ВЫ ВОЗДЕРЖАЛИСЬ</span> (Голос за сохранение всех)`;
      } else {
        btnAbstain.classList.remove('selected');
        btnAbstain.innerHTML = `<span>⚪ ВОЗДЕРЖАТЬСЯ</span> (Пропустить голос / Никого не выгонять)`;
      }
      btnAbstain.onclick = () => {
        state.selectedVoteTarget = 'ABSTAIN';
        sendAction('CAST_VOTE', { target_id: 'ABSTAIN' });
        window.soundFX.playVoteCast();
        showToast('Вы воздержались от голосования');
        renderVotingSection(game);
      };
    }
  }

  // Wire Skip Round Button in Round 1 (Вариант 5Б)
  const btnSkipRound = document.getElementById('btnVoteSkipRound');
  if (btnSkipRound) {
    const skipInfo = game.skip_round_info || {};
    if (skipInfo.can_skip && isVoting) {
      btnSkipRound.style.display = 'block';
      const votedSkip = (state.selectedVoteTarget === 'SKIP_ROUND');
      if (votedSkip) {
        btnSkipRound.classList.add('selected');
        btnSkipRound.innerHTML = `<span>✅ ВЫ ЗА ПРОПУСК ИЗГНАНИЯ (${skipInfo.skip_votes}/${skipInfo.needed})</span><div style="font-size: 11px; margin-top: 3px;">Во 2-м раунде произойдет ДВОЙНОЕ изгнание!</div>`;
      } else {
        btnSkipRound.classList.remove('selected');
        btnSkipRound.innerHTML = `<span>⏭️ ПРОПУСТИТЬ ИЗГНАНИЕ (${skipInfo.skip_votes}/${skipInfo.needed})</span><div style="font-size: 11px; margin-top: 3px;">Большинство оставит всех в бункере, но во 2-м раунде будет ДВОЙНОЕ изгнание!</div>`;
      }
      btnSkipRound.onclick = () => {
        state.selectedVoteTarget = 'SKIP_ROUND';
        sendAction('CAST_VOTE', { target_id: 'SKIP_ROUND' });
        window.soundFX.playVoteCast();
        showToast('Вы проголосовали за пропуск изгнания в 1-м раунде');
        renderVotingSection(game);
      };
    } else {
      btnSkipRound.style.display = 'none';
    }
  }

  const grid = document.getElementById('voteCandidatesGrid');
  grid.innerHTML = '';

  let candidates = game.players.filter(p => p.id !== state.playerId && p.is_alive && !p.has_immunity);
  if (isRevote && game.revote_status && game.revote_status.candidates && game.revote_status.candidates.length > 0) {
    candidates = candidates.filter(p => game.revote_status.candidates.includes(p.id));
  } else if (isTie && game.vote_results && game.vote_results.top_candidates && game.vote_results.top_candidates.length > 0) {
    candidates = candidates.filter(p => game.vote_results.top_candidates.includes(p.id));
  }

  candidates.forEach(cand => {
    const btn = document.createElement('button');
    btn.className = `vote-btn ${state.selectedVoteTarget === cand.id ? 'selected' : ''}`;
    
    const profCard = cand.cards && cand.cards.profession;
    const profText = (profCard && profCard.revealed) ? profCard.value : 'Профессия скрыта';

    btn.innerHTML = `
      <span class="vote-cand-action">🚫 ИЗГНАТЬ</span>
      <span class="vote-cand-name">${escapeHtml(cand.name)}</span>
      <span class="vote-cand-prof">${escapeHtml(profText)}</span>
    `;
    btn.addEventListener('click', () => {
      openVoteConfirmModal(cand, () => {
        state.selectedVoteTarget = cand.id;
        sendAction('CAST_VOTE', { target_id: cand.id });
        window.soundFX.playVoteCast();
        showToast(`Вы проголосовали за изгнание: ${cand.name}`);
        renderVotingSection(game);
      });
    });
    grid.appendChild(btn);
  });
}

function renderVoteResultsSection(game) {
  const section = document.getElementById('voteResultsSection');
  if (!section) return;
  section.style.display = 'block';

  const res = game.vote_results || {};
  const outcomeBanner = document.getElementById('voteOutcomeBanner');
  const countdownEl = document.getElementById('voteResultsCountdown');
  const tallyGrid = document.getElementById('voteTallyGrid');
  const hostControls = document.getElementById('voteResultsHostControls');
  const nextRoundBtn = document.getElementById('btnHostNextRoundNow');

  const secLeft = game.timer ? game.timer.seconds_left : 0;
  if (countdownEl) {
    countdownEl.textContent = `⏳ Следующий раунд через ${secLeft} сек...`;
  }

  if (outcomeBanner) {
    if (res.veto_used) {
      outcomeBanner.className = 'threshold-notice threshold-failed-alert';
      outcomeBanner.innerHTML = `🛡️ <strong>ПРАВО ВЕТО АКТИВИРОВАНО!</strong> Изгнание заблокировано спецкартой. Никто не покидает бункер!`;
    } else if (res.skipped_round) {
      outcomeBanner.className = 'threshold-notice tie-alert';
      outcomeBanner.innerHTML = `⏭️ <strong>ИЗГНАНИЕ ПРОПУЩЕНО:</strong> Большинство проголосовало за пропуск в 1-м раунде! Все остаются в бункере, но во 2-м раунде произойдет <strong>ДВОЙНОЕ ИЗГНАНИЕ</strong>!`;
    } else if (res.double_elimination) {
      outcomeBanner.className = 'threshold-notice elimination-alert';
      outcomeBanner.innerHTML = `💀💀 <strong>ДВОЙНОЕ ИЗГНАНИЕ:</strong> По итогам голосования бункер покидают сразу двое: <strong>${escapeHtml(res.eliminated_name)}</strong>!`;
    } else if (res.instant_exile) {
      outcomeBanner.className = 'threshold-notice elimination-alert';
      outcomeBanner.innerHTML = `⚡ <strong>МОМЕНТАЛЬНОЕ ИЗГНАНИЕ (≥70%):</strong> Кандидат <strong>${escapeHtml(res.eliminated_name)}</strong> набрал ${res.max_percent}% голосов и изгоняется без права на оправдание!`;
    } else if (res.revote_completed) {
      if (res.tie_broken_by === 'dice' || res.is_tie) {
        outcomeBanner.className = 'threshold-notice tie-alert';
        outcomeBanner.innerHTML = `🎲 <strong>НИЧЬЯ В ПЕРЕГОЛОСОВАНИИ:</strong> Кандидаты набрали поровну голосов. Жребий судьбы решил исход: бункер покидает <strong>${escapeHtml(res.eliminated_name)}</strong>! Ожидание возможного Вето...`;
      } else {
        outcomeBanner.className = 'threshold-notice elimination-alert';
        outcomeBanner.innerHTML = `⚖️ <strong>ИТОГИ ПЕРЕГОЛОСОВАНИЯ:</strong> Большинство голосов отдано за изгнание: <strong>${escapeHtml(res.eliminated_name)}</strong>! Ожидание возможного Вето...`;
      }
    } else if (res.threshold_failed) {
      outcomeBanner.className = 'threshold-notice threshold-failed-alert';
      outcomeBanner.innerHTML = `⚠️ <strong>НИКТО НЕ ИЗГНАН:</strong> Все участники воздержались от голосования. Никто не покидает бункер!`;
    } else if (res.is_tie) {
      outcomeBanner.className = 'threshold-notice tie-alert';
      outcomeBanner.innerHTML = `⚖️ <strong>РАВЕНСТВО ГОЛОСОВ:</strong> Кандидаты набрали равное количество голосов.`;
    } else if (res.eliminated_name) {
      outcomeBanner.className = 'threshold-notice elimination-alert';
      outcomeBanner.innerHTML = `🚫 <strong>КАНДИДАТ НА ИЗГНАНИЕ:</strong> Большинством голосов выбран <strong>${escapeHtml(res.eliminated_name)}</strong>! Ожидание возможного Вето...`;
    } else {
      outcomeBanner.className = 'threshold-notice';
      outcomeBanner.innerHTML = `ℹ️ Подсчет голосов завершен. Переход к следующему раунду...`;
    }
  }

  if (tallyGrid) {
    tallyGrid.innerHTML = '';
    const items = res.detailed_tally || [];

    items.forEach(t => {
      const isElim = (res.eliminated_id === t.player_id && !res.threshold_failed && !res.veto_used);
      const row = document.createElement('div');
      row.className = 'vote-tally-item';

      const fill = document.createElement('div');
      fill.className = `vote-tally-fill ${isElim ? 'fill-eliminated' : ''}`;
      fill.style.width = `${Math.min(100, Math.max(2, t.percent))}%`;

      const nameSpan = document.createElement('div');
      nameSpan.className = 'vote-tally-name';
      const badgeText = (res.tie_broken_by === 'dice' || res.is_tie) ? 'Жребий: на выход' : 'Кандидат на выход';
      nameSpan.innerHTML = `${isElim ? (res.tie_broken_by === 'dice' ? '🎲 ' : '🚫 ') : '👤 '} ${escapeHtml(t.player_name)} ${isElim ? `<span class="badge badge-danger">${badgeText}</span>` : ''}`;

      const statSpan = document.createElement('div');
      statSpan.className = 'vote-tally-stat';
      statSpan.textContent = `${t.votes} гол. (${t.percent}%)`;

      row.appendChild(fill);
      row.appendChild(nameSpan);
      row.appendChild(statSpan);
      tallyGrid.appendChild(row);
    });

    // Abstain row
    if (res.abstain_count !== undefined) {
      const aliveCount = game.alive_count || (game.players ? game.players.filter(p => p.is_alive).length : 1) || 1;
      const absPct = Math.round(((res.abstain_count / aliveCount) * 100) * 10) / 10;
      const absRow = document.createElement('div');
      absRow.className = 'vote-tally-item';

      const absFill = document.createElement('div');
      absFill.className = 'vote-tally-fill fill-abstain';
      absFill.style.width = `${Math.min(100, Math.max(0, absPct))}%`;

      const absName = document.createElement('div');
      absName.className = 'vote-tally-name';
      absName.style.color = 'var(--accent-cyan)';
      absName.innerHTML = `⚪ Воздержались от изгнания`;

      const absStat = document.createElement('div');
      absStat.className = 'vote-tally-stat';
      absStat.style.color = 'var(--accent-cyan)';
      absStat.textContent = `${res.abstain_count} чел. (${absPct}%)`;

      absRow.appendChild(absFill);
      absRow.appendChild(absName);
      absRow.appendChild(absStat);
      tallyGrid.appendChild(absRow);
    }
  }

  // Host button to proceed immediately
  if (hostControls) {
    if (state.isHost) {
      hostControls.style.display = 'flex';
      if (nextRoundBtn) {
        nextRoundBtn.onclick = () => {
          nextRoundBtn.disabled = true;
          sendAction('CONFIRM_ELIMINATION', {});
          showToast('Переход к следующему раунду...');
        };
      }
    } else {
      hostControls.style.display = 'none';
    }
  }
}

// --- All Players Grid ---
function renderPlayersGrid(game) {
  const grid = document.getElementById('allPlayersGrid');
  const spkId = (game.phase === 'SPEECH' && game.current_speaker) ? game.current_speaker.id : ((game.phase === 'DEBATE' && game.debate_speaker) ? game.debate_speaker.id : '');
  const sig = game.players.map(p => `${p.id}_${p.is_alive}_${p.connected}_${p.is_silenced}_${Object.values(p.cards||{}).map(c=>c.revealed).join('')}`).join('|') + `__${spkId}_${state.isHost}_${game.phase}`;
  
  if (state.lastPlayersSig === sig && grid.children.length > 0) {
    return;
  }
  state.lastPlayersSig = sig;
  grid.innerHTML = '';

  game.players.forEach(p => {
    const isSpeechSpeaker = (game.phase === 'SPEECH' && game.current_speaker && game.current_speaker.id === p.id);
    const isDebateSpeaker = (game.phase === 'DEBATE' && game.debate_speaker && game.debate_speaker.id === p.id);
    const isSpeaker = isSpeechSpeaker || isDebateSpeaker;
    const isEliminated = !p.is_alive;

    const card = document.createElement('div');
    card.className = `player-card ${isSpeaker ? 'active-speaker' : ''} ${isEliminated ? 'eliminated' : ''}`;
    card.title = 'Нажмите для подробного досье';
    card.addEventListener('click', (e) => {
      // Don't open if clicked on host action button inside
      if (e.target.tagName === 'BUTTON') return;
      openPlayerDossierModal(p);
    });

    // Stamped eliminated banner
    if (isEliminated) {
      const elimBanner = document.createElement('div');
      elimBanner.className = 'stamp-eliminated-banner stamp-anim';
      elimBanner.textContent = 'ИЗГНАН НА ПОВЕРХНОСТЬ';
      card.appendChild(elimBanner);
    }

    // Header
    const header = document.createElement('div');
    header.className = 'player-header';

    const nameDiv = document.createElement('div');
    nameDiv.className = 'player-name';
    nameDiv.innerHTML = `
      ${p.connected ? '<span class="live-dot success"></span>' : '<span class="live-dot danger"></span>'}
      ${escapeHtml(p.name)}
      ${p.is_host ? '<span class="brand-badge">Ведущий</span>' : ''}
      ${p.is_silenced ? '<span class="badge badge-danger" style="font-size: 10px; margin-left: 4px;">🔇 Молчание</span>' : ''}
      ${isDebateSpeaker ? '<span class="badge badge-cyan" style="font-size: 10px; margin-left: 4px;">🎤 Спикер</span>' : ''}
    `;

    const statusBadge = document.createElement('span');
    statusBadge.className = `player-status-badge ${p.is_alive ? 'badge-alive' : 'badge-eliminated'}`;
    statusBadge.textContent = p.is_alive ? 'В игре' : 'Изгнан';

    header.appendChild(nameDiv);
    header.appendChild(statusBadge);
    card.appendChild(header);

    // Cards list
    const list = document.createElement('div');
    list.className = 'dossier-list';

    Object.entries(p.cards || {}).forEach(([cat, c]) => {
      const row = document.createElement('div');
      row.className = `dossier-item ${c.revealed ? 'revealed' : 'secret'}`;
      row.setAttribute('data-cat', cat);
      row.innerHTML = `
        <div class="dossier-icon">${c.icon || '❓'}</div>
        <div class="dossier-content">
          <div class="dossier-label">${c.label}</div>
          <div class="dossier-val">${c.value}</div>
          ${c.revealed && c.details ? `<div class="dossier-sub">${c.details}</div>` : ''}
        </div>
      `;
      list.appendChild(row);
    });

    card.appendChild(list);

    const hint = document.createElement('div');
    hint.className = 'player-inspect-hint';
    hint.textContent = '🔍 Досье';
    card.appendChild(hint);

    // Host manual actions in Lobby (Kick)
    if (state.isHost && game.phase === 'LOBBY' && p.id !== state.playerId) {
      const actionRow = document.createElement('div');
      actionRow.style.marginTop = '10px';
      actionRow.style.display = 'flex';
      actionRow.style.gap = '6px';

      const btnKick = document.createElement('button');
      btnKick.className = 'btn btn-danger btn-sm';
      btnKick.style.flex = '1';
      btnKick.textContent = '❌ Кикнуть';
      btnKick.title = `Исключить игрока ${p.name} из лобби`;
      btnKick.addEventListener('click', (e) => {
        e.stopPropagation();
        if (confirm(`Удалить игрока ${p.name} из комнаты?`)) {
          sendAction('HOST_KICK', { player_id: p.id });
        }
      });
      actionRow.appendChild(btnKick);
      card.appendChild(actionRow);
    }

    // Host manual actions during game
    if (state.isHost && game.phase !== 'LOBBY' && game.phase !== 'FINAL') {
      const actionRow = document.createElement('div');
      actionRow.style.marginTop = '10px';
      actionRow.style.display = 'flex';
      actionRow.style.gap = '6px';

      if (p.is_alive) {
        const btnElim = document.createElement('button');
        btnElim.className = 'btn btn-danger btn-sm';
        btnElim.style.flex = '1';
        btnElim.textContent = '❌ Изгнать';
        btnElim.addEventListener('click', (e) => {
          e.stopPropagation();
          if (confirm(`Принудительно изгнать игрока ${p.name}?`)) {
            sendAction('HOST_ELIMINATE', { target_id: p.id });
          }
        });
        actionRow.appendChild(btnElim);
      } else {
        const btnRestore = document.createElement('button');
        btnRestore.className = 'btn btn-secondary btn-sm';
        btnRestore.style.flex = '1';
        btnRestore.textContent = '✨ Помиловать';
        btnRestore.addEventListener('click', (e) => {
          e.stopPropagation();
          sendAction('HOST_RESTORE', { target_id: p.id });
        });
        actionRow.appendChild(btnRestore);
      }

      card.appendChild(actionRow);
    }

    grid.appendChild(card);
  });
}

function renderGameLog(game) {
  const box = document.getElementById('gameLogBox');
  const logs = game.game_log || [];
  if (state.lastLogLength === logs.length && box.children.length > 0) {
    return;
  }
  state.lastLogLength = logs.length;
  box.innerHTML = '';
  logs.forEach(entry => {
    const row = document.createElement('div');
    row.className = `log-entry ${entry.type || 'info'}`;
    row.innerHTML = `<span class="log-time">[${entry.timestamp}]</span> <strong>${entry.title}:</strong> ${entry.text}`;
    box.appendChild(row);
  });
  box.scrollTop = box.scrollHeight;
}

function renderFinalScreen(game) {
  const finalSec = document.getElementById('finalScreenSection');
  if (game.phase !== 'FINAL' || !game.final_evaluation) {
    finalSec.style.display = 'none';
    return;
  }
  finalSec.style.display = 'block';

  const evalData = game.final_evaluation;
  const gauge = document.getElementById('survivalGauge');
  const targetPercent = evalData.survival_percent || 0;
  gauge.className = `survival-gauge ${evalData.is_success ? 'success' : 'fail'}`;

  // Counter animation for gauge
  if (!gauge.getAttribute('data-animated')) {
    gauge.setAttribute('data-animated', 'true');
    let cur = 0;
    const step = Math.max(1, Math.round(targetPercent / 30));
    const timer = setInterval(() => {
      cur += step;
      if (cur >= targetPercent) {
        cur = targetPercent;
        clearInterval(timer);
      }
      gauge.textContent = `${cur}%`;
    }, 30);
  } else {
    gauge.textContent = `${targetPercent}%`;
  }

  // Animated Vault Door Graphic
  const vaultGraphic = document.getElementById('finalVaultDoorGraphic');
  const vaultIcon = document.getElementById('finalVaultDoorIcon');
  const vaultStatus = document.getElementById('finalVaultDoorStatus');
  if (vaultGraphic) {
    vaultGraphic.className = `vault-door-graphic ${evalData.is_success ? 'sealed' : 'breached'}`;
  }
  if (vaultIcon) {
    vaultIcon.textContent = evalData.is_success ? '🛡️' : '⚠️';
  }
  if (vaultStatus) {
    vaultStatus.textContent = evalData.is_success
      ? 'ГЕРМОШЛЮЗ НАДЕЖНО ЗАПЕРТ • КОЛОНИЯ ВЫЖИЛА'
      : 'УГРОЗА ПРОРЫВА • БУНКЕР НЕ ВЫДЕРЖАЛ';
    vaultStatus.style.color = evalData.is_success ? 'var(--accent-success)' : 'var(--accent-danger)';
  }

  document.getElementById('finalTitle').textContent = evalData.title;
  document.getElementById('finalText').textContent = evalData.text;

  // Achievements Breakdown
  const achList = document.getElementById('finalAchievementsList');
  if (achList) {
    achList.innerHTML = '';
    const achs = evalData.achievements || [];
    if (achs.length === 0) {
      achList.innerHTML = '<div style="color: var(--text-muted); font-size: 13px; grid-column: 1 / -1;">Нет особых заслуг у этой группы колонистов.</div>';
    } else {
      achs.forEach(ach => {
        const card = document.createElement('div');
        card.className = 'achievement-card';
        card.innerHTML = `
          <div class="achievement-badge">${ach.badge || '🎖️'}</div>
          <div class="achievement-body">
            <div class="achievement-player">👤 ${escapeHtml(ach.player_name || 'Выживший')}</div>
            <div class="achievement-title">${escapeHtml(ach.title)}</div>
            <div class="achievement-desc">${escapeHtml(ach.desc)}</div>
          </div>
        `;
        achList.appendChild(card);
      });
    }
  }

  // Pros and cons
  const prosList = document.getElementById('finalProsList');
  prosList.innerHTML = '';
  (evalData.pros || []).forEach(p => {
    const li = document.createElement('li');
    li.textContent = `✅ ${p}`;
    prosList.appendChild(li);
  });

  const consList = document.getElementById('finalConsList');
  consList.innerHTML = '';
  (evalData.cons || []).forEach(c => {
    const li = document.createElement('li');
    li.textContent = `❌ ${c}`;
    consList.appendChild(li);
  });
}

// --- Discord Report Generator ---
function generateDiscordReport() {
  if (!state.gameData || !state.gameData.final_evaluation) return;

  const g = state.gameData;
  const ev = g.final_evaluation;
  const alive = g.players.filter(p => p.is_alive).map(p => `• **${p.name}**`).join('\n');
  const dead = g.players.filter(p => !p.is_alive).map(p => `• ~~${p.name}~~`).join('\n');

  let report = `☣️ **ИТОГИ ИГРЫ «БУНКЕР» // КОМНАТА ${g.room_code}** ☣️\n`;
  report += `☄️ **Катастрофа:** ${g.catastrophe ? g.catastrophe.title : 'Неизвестно'}\n`;
  report += `🛡️ **Бункер:** Мест: ${g.bunker_capacity} | Срок изоляции: ${g.catastrophe ? g.catastrophe.duration_years : 5} лет\n`;
  report += `📊 **Шанс на выживание колонии:** **${ev.survival_percent}%** (${ev.title})\n\n`;
  report += `🟢 **Выжили в бункере:**\n${alive || 'Никто'}\n\n`;
  report += `🔴 **Остались на поверхности:**\n${dead || 'Никто'}\n\n`;
  if (ev.traitor_in_bunker) {
    report += `⚠️ **Диверсант (${ev.traitor_name}) проник в бункер и саботировал спасение!**\n\n`;
  }
  if (ev.achievements && ev.achievements.length > 0) {
    report += `🏆 **Заслуги и титулы выживших:**\n`;
    ev.achievements.forEach(a => {
      report += `• ${a.badge || '🎖️'} **${a.player_name || 'Выживший'}** — ${a.title}: ${a.desc}\n`;
    });
    report += `\n`;
  }

  navigator.clipboard.writeText(report).then(() => {
    showToast('📋 Отчет для Discord успешно скопирован в буфер обмена!');
  }).catch(() => {
    prompt('Скопируйте отчет для Discord:', report);
  });
}

// --- Modals Logic ---
function setupModals() {
  // Target Picker
  document.getElementById('btnTargetPickerClose').addEventListener('click', closeModals);
  document.getElementById('btnTargetPickerCancel').addEventListener('click', closeModals);

  // Vote Confirm
  document.getElementById('btnVoteConfirmClose').addEventListener('click', closeModals);
  document.getElementById('btnVoteConfirmCancel').addEventListener('click', closeModals);

  // Player Dossier
  document.getElementById('btnPlayerDossierClose').addEventListener('click', closeModals);
  document.getElementById('btnPlayerDossierDismiss').addEventListener('click', closeModals);

  // Event Dice Modal
  const btnDiceClose = document.getElementById('btnDiceModalClose');
  if (btnDiceClose) btnDiceClose.addEventListener('click', closeModals);
  const btnDiceAccept = document.getElementById('btnDiceModalAccept');
  if (btnDiceAccept) btnDiceAccept.addEventListener('click', closeModals);

  // Event History Modal
  const btnJournal = document.getElementById('btnOpenEventsJournal');
  if (btnJournal) btnJournal.addEventListener('click', openEventHistoryModal);
  const btnHistoryClose = document.getElementById('btnEventHistoryClose');
  if (btnHistoryClose) btnHistoryClose.addEventListener('click', closeModals);
  const btnHistoryDismiss = document.getElementById('btnEventHistoryDismiss');
  if (btnHistoryDismiss) btnHistoryDismiss.addEventListener('click', closeModals);

  // Achievements Modal
  const btnAchHUD = document.getElementById('btnOpenAchievements');
  if (btnAchHUD) btnAchHUD.addEventListener('click', openAchievementsModal);
  const btnAchClose = document.getElementById('btnAchievementsClose');
  if (btnAchClose) btnAchClose.addEventListener('click', closeModals);
  const btnAchDismiss = document.getElementById('btnAchievementsDismiss');
  if (btnAchDismiss) btnAchDismiss.addEventListener('click', closeModals);
}

function closeModals() {
  document.querySelectorAll('.modal-overlay').forEach(m => m.style.display = 'none');
  state.activeModal = null;
}

function openAchievementsModal() {
  closeModals();
  const modal = document.getElementById('modalAchievements');
  const list = document.getElementById('achievementsModalList');
  if (list) {
    list.innerHTML = '';
    ALL_ACHIEVEMENTS.forEach(ach => {
      const card = document.createElement('div');
      card.className = 'achievement-card';
      card.innerHTML = `
        <div class="achievement-badge">${ach.badge}</div>
        <div>
          <div class="achievement-title">${escapeHtml(ach.title)}</div>
          <div class="achievement-desc">${escapeHtml(ach.desc)}</div>
        </div>
      `;
      list.appendChild(card);
    });
  }
  if (modal) modal.style.display = 'flex';
}

function openTargetPickerModal(title, promptText, candidates, onConfirm) {
  closeModals();
  const modal = document.getElementById('modalTargetPicker');
  document.getElementById('targetPickerTitle').textContent = title;
  document.getElementById('targetPickerPrompt').textContent = promptText;

  const listContainer = document.getElementById('targetPickerList');
  listContainer.innerHTML = '';

  let selectedId = candidates.length > 0 ? candidates[0].id : null;

  candidates.forEach(c => {
    const item = document.createElement('div');
    item.className = `modal-candidate-item ${c.id === selectedId ? 'selected' : ''}`;
    item.innerHTML = `
      <div>
        <strong style="color: #fff; font-size: 14px;">${c.name}</strong>
      </div>
      <span class="live-dot success"></span>
    `;
    item.addEventListener('click', () => {
      selectedId = c.id;
      listContainer.querySelectorAll('.modal-candidate-item').forEach(el => el.classList.remove('selected'));
      item.classList.add('selected');
    });
    listContainer.appendChild(item);
  });

  const confirmBtn = document.getElementById('btnTargetPickerConfirm');
  const newConfirmBtn = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

  newConfirmBtn.addEventListener('click', () => {
    if (selectedId) {
      closeModals();
      onConfirm(selectedId);
    }
  });

  modal.style.display = 'flex';
}

function openVoteConfirmModal(candidate, onConfirm) {
  closeModals();
  const modal = document.getElementById('modalVoteConfirm');
  const profCard = candidate.cards && candidate.cards.profession;
  const profText = (profCard && profCard.revealed) ? profCard.value : 'Профессия скрыта';
  const nameEl = document.getElementById('voteConfirmCandidateName');
  if (nameEl) {
    nameEl.innerHTML = `${escapeHtml(candidate.name)} <div style="font-size: 14px; font-weight: 500; color: var(--accent-cyan); margin-top: 4px;">(${escapeHtml(profText)})</div>`;
  }

  const sendBtn = document.getElementById('btnVoteConfirmSend');
  const newSendBtn = sendBtn.cloneNode(true);
  sendBtn.parentNode.replaceChild(newSendBtn, sendBtn);

  newSendBtn.addEventListener('click', () => {
    closeModals();
    onConfirm();
  });

  modal.style.display = 'flex';
}

function openPlayerDossierModal(player) {
  closeModals();
  const modal = document.getElementById('modalPlayerDossier');
  document.getElementById('dossierModalPlayerName').textContent = `ЛИЧНОЕ ДЕЛО: ${player.name}`;
  document.getElementById('dossierModalStatus').textContent = player.is_alive ? 'СТАТУС: В БУНКЕРЕ' : 'СТАТУС: ИЗГНАН';
  document.getElementById('dossierModalStatus').style.color = player.is_alive ? 'var(--accent-success)' : 'var(--accent-danger)';

  const list = document.getElementById('dossierModalCardsList');
  list.innerHTML = '';

  Object.entries(player.cards || {}).forEach(([cat, card]) => {
    const isTraitor = (cat === 'traitor');
    const row = document.createElement('div');
    row.className = `dossier-item ${card.revealed ? 'revealed' : 'secret'} ${isTraitor ? 'traitor-card' : ''}`;
    row.innerHTML = `
      <div class="dossier-icon">${card.icon || '❓'}</div>
      <div class="dossier-content">
        <div class="dossier-label">
          ${card.label || cat}
          ${card.revealed ? '<span class="stamp-revealed">РАССЕКРЕЧЕНО</span>' : '<span class="stamp-classified">СЕКРЕТНО</span>'}
        </div>
        <div class="dossier-val">${card.value}</div>
        ${card.revealed && card.details ? `<div class="dossier-sub">${card.details}</div>` : ''}
      </div>
    `;
    list.appendChild(row);
  });

  modal.style.display = 'flex';
}

// --- Host & Game Control Button Handlers ---
function setupGameAndHostButtons() {
  const btnStart = document.getElementById('btnStartGame');
  if (btnStart) {
    btnStart.addEventListener('click', () => {
      const capInput = document.getElementById('inputBunkerCapacity');
      const cap = capInput ? (parseInt(capInput.value, 10) || 3) : 3;
      const checkTraitor = document.getElementById('checkLobbyTraitor');
      const enableTraitor = checkTraitor ? checkTraitor.checked : false;
      const checkEvents = document.getElementById('checkLobbyEvents');
      const enableEvents = checkEvents ? checkEvents.checked : true;
      const selectGameMode = document.getElementById('selectGameMode');
      const gameMode = selectGameMode ? selectGameMode.value : 'STANDARD';
      const selectSpeechTime = document.getElementById('selectSpeechTime');
      const speechDuration = selectSpeechTime ? parseInt(selectSpeechTime.value, 10) : 45;
      const selectDebateTime = document.getElementById('selectDebateTime');
      const debateDuration = selectDebateTime ? parseInt(selectDebateTime.value, 10) : 60;
      const selectVotingTime = document.getElementById('selectVotingTime');
      const votingDuration = selectVotingTime ? parseInt(selectVotingTime.value, 10) : 15;

      sendAction('START_GAME', {
        capacity: cap,
        enable_traitor: enableTraitor,
        enable_events: enableEvents,
        game_mode: gameMode,
        speech_duration: speechDuration,
        debate_duration: debateDuration,
        voting_duration: votingDuration
      });
      window.soundFX.playVaultDoor();
    });
  }

  const btnAddBots = document.getElementById('btnAddBotsLobby');
  if (btnAddBots) {
    btnAddBots.onclick = () => window.addBotsToCurrentRoom(5);
  }

  const selectGameMode = document.getElementById('selectGameMode');
  if (selectGameMode) {
    selectGameMode.addEventListener('change', () => {
      const mode = selectGameMode.value;
      const sp = document.getElementById('selectSpeechTime');
      const deb = document.getElementById('selectDebateTime');
      const vot = document.getElementById('selectVotingTime');
      if (mode === 'METEORITE') {
        if (sp) sp.value = '30';
        if (deb) deb.value = '30';
        if (vot) vot.value = '30';
        showToast('🚀 Режим «Метеорит»: быстрые таймеры (30с), профессия и здоровье будут вскрыты со старта!');
      } else {
        if (sp) sp.value = '45';
        if (deb) deb.value = '60';
        if (vot) vot.value = '60';
      }
    });
  }

  const btnPause = document.getElementById('btnHostPause');
  if (btnPause) {
    btnPause.addEventListener('click', () => {
      sendAction('HOST_PAUSE_TIMER', {});
    });
  }

  const btnAddTime = document.getElementById('btnHostAddTime');
  if (btnAddTime) {
    btnAddTime.addEventListener('click', () => {
      sendAction('HOST_ADD_TIME', { seconds: 30 });
      showToast('+30 секунд добавлено к таймеру');
    });
  }

  const btnRestartDebate = document.getElementById('btnHostRestartDebate');
  if (btnRestartDebate) {
    btnRestartDebate.addEventListener('click', () => {
      sendAction('HOST_RESTART_PHASE', {});
      showToast('Дебаты перезапущены!');
    });
  }

  const btnTiebreaker = document.getElementById('btnHostTiebreaker');
  if (btnTiebreaker) {
    btnTiebreaker.addEventListener('click', () => {
      sendAction('HOST_TIEBREAKER', {});
      showToast('Запущен тайбрейк между кандидатами с равными голосами!');
    });
  }

  const btnNextRound = document.getElementById('btnHostNextRoundNow');
  if (btnNextRound) {
    btnNextRound.addEventListener('click', () => {
      sendAction('CONFIRM_ELIMINATION', {});
      showToast('Переход к следующему раунду...');
    });
  }

  const btnNextSpk = document.getElementById('btnNextSpeaker');
  if (btnNextSpk) {
    btnNextSpk.addEventListener('click', () => {
      sendAction('NEXT_SPEAKER', {});
    });
  }

  // Last Word button
  const btnFinishLastWord = document.getElementById('btnFinishLastWord');
  if (btnFinishLastWord) {
    btnFinishLastWord.addEventListener('click', () => {
      sendAction('FINISH_LAST_WORD', {});
      showToast('Последнее слово завершено');
    });
  }

  // Secret Peek Announcement
  const btnAnnouncePeeked = document.getElementById('btnAnnouncePeeked');
  if (btnAnnouncePeeked) {
    btnAnnouncePeeked.addEventListener('click', () => {
      sendAction('ANNOUNCE_PEEKED', {});
      showToast('Подсмотренная характеристика раскрыта всем игрокам!');
      const box = document.getElementById('secretPeekAlert');
      if (box) box.style.display = 'none';
    });
  }

  // Exile Vendetta
  const btnTriggerVendetta = document.getElementById('btnTriggerVendetta');
  if (btnTriggerVendetta) {
    btnTriggerVendetta.addEventListener('click', () => {
      if (confirm('Совершить диверсию против бункера (-5% к выживанию оставшихся)? Это действие необратимо!')) {
        sendAction('EXILE_VENDETTA', {});
        showToast('Диверсия совершена! Вы отомстили бункеру.');
        window.soundFX.playSiren();
      }
    });
  }

  // --- Debate, Accusation & Justification Controls ---
  const btnPassAccusation = document.getElementById('btnPassAccusation');
  if (btnPassAccusation) {
    btnPassAccusation.addEventListener('click', () => {
      sendAction('NEXT_ACCUSATION_SPEAKER', {});
    });
  }

  const btnPassJustification = document.getElementById('btnPassJustification');
  if (btnPassJustification) {
    btnPassJustification.addEventListener('click', () => {
      sendAction('NEXT_JUSTIFICATION_SPEAKER', {});
    });
  }

  const btnPassDebate = document.getElementById('btnPassDebate');
  if (btnPassDebate) {
    btnPassDebate.addEventListener('click', () => {
      sendAction('NEXT_DEBATE_SPEAKER', {});
    });
  }

  const btnHostEndDebate = document.getElementById('btnHostEndDebate');
  if (btnHostEndDebate) {
    btnHostEndDebate.addEventListener('click', () => {
      const ph = state.gameData ? state.gameData.phase : '';
      if (ph === 'SPEECH') {
        sendAction('HOST_FORCE_NEXT_SPEAKER', {});
        showToast('Слово передано следующему оратору');
      } else if (ph === 'COLLECTIVE_DISCUSSION') {
        sendAction('START_ACCUSATION', {});
        showToast('Переход к раунду обвинений');
      } else if (ph === 'JUSTIFICATION') {
        sendAction('NEXT_JUSTIFICATION_SPEAKER', {});
        showToast('Оправдательная речь завершена');
      } else {
        sendAction('NEXT_ACCUSATION_SPEAKER', {});
        showToast('Слово передано следующему спикеру');
      }
    });
  }

  const btnHostSkipDisc = document.getElementById('btnHostSkipDiscussion');
  if (btnHostSkipDisc) {
    btnHostSkipDisc.addEventListener('click', () => {
      sendAction('START_ACCUSATION', {});
      showToast('Переход к раунду обвинений');
    });
  }

  const btnHostSkipVote = document.getElementById('btnHostSkipToVoting');
  if (btnHostSkipVote) {
    btnHostSkipVote.addEventListener('click', () => {
      sendAction('START_VOTING', {});
      showToast('Переход к тайному голосованию');
    });
  }

  const btnHostRestartDebateTime = document.getElementById('btnHostRestartDebateTime');
  if (btnHostRestartDebateTime) {
    btnHostRestartDebateTime.addEventListener('click', () => {
      sendAction('HOST_ADD_TIME', { seconds: 60 });
      showToast('Спикеру добавлено 60 секунд');
    });
  }

  const btnHostGrantDebate = document.getElementById('btnHostGrantDebate');
  if (btnHostGrantDebate) {
    btnHostGrantDebate.addEventListener('click', () => {
      const sel = document.getElementById('selectHostGrantDebate');
      if (sel && sel.value) {
        sendAction('GRANT_DEBATE_SPEAKER', { target_player_id: sel.value });
        showToast('Слово передано выбранному игроку');
      }
    });
  }

  const btnHostForceNext = document.getElementById('btnHostForceNextSpeaker');
  if (btnHostForceNext) {
    btnHostForceNext.addEventListener('click', () => {
      sendAction('HOST_FORCE_NEXT_SPEAKER', {});
      showToast('Слово передано дальше');
    });
  }

  const btnHostSkipDiscBar = document.getElementById('btnHostSkipDiscBar');
  if (btnHostSkipDiscBar) {
    btnHostSkipDiscBar.addEventListener('click', () => {
      sendAction('START_ACCUSATION', {});
      showToast('Переход к раунду обвинений');
    });
  }

  const btnForceVoting = document.getElementById('btnForceVoting');
  if (btnForceVoting) {
    btnForceVoting.addEventListener('click', () => {
      sendAction('START_VOTING', {});
    });
  }

  const btnForceDebate = document.getElementById('btnForceDebate');
  if (btnForceDebate) {
    btnForceDebate.addEventListener('click', () => {
      if (state.gameData && state.gameData.phase === 'COLLECTIVE_DISCUSSION') {
        sendAction('START_ACCUSATION', {});
        showToast('Переход к раунду обвинений');
      } else {
        sendAction('START_DEBATE', {});
      }
    });
  }

  const btnTriggerSiren = document.getElementById('btnTriggerSiren');
  if (btnTriggerSiren) {
    btnTriggerSiren.addEventListener('click', () => {
      sendAction('PLAY_SOUND_ALERT', { sound: 'siren' });
      window.soundFX.playSiren();
      triggerScreenShake();
      showToast('🚨 Сирена тревоги включена!');
    });
  }

  const checkLobbyTraitor = document.getElementById('checkLobbyTraitor');
  if (checkLobbyTraitor) {
    checkLobbyTraitor.addEventListener('change', () => {
      sendAction('HOST_TOGGLE_TRAITOR', { enable_traitor: checkLobbyTraitor.checked });
      showToast(checkLobbyTraitor.checked ? 'Режим предателя включен' : 'Режим предателя отключен');
    });
  }

  const checkLobbyEvents = document.getElementById('checkLobbyEvents');
  if (checkLobbyEvents) {
    checkLobbyEvents.addEventListener('change', () => {
      sendAction('HOST_TOGGLE_EVENTS', { enabled: checkLobbyEvents.checked });
      showToast(checkLobbyEvents.checked ? 'Случайные события включены' : 'Случайные события отключены');
    });
  }

  const btnTriggerEvent = document.getElementById('btnHostTriggerEvent');
  if (btnTriggerEvent) {
    btnTriggerEvent.addEventListener('click', () => {
      sendAction('HOST_TRIGGER_EVENT', {});
      showToast('🎲 Вытянуто новое испытание!');
    });
  }
}
const bindHostControlEvents = setupGameAndHostButtons;

// =====================================================================
// === EVENT RENDERING & RESOLUTION (v3.0) ===
// =====================================================================

function renderEventContentHtml(activeEv, odds, game, eventsState, isSurface, isSkipped) {
  if (!isSurface) {
    // Внутри бункера: факторы живых игроков
    const posList = (odds.positive_factors || []).map(f => `
      <div class="mod-badge mod-badge--pos">
        <span class="mod-delta">+${f.delta}%</span>
        <div><strong>${f.player_name}:</strong> ${f.title} (${f.card_name || ''})</div>
      </div>
    `).join('');

    const negList = (odds.negative_factors || []).map(f => `
      <div class="mod-badge mod-badge--neg">
        <span class="mod-delta">${f.delta}%</span>
        <div><strong>${f.player_name}:</strong> ${f.title} (${f.card_name || ''})</div>
      </div>
    `).join('');

    return `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; margin-top: 12px;">
        <div class="duel-side duel-side--bunker">
          <div class="duel-side-title" style="color: var(--accent-success);">🛡️ Факторы защиты (+${odds.positive_factors ? odds.positive_factors.reduce((a, b) => a + b.delta, 0) : 0}%)</div>
          <div class="modifiers-list">
            ${posList || '<div style="color: var(--text-muted); font-size: 11px;">Нет открытых защитных карт у выживших</div>'}
          </div>
        </div>
        <div class="duel-side duel-side--exiles">
          <div class="duel-side-title" style="color: var(--accent-danger);">⚠️ Факторы риска (-${odds.negative_factors ? Math.abs(odds.negative_factors.reduce((a, b) => a + b.delta, 0)) : 0}%)</div>
          <div class="modifiers-list">
            ${negList || '<div style="color: var(--text-muted); font-size: 11px;">Нет открытых факторов риска</div>'}
          </div>
        </div>
      </div>
    `;
  } else {
    // На поверхности: Дуэль (Доброволец бункера vs Озлобленные изгнанники)
    const vol = odds.volunteer;
    const volName = vol ? vol.name : 'Не назначен';
    const volId = vol ? vol.id : '';

    const alive = (game.players || []).filter(p => p.is_alive);
    const optionsHtml = alive.map(p => `
      <option value="${p.id}" ${p.id === volId ? 'selected' : ''}>${p.name}</option>
    `).join('');

    const volMods = (vol && vol.factors ? vol.factors : []).map(f => `
      <div class="mod-badge ${f.delta > 0 ? 'mod-badge--pos' : 'mod-badge--neg'}">
        <span class="mod-delta">${f.delta > 0 ? '+' : ''}${f.delta}%</span>
        <div>${f.title} (${f.card_name || ''})</div>
      </div>
    `).join('');

    const exilesList = (odds.exiles || []).map(ex => {
      const fHtml = (ex.factors || []).map(f => `
        <div class="mod-badge ${f.delta === 0 ? 'mod-badge--neutral' : 'mod-badge--neg'}">
          <span class="mod-delta">${f.delta === 0 ? '0%' : f.delta + '%'}</span>
          <div>${f.title}</div>
        </div>
      `).join('');

      return `
        <div style="margin-bottom: 10px; background: rgba(255,51,102,0.05); padding: 6px 10px; border-radius: 4px;">
          <div style="font-size: 12px; font-weight: 700; color: #fff; margin-bottom: 4px;">
            ${ex.name} ${ex.is_alive_surface ? '🔥 (Жив в пустошах)' : '💀 (Погиб от среды)'}
          </div>
          <div class="modifiers-list">
            ${fHtml}
          </div>
        </div>
      `;
    }).join('');

    const skipBannerHtml = isSkipped ? `
      <div style="background: rgba(255, 170, 0, 0.12); border: 1px solid var(--accent-amber); border-radius: var(--radius-sm); padding: 10px 14px; margin-bottom: 12px; color: var(--accent-amber); text-align: center; font-weight: 700; font-size: 13px;">
        🚫 ВЫЛАЗКА ПРОПУЩЕНА: Гермошлюз запечатан. Никто не выходит на поверхность — риск для здоровья исключен (0% к шансам бункера).
      </div>
    ` : '';

    return `
      ${skipBannerHtml}
      <div class="duel-container">
        <!-- Bunker volunteer side -->
        <div class="duel-side duel-side--bunker">
          <div class="duel-side-title" style="color: var(--accent-success);">🛡️ Доброволец на вылазку</div>
          ${state.isHost ? `
            <div class="volunteer-select-box">
              <label style="font-size: 11px; color: var(--text-muted);">Выбрать добровольца:</label>
              <select id="selectEventVolunteer" onchange="window.handleVolunteerChange(this.value)">
                ${optionsHtml}
              </select>
            </div>
          ` : `
            <div style="font-size: 13px; font-weight: 700; color: var(--accent-cyan); margin-bottom: 10px;">
              Герой вылазки: ${volName}
            </div>
          `}
          <div class="modifiers-list">
            ${volMods || '<div style="color: var(--text-muted); font-size: 11px;">Нет открытых бонусов у добровольца</div>'}
          </div>
        </div>

        <!-- VS Badge -->
        <div class="duel-vs-badge">VS</div>

        <!-- Hostile Exiles side -->
        <div class="duel-side duel-side--exiles">
          <div class="duel-side-title" style="color: var(--accent-danger);">💀 Озлобленные изгнанники снаружи</div>
          <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 8px;">
            Озлоблены за изгнание и пытаются сорвать вылазку или забрать контейнер себе!
          </div>
          ${exilesList || '<div style="color: var(--text-muted); font-size: 11px;">На поверхности пока никого нет (пустоши пусты)</div>'}
        </div>
      </div>
    `;
  }
}

function renderEventActionsHtml(activeEv, isSurface, isSkipped) {
  if (state.isHost) {
    return `
      <div class="crisis-actions-bar">
        <button class="btn-resolve-event" onclick="window.handleHostResolveEvent()">
          🎲 БРОСИТЬ КУБИК d100 (Разрешить испытание)
        </button>
        ${isSurface ? `
          <button class="btn ${isSkipped ? 'btn-warning' : 'btn-secondary'} btn-sm" onclick="sendAction('SKIP_SORTIE', { skip: ${!isSkipped} })">
            ${isSkipped ? '↩️ Возобновить вылазку' : '🚫 Пропустить вылазку'}
          </button>
        ` : ''}
        <button class="btn btn-secondary btn-sm" onclick="sendAction('HOST_TRIGGER_EVENT', {})">
          🔄 Сменить испытание
        </button>
        <span style="font-size: 11px; color: var(--text-muted); margin-left: auto;">
          🎲 Испытание автоматически разрешится после голосования (или бросьте вручную)
        </span>
      </div>
    `;
  } else {
    return `
      <div class="crisis-actions-bar">
        <span style="font-size: 12px; color: var(--accent-amber); font-weight: 600;">
          ${isSkipped ? '🚫 Вылазка отменена ведущим: бункер запечатан, здоровье добровольца в безопасности.' : '🎲 Кубик d100 бросится автоматически сразу после голосования и изгнания! Вскрывайте карты, чтобы повлиять на шансы.'}
        </span>
      </div>
    `;
  }
}

function renderActiveEvent(game) {
  const container = document.getElementById('eventChallengeSection');
  if (!container) return;

  const eventsState = game.events_state;
  const activeEv = eventsState ? eventsState.active_event : null;

  // Update HUD badge
  const badgeEl = document.getElementById('hudEventsBadge');
  const hist = (eventsState && eventsState.resolved_history) ? eventsState.resolved_history : [];
  if (badgeEl) badgeEl.textContent = hist.length;

  if (!activeEv) {
    container.style.display = 'none';
    container.innerHTML = '';
    state.lastActiveEventId = null;
    state.lastActiveEventOddsSig = null;
    return;
  }

  container.style.display = 'block';

  const odds = eventsState.current_odds || {
    base_chance: activeEv.base_chance || 35,
    final_chance: activeEv.base_chance || 35,
    positive_factors: [],
    negative_factors: [],
    volunteer: null,
    exiles: []
  };

  const isSurface = (activeEv.type === 'SURFACE_EVENT');
  const isSkipped = Boolean(eventsState.is_sortie_skipped);
  const cardClass = isSurface ? 'crisis-card--surface' : 'crisis-card--bunker';
  const badgeClass = isSurface ? 'crisis-badge--surface' : 'crisis-badge--bunker';
  const badgeText = isSurface ? '🪂 ВЫЛАЗКА НА ПОВЕРХНОСТЬ' : '🚨 АВАРИЯ В БУНКЕРЕ';

  const chanceVal = odds.final_chance;
  const chanceTier = chanceVal >= 60 ? 'high' : chanceVal >= 40 ? 'mid' : 'low';

  const isNewEvent = (state.lastActiveEventId !== activeEv.id);
  const oddsSig = `${activeEv.id}_${odds.final_chance}_${eventsState.volunteer_id}_${isSkipped}_${(odds.positive_factors||[]).length}_${(odds.negative_factors||[]).length}_${(odds.exiles||[]).length}_${state.isHost}`;

  const existingCard = container.querySelector('.crisis-card');

  // Если карточка уже существует для этого события, обновляем по месту (без пересоздания DOM и без перезапуска анимаций)
  if (!isNewEvent && existingCard && existingCard.dataset.eventId === activeEv.id) {
    if (state.lastActiveEventOddsSig === oddsSig) {
      return;
    }
    state.lastActiveEventOddsSig = oddsSig;

    const pctValEl = existingCard.querySelector('.odds-percent-val');
    if (pctValEl) {
      pctValEl.textContent = `${chanceVal}%`;
      pctValEl.className = `odds-percent-val ${chanceTier}`;
    }
    const fillEl = existingCard.querySelector('.odds-progress-fill');
    if (fillEl) {
      fillEl.style.width = `${chanceVal}%`;
      fillEl.className = `odds-progress-fill ${chanceTier}`;
    }

    const dynContentEl = existingCard.querySelector('#eventDynamicContent');
    if (dynContentEl) {
      dynContentEl.innerHTML = renderEventContentHtml(activeEv, odds, game, eventsState, isSurface, isSkipped);
    }
    const actionsEl = existingCard.querySelector('#eventActionControls');
    if (actionsEl) {
      actionsEl.innerHTML = renderEventActionsHtml(activeEv, isSurface, isSkipped);
    }
    return;
  }

  state.lastActiveEventId = activeEv.id;
  state.lastActiveEventOddsSig = oddsSig;

  container.innerHTML = `
    <div class="crisis-card ${cardClass}" data-event-id="${activeEv.id}">
      <div class="crisis-header">
        <div class="crisis-icon">${activeEv.title.split(' ')[0] || '🎲'}</div>
        <div class="crisis-title-wrap">
          <div class="crisis-badge ${badgeClass}">${badgeText}</div>
          <div class="crisis-title">${activeEv.title}</div>
          <div class="crisis-desc">${activeEv.description}</div>
          ${activeEv.requirements_desc ? `<div class="crisis-reqs">🎯 <strong>Требования:</strong> ${activeEv.requirements_desc}</div>` : ''}
        </div>
      </div>

      <!-- Live Odds Progress Meter -->
      <div class="odds-meter-container">
        <div class="odds-meter-header">
          <span class="odds-percent-label">Шанс успешного разрешения (Базовый: ${activeEv.base_chance}%)</span>
          <span class="odds-percent-val ${chanceTier}">${chanceVal}%</span>
        </div>
        <div class="odds-progress-track">
          <div class="odds-progress-fill ${chanceTier}" style="width: ${chanceVal}%;"></div>
        </div>
      </div>

      <div id="eventDynamicContent">
        ${renderEventContentHtml(activeEv, odds, game, eventsState, isSurface, isSkipped)}
      </div>

      <div id="eventActionControls">
        ${renderEventActionsHtml(activeEv, isSurface, isSkipped)}
      </div>
    </div>
  `;
}

function handleVolunteerChange(volunteerId) {
  sendAction('ASSIGN_VOLUNTEER', { volunteer_id: volunteerId });
  showToast('Доброволец на вылазку изменен!');
}
window.handleVolunteerChange = handleVolunteerChange;

function handleHostResolveEvent() {
  const evState = state.gameData ? state.gameData.events_state : null;
  const activeEv = evState ? evState.active_event : null;
  if (!activeEv) return;

  sendAction('RESOLVE_EVENT', {});
}
window.handleHostResolveEvent = handleHostResolveEvent;

function openDiceModal(result) {
  closeModals();
  const modal = document.getElementById('modalEventDice');
  const title = document.getElementById('diceModalTitle');
  const numDisplay = document.getElementById('diceNumberDisplay');
  const targetDisplay = document.getElementById('diceTargetDisplay');
  const outcomeContainer = document.getElementById('diceOutcomeContainer');
  const acceptBtn = document.getElementById('btnDiceModalAccept');

  title.textContent = `🎲 ${result.event_title || result.title}`;
  if (result.is_skipped) {
    targetDisplay.textContent = `Вылазка была отменена бункером`;
  } else {
    targetDisplay.textContent = `Требуется выбросить: ≤ ${result.chance_required}% для успеха`;
  }

  outcomeContainer.style.display = 'none';
  acceptBtn.style.display = 'none';
  numDisplay.classList.add('dice-rolling');
  numDisplay.style.color = '#fff';

  modal.style.display = 'flex';

  if (result.is_skipped) {
    numDisplay.classList.remove('dice-rolling');
    showDiceOutcome(result);
    return;
  }

  let rollCount = 0;
  const rollInterval = setInterval(() => {
    numDisplay.textContent = Math.floor(Math.random() * 100) + 1;
    rollCount++;
    if (rollCount > 18) {
      clearInterval(rollInterval);
      numDisplay.classList.remove('dice-rolling');
      showDiceOutcome(result);
    }
  }, 75);
}

function showDiceOutcome(result) {
  const numDisplay = document.getElementById('diceNumberDisplay');
  const outcomeContainer = document.getElementById('diceOutcomeContainer');
  const outcomeTitle = document.getElementById('diceOutcomeTitle');
  const outcomeDesc = document.getElementById('diceOutcomeDesc');
  const boostNotice = document.getElementById('diceBoostNotice');
  const acceptBtn = document.getElementById('btnDiceModalAccept');

  outcomeContainer.style.display = 'block';

  if (result.is_skipped) {
    numDisplay.textContent = '🚫';
    numDisplay.style.color = 'var(--accent-amber)';
    outcomeTitle.style.color = 'var(--accent-amber)';
    outcomeTitle.textContent = result.title;
    outcomeDesc.textContent = result.description;
    boostNotice.style.display = 'none';
  } else if (result.is_success) {
    numDisplay.textContent = result.roll;
    numDisplay.style.color = 'var(--accent-success)';
    outcomeTitle.style.color = 'var(--accent-success)';
    outcomeTitle.textContent = `✅ ${result.title} (Выброшено: ${result.roll} из ${result.chance_required}%)`;
    outcomeDesc.textContent = `${result.description} (+${result.score_delta}% к шансам бункера)`;
    boostNotice.style.display = 'none';
    window.soundFX.playVaultDoor();
  } else {
    numDisplay.textContent = result.roll;
    numDisplay.style.color = 'var(--accent-danger)';
    outcomeTitle.style.color = 'var(--accent-danger)';
    outcomeTitle.textContent = `❌ ${result.title} (Выброшено: ${result.roll} из ${result.chance_required}%)`;
    outcomeDesc.textContent = `${result.description} (${result.score_delta}% к шансам бункера)`;

    if (result.boosted_tags && result.boosted_tags.length > 0) {
      boostNotice.style.display = 'block';
      boostNotice.innerHTML = `
        <strong>🔥 КРИТИЧЕСКИЙ БУСТ ПРОФЕССИЙ:</strong><br>
        ${result.boost_reason || 'Специалисты по устранению последствий теперь жизненно необходимы бункеру!'}
      `;
    } else {
      boostNotice.style.display = 'none';
    }
    window.soundFX.playSiren();
    triggerScreenShake();
  }

  acceptBtn.style.display = 'inline-block';
}

function openEventHistoryModal() {
  closeModals();
  const modal = document.getElementById('modalEventHistory');
  const list = document.getElementById('eventHistoryList');
  list.innerHTML = '';

  const hist = (state.gameData && state.gameData.events_state && state.gameData.events_state.resolved_history)
    ? state.gameData.events_state.resolved_history
    : [];

  if (hist.length === 0) {
    list.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 30px 10px;">В этой партии пока не произошло ни одного испытания.</div>';
  } else {
    hist.forEach((item) => {
      const res = item.result;
      const isSuccess = res.is_success;
      const div = document.createElement('div');
      div.className = `event-history-item ${isSuccess ? 'success' : 'failure'}`;
      div.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;">
          <strong style="color: ${isSuccess ? 'var(--accent-success)' : 'var(--accent-danger)'}; font-family: var(--font-hud);">
            ${isSuccess ? '✅ УСПЕХ' : '❌ ПРОВАЛ'}: ${res.event_title}
          </strong>
          <span style="font-size: 11px; color: var(--text-muted); font-family: var(--font-hud);">Раунд ${item.round} // ${item.timestamp}</span>
        </div>
        <div style="font-size: 13px; color: var(--text-main); margin-bottom: 6px;">${res.description}</div>
        <div style="font-size: 11px; color: var(--text-muted);">
          Кубик d100: <strong style="color: #fff;">${res.roll}</strong> (Требовалось: ≤ ${res.chance_required}%) | Влияние на бункер: <strong style="color: ${isSuccess ? 'var(--accent-success)' : 'var(--accent-danger)'};">${res.score_delta > 0 ? '+' : ''}${res.score_delta}%</strong>
        </div>
        ${res.boost_reason ? `<div style="margin-top: 6px; font-size: 11px; color: var(--accent-amber);">${res.boost_reason}</div>` : ''}
      `;
      list.appendChild(div);
    });
  }

  modal.style.display = 'flex';
}

// --- Utilities ---
function copyDiscordLink() {
  let url = window.location.href;
  if (state.networkInfo && state.networkInfo.external_url && state.roomCode) {
    url = `${state.networkInfo.external_url}/?room=${state.roomCode}`;
  } else if (state.networkInfo && state.networkInfo.external_ip && state.roomCode) {
    url = `http://${state.networkInfo.external_ip}:${state.networkInfo.port}?room=${state.roomCode}`;
  } else if (state.roomCode) {
    url = `${window.location.origin}/?room=${state.roomCode}`;
  }

  navigator.clipboard.writeText(url).then(() => {
    showToast('📋 Ссылка для друзей в Discord скопирована в буфер обмена!');
  }).catch(() => {
    prompt('Скопируйте ссылку для Discord:', url);
  });
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `<span>${type === 'danger' ? '⚠️' : 'ℹ️'}</span> <div>${message}</div>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// --- Cinematic Prologue Modal ---
function triggerCinematicPrologue(game) {
  const modal = document.getElementById('cinematicPrologueModal');
  if (!modal || !game.catastrophe) return;

  const videoBg = document.getElementById('prologueVideoBg');
  const titleEl = document.getElementById('prologueCatastropheTitle');
  const descEl = document.getElementById('prologueCatastropheDesc');
  const gridEl = document.getElementById('prologueHeroesGrid');
  const noticeEl = document.getElementById('prologueCapacityNotice');
  const enterBtn = document.getElementById('btnPrologueEnter');
  const closeBtn = document.getElementById('btnPrologueClose');

  if (titleEl) titleEl.textContent = game.catastrophe.title;
  if (descEl) {
    descEl.textContent = `${game.catastrophe.description} Опасность: ${game.catastrophe.hazard}. Срок изоляции: ${game.catastrophe.duration_years} лет.`;
  }

  if (noticeEl) {
    noticeEl.textContent = `⚠️ Бункер вмещает только ${game.bunker_capacity} человек из ${game.alive_count}! Остальные будут изгнаны на смертоносную поверхность.`;
  }

  if (gridEl) {
    gridEl.innerHTML = '';
    (game.players || []).forEach(p => {
      const hero = document.createElement('div');
      hero.className = 'prologue-hero-card';
      hero.innerHTML = `
        <div style="font-size: 22px; margin-bottom: 4px;">👤</div>
        <div style="font-weight: 700; font-size: 13px; color: #fff;">${p.name}</div>
        <div style="font-size: 10px; color: var(--accent-cyan); margin-top: 2px;">В ОЧЕРЕДИ К ШЛЮЗУ</div>
      `;
      gridEl.appendChild(hero);
    });
  }

  // Load and play catastrophe video
  if (videoBg && game.catastrophe.id) {
    const catId = game.catastrophe.id;
    videoBg.poster = `/static/images/catastrophes/${catId}.jpg`;
    videoBg.src = `/static/videos/catastrophes/${catId}.mp4`;
    videoBg.currentTime = 0;
    const playPromise = videoBg.play();
    if (playPromise !== undefined) {
      playPromise.catch(err => {
        console.log('Video autoplay prevented or suppressed, fallback to poster:', err);
      });
    }
  }

  modal.style.display = 'flex';
  window.soundFX.playSiren();

  const handleClose = () => {
    modal.style.display = 'none';
    if (videoBg) {
      videoBg.pause();
    }
    if (window.soundFX && window.soundFX.playVaultDoor) window.soundFX.playVaultDoor();
    sendAction('ENTER_BUNKER');
  };

  if (enterBtn) enterBtn.onclick = handleClose;
  if (closeBtn) closeBtn.onclick = handleClose;
}
