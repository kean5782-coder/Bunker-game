/**
 * Bunker V4.6 — local audio mixer and "Realistic bunker" soundscape.
 * Asset recordings are ORIGINAL SYNTHESIS, not Freesound field recordings.
 * No audio request leaves the game server; no API credentials are used.
 * Only public phase/catastrophe identifiers affect ambience, never odds/cards.
 */
class BunkerSoundFX {
  constructor() {
    this.ctx = null;
    this.masterGain = null;
    this.effectsGain = null;
    this.notificationsGain = null;
    this.mediaGain = null;
    this.ambientGain = null;
    this.ambientNode = null;
    this._unlocked = false;
    this._disposed = false;
    this._buffers = new Map();
    this._loads = new Map();
    this._failures = new Set();
    this._loops = new Map();
    this._details = new Set();
    this._media = new Map();
    this._accentTimer = null;
    this._lastAccent = '';
    this._scene = {phase:'WELCOME', catastrophe:'', prologue:false, review:false, connected:true};
    this._ambientWanted = true;
    this._previewTimer = null;
    this._preview = false;
    const read = (key) => { try { return localStorage.getItem(key); } catch (_) { return null; } };
    this._read = read;
    this._write = (key, value) => { try {localStorage.setItem(key,String(value));} catch (_) {} };
    let saved = {};
    try { saved = JSON.parse(read('bunker_audio_v46') || '{}') || {}; } catch (_) {}
    if (typeof saved !== 'object' || Array.isArray(saved)) saved = {};
    const unit = (x, def) => typeof x === 'number' && Number.isFinite(x) ? Math.min(1, Math.max(0,x)) : def;
    const bool = (x, def) => typeof x === 'boolean' ? x : def;
    const legacyVol = parseFloat(read('bunker_sound_volume'));
    this.volume = unit(saved.master, Number.isFinite(legacyVol) ? unit(legacyVol,.55) : .55);
    this.enabled = bool(saved.enabled, read('bunker_sound_enabled') !== 'false');
    this.ambientEnabled = bool(saved.ambientEnabled, read('bunker_ambient_enabled') !== 'false');
    this.consent = read('bunker_audio_consent_v46') === 'yes' || read('bunker_audio_consent_v46') === 'silent';
    this.settings = {
      ambient: unit(saved.ambient,.35), effects: unit(saved.effects,.55), notifications:unit(saved.notifications,.65), video:unit(saved.video,.50),
      effectsEnabled:bool(saved.effectsEnabled,true), notificationsEnabled:bool(saved.notificationsEnabled,true), videoEnabled:bool(saved.videoEnabled,true),
      accents:bool(saved.accents,true), exterior:bool(saved.exterior,true), duckSpeech:bool(saved.duckSpeech,true),
      muteHidden:bool(saved.muteHidden,true), soft:bool(saved.soft,true), clips:bool(saved.clips,true)
    };
    this._onVisibility = () => {
      this._applyGains();
      if (document.hidden && this.settings.muteHidden) this._stopLoops();
      else this._syncAmbient();
      this._scheduleAccent();
      this._notify();
    };
    document.addEventListener('visibilitychange',this._onVisibility);
  }
  _notify() { window.dispatchEvent(new CustomEvent('bunker-audio-change')); }
  _save() {
    this._write('bunker_audio_v46',JSON.stringify({master:this.volume,enabled:this.enabled,ambientEnabled:this.ambientEnabled,...this.settings}));
    this._write('bunker_sound_volume',this.volume);
    this._write('bunker_sound_enabled',this.enabled);
    this._write('bunker_ambient_enabled',this.ambientEnabled);
    this._notify();
  }
  chooseSound(yes) {
    this.consent = true;
    this.enabled = Boolean(yes);
    this._write('bunker_audio_consent_v46',yes?'yes':'silent');
    this._save();
    if (yes) this.unlock();
    else { this._applyGains(); this._stopLoops(); }
  }
  unlock() {
    if (!this.consent || !this.enabled || this._disposed) return;
    this._unlocked = true;
    this.init();
    if (!this.ctx) return;
    const ready = () => { this._applyGains(); this._syncAmbient(); this._notify(); };
    if (this.ctx.state !== 'running') this.ctx.resume().then(ready).catch(()=>this._notify());
    else ready();
  }
  init() {
    if (!this.consent || !this.enabled || !this._unlocked || this._disposed) return;
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      try {
        this.ctx = new AudioCtx();
        this.masterGain=this.ctx.createGain();
        const limiter=this.ctx.createDynamicsCompressor();
        limiter.threshold.value=-8;limiter.knee.value=6;limiter.ratio.value=12;
        limiter.attack.value=.004;limiter.release.value=.20;
        this.masterGain.connect(limiter);limiter.connect(this.ctx.destination);
        this.effectsGain=this.ctx.createGain();this.effectsGain.connect(this.masterGain);
        this.notificationsGain=this.ctx.createGain();this.notificationsGain.connect(this.masterGain);
        this.mediaGain=this.ctx.createGain();this.mediaGain.connect(this.masterGain);
        this.ambientGain=this.ctx.createGain();this.ambientGain.connect(this.masterGain);
        this._applyGains(true);
      } catch (e) { this.ctx=null;console.warn('Audio unavailable:',e); }
    }
  }
  _gain(node,value,seconds=.10) {
    if (!node || !this.ctx || node._target === value) return;
    node._target=value;
    const now=this.ctx.currentTime;
    node.gain.cancelScheduledValues(now);
    node.gain.setValueAtTime(node.gain.value,now);
    node.gain.linearRampToValueAtTime(value,now+seconds);
  }
  _audible() { return this.enabled && this.consent && !(this.settings.muteHidden && document.hidden); }
  _speech() { return ['REVEAL','SPEECH','ACCUSATION','DEBATE','JUSTIFICATION','LAST_WORD'].includes(this._scene.phase); }
  _duck() {
    if (this._preview) return .9;
    if (!this._scene.connected) return 0;
    if (this._scene.prologue) return .10;
    if (this._scene.review) return .30;
    if (this.settings.duckSpeech && this._speech()) return .25;
    if (this._scene.phase === 'WELCOME') return .60;
    if (this._scene.phase === 'FINAL') return .60;
    return .85;
  }
  _applyGains(immediate=false) {
    const t=immediate?0:.08;
    this._gain(this.masterGain,this._audible()?this.volume:0,t);
    this._gain(this.effectsGain,this.settings.effectsEnabled?this.settings.effects*(this.settings.soft?.55:1):0,t);
    this._gain(this.notificationsGain,this.settings.notificationsEnabled?this.settings.notifications*(this.settings.soft?.65:1):0,t);
    this._gain(this.mediaGain,this.settings.videoEnabled?this.settings.video:0,t);
    this._gain(this.ambientGain,this.ambientEnabled?this.settings.ambient*this._duck():0,immediate?0:.9);
    this._syncMedia();
  }
  getDestination(kind='effects') {
    this.init();
    return kind==='notifications'?this.notificationsGain:this.effectsGain;
  }
  getVolume() { return this.volume; }
  setVolume(value) {
    const n=Number(value);if(!Number.isFinite(n))return;
    this.volume=Math.max(0,Math.min(1,n));
    // A slider never silently reverses an explicit mute.
    this._applyGains();this._syncAmbient();this._save();
  }
  toggleSound() {
    this.enabled=!this.enabled;
    if (this.enabled) {this.consent=true;this._write('bunker_audio_consent_v46','yes');this.unlock();}
    else this._stopLoops();
    this._applyGains();this._save();return this.enabled;
  }
  toggleAmbient() {
    this.ambientEnabled=!this.ambientEnabled;
    this._ambientWanted=this.ambientEnabled;
    this._applyGains();this._syncAmbient();this._save();return this.ambientEnabled;
  }
  setSetting(key,value) {
    if(!Object.prototype.hasOwnProperty.call(this.settings,key))return;
    if (typeof this.settings[key]==='boolean') { if(typeof value!=='boolean')return;this.settings[key]=value; }
    else {const n=Number(value);if(!Number.isFinite(n))return;this.settings[key]=Math.max(0,Math.min(1,n));}
    this._applyGains();this._syncAmbient();this._scheduleAccent();this._save();
  }
  setScene(data={}) {
    const before=JSON.stringify(this._scene);
    // Deliberately do not retain game objects or accept probabilities/private cards.
    if(typeof data.phase==='string')this._scene.phase=data.phase;
    if(typeof data.catastrophe==='string')this._scene.catastrophe=/^[a-z0-9_]+$/.test(data.catastrophe)?data.catastrophe:'';
    for(const k of ['prologue','review','connected'])if(typeof data[k]==='boolean')this._scene[k]=data[k];
    this._applyGains();this._syncAmbient();this._scheduleAccent();
    if(before!==JSON.stringify(this._scene))this._notify();
  }
  _exterior() {
    if(!this.settings.exterior)return null;
    const id=this._scene.catastrophe;
    if(['nuclear_winter','ice_age','dark_matter_storm','permafrost_thaw'].includes(id))return 'wind';
    if(['acid_rains','global_flood','toxic_bloom'].includes(id))return 'rain';
    if(['asteroid_impact','atmospheric_fire','supervolcano','black_hole_approach','orbital_debris'].includes(id))return 'rumble';
    return null;
  }
  _desiredLoops() {
    const layers={ventilation:.80,equipment:.40};const ext=this._exterior();
    if(ext)layers[ext]=.16;return layers;
  }
  _canAmbient() {
    return !this._disposed&&this._ambientWanted&&this.ambientEnabled&&this._audible()&&this.volume>0&&this.settings.ambient>0&&this.ctx?.state==='running'&&this._scene.connected;
  }
  async _load(name) {
    if(this._buffers.has(name))return this._buffers.get(name);
    if(this._loads.has(name))return this._loads.get(name);
    if(this._failures.has(name)||!this.ctx)return null;
    const context=this.ctx;
    const task=(async()=>{
      for(const ext of ['ogg','mp3']) {
        const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),10000);
        try {
          const res=await fetch(`/static/audio/realistic_bunker/${name}.${ext}?v=4.6.0`,{signal:controller.signal,cache:'force-cache'});
          if(!res.ok)throw new Error('HTTP '+res.status);
          const bytes=await res.arrayBuffer();
          const buffer=await context.decodeAudioData(bytes);
          if(!buffer.duration||this._disposed)return null;
          this._buffers.set(name,buffer);this._notify();return buffer;
        } catch (_) { /* Try MP3 when OGG is unsupported or unavailable. */ }
        finally {clearTimeout(timeout);}
      }
      this._failures.add(name);this._notify();return null;
    })();
    this._loads.set(name,task);
    task.finally(()=>this._loads.delete(name));
    return task;
  }
  startAmbient() { this._ambientWanted=true;this.init();this._syncAmbient(); }
  stopAmbient() { this._ambientWanted=false;this._stopLoops(); }
  _syncAmbient() {
    if(!this._canAmbient()) {this._stopLoops();return;}
    const desired=this._desiredLoops();
    for(const [name,layer] of this._loops)if(!(name in desired)) {this._retire(layer);this._loops.delete(name);}
    for(const [name,level] of Object.entries(desired)) {
      if(this._loops.has(name))continue;
      const buffer=this._buffers.get(name);
      if(!buffer) {if(!this._loads.has(name)&&!this._failures.has(name))this._load(name).then(b=>{if(b&&this._canAmbient())this._syncAmbient();});continue;}
      try {
        const source=this.ctx.createBufferSource();source.buffer=buffer;source.loop=true;
        const gain=this.ctx.createGain();gain.gain.value=0;
        source.connect(gain);gain.connect(this.ambientGain);
        // Random starting positions prevent a fixed combined repeating pattern.
        source.start(this.ctx.currentTime+.025,Math.random()*buffer.duration);
        const layer={source,gain};this._loops.set(name,layer);
        this._gain(gain,level,1.4);
      } catch(e) {console.warn('Ambient start:',e);}
    }
    this.ambientNode=this._loops.size?this._loops:null;
    this._scheduleAccent();
  }
  _retire(layer) {
    if(!layer||layer.retired)return;layer.retired=true;
    // Capture this source. A delayed callback must never stop its replacement.
    this._gain(layer.gain,0,.30);
    layer.source.onended=()=>{try{layer.source.disconnect();layer.gain.disconnect();layer.pan?.disconnect();}catch(_){}};
    try{layer.source.stop(this.ctx.currentTime+.35);}catch(_){}
  }
  _stopLoops() {
    for(const layer of this._loops.values())this._retire(layer);
    this._loops.clear();this.ambientNode=null;
    for(const layer of this._details)this._retire(layer);
    this._details.clear();
    clearTimeout(this._accentTimer);this._accentTimer=null;
  }
  _canAccent() { return this._canAmbient()&&this.settings.accents&&!this._speech()&&!this._scene.prologue&&!this._scene.review&&!this._preview; }
  _scheduleAccent() {
    if(!this._canAccent()) {clearTimeout(this._accentTimer);this._accentTimer=null;for(const layer of this._details)this._retire(layer);this._details.clear();return;}
    if(this._accentTimer!==null)return;
    this._accentTimer=setTimeout(()=>{
      this._accentTimer=null;
      if(this._canAccent()) {
        const choices=['relay','metal','air_release'].filter(x=>x!==this._lastAccent);
        const name=choices[Math.floor(Math.random()*choices.length)];
        this._lastAccent=name;this._playAccent(name);this._scheduleAccent();
      }
    },40000+Math.random()*50000);
  }
  async _playAccent(name) {
    if(!this._canAccent())return;
    const buffer=await this._load(name);
    if(!buffer||!this._canAccent())return;
    const source=this.ctx.createBufferSource();source.buffer=buffer;
    const gain=this.ctx.createGain();gain.gain.value=(name==='relay'?.42:.27)*(this.settings.soft?.65:1);
    source.connect(gain);
    let pan=null;
    if(this.ctx.createStereoPanner){pan=this.ctx.createStereoPanner();pan.pan.value=(Math.random()-.5)*.45;gain.connect(pan);pan.connect(this.ambientGain);}
    else gain.connect(this.ambientGain);
    const layer={source,gain,pan};this._details.add(layer);
    source.onended=()=>{this._details.delete(layer);try{source.disconnect();gain.disconnect();pan?.disconnect();}catch(_){}};
    source.start();
  }
  previewAmbient() {
    if(!this.enabled||!this.consent)this.chooseSound(true);else this.unlock();
    this.ambientEnabled=true;this._ambientWanted=true;this._preview=true;
    clearTimeout(this._previewTimer);
    this._applyGains();this._syncAmbient();this._save();
    this._previewTimer=setTimeout(()=>{this._preview=false;this._applyGains();this._scheduleAccent();},10000);
  }
  retryAmbient() {this._failures.clear();this._syncAmbient();}
  attachMedia(video) {
    if(!video)return;
    if(!this._media.has(video))this._media.set(video,null);
    this._syncMedia();
  }
  _syncMedia() {
    for(const [video,node] of this._media) {
      let current=node;
      if(!current&&this.ctx) {
        try {current=this.ctx.createMediaElementSource(video);current.connect(this.mediaGain);this._media.set(video,current);}catch(_){}
      }
      const audible=this._audible()&&this.settings.videoEnabled&&this.settings.video>0&&this.volume>0&&this._unlocked;
      video.muted=!audible;
      // Safe native fallback: still respects master/visibility when graph unavailable.
      video.volume=current?1:Math.max(0,Math.min(1,this.volume*this.settings.video));
    }
  }
  status() {
    if(!this.consent)return 'Выберите: со звуком или без звука.';
    if(!this.enabled||this.volume===0)return 'Весь звук выключен.';
    if(this.settings.muteHidden&&document.hidden)return 'Фоновая вкладка: звук приглушён.';
    if(!this._unlocked||!this.ctx||this.ctx.state!=='running')return 'Нажмите «Включить звук», чтобы разрешить воспроизведение.';
    if(this._failures.size)return 'Часть аудиофайлов не загрузилась. Доступные слои продолжают работать.';
    if(!this.ambientEnabled)return 'Эмбиент выключен. Остальные каналы независимы.';
    if(this._loads.size)return 'Загрузка локальных звуков бункера…';
    if(this._scene.prologue)return 'Идёт ролик: фон бункера приглушён.';
    if(this.settings.duckSpeech&&this._speech())return 'Идёт речь: фон приглушён, редкие эффекты не звучат.';
    return 'Реалистичный бункер: вентиляция и оборудование.';
  }
  destroy() {
    this._disposed=true;this._stopLoops();clearTimeout(this._previewTimer);
    document.removeEventListener('visibilitychange',this._onVisibility);
    for(const [v,n] of this._media){v.muted=true;try{n?.disconnect();}catch(_){}}
    this._media.clear();this._buffers.clear();this.ctx?.close().catch(()=>{});
  }
  playCardReveal() {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;

    const now = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();

    osc.type = 'triangle';
    osc.frequency.setValueAtTime(320, now);
    osc.frequency.exponentialRampToValueAtTime(960, now + 0.16);

    gain.gain.setValueAtTime(0.25, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.28);

    osc.connect(gain);
    const dest = this.getDestination();
    if (dest) gain.connect(dest);

    osc.start(now);
    osc.stop(now + 0.28);
  }

  playStampSlam() {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;

    const now = this.ctx.currentTime;
    // Metallic impact + bass thud
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();

    osc.type = 'square';
    osc.frequency.setValueAtTime(160, now);
    osc.frequency.exponentialRampToValueAtTime(35, now + 0.25);

    gain.gain.setValueAtTime(0.35, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);

    osc.connect(gain);
    const dest = this.getDestination();
    if (dest) gain.connect(dest);

    osc.start(now);
    osc.stop(now + 0.35);
  }

  playGeigerClicks(count = 4) {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;

    const dest = this.getDestination();
    if (!dest) return;

    for (let i = 0; i < count; i++) {
      const delay = Math.random() * 0.4;
      const t = this.ctx.currentTime + delay;
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(2400 + Math.random() * 800, t);

      gain.gain.setValueAtTime(0.12, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.015);

      osc.connect(gain);
      gain.connect(dest);

      osc.start(t);
      osc.stop(t + 0.015);
    }
  }

  playTick(urgent = false) {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;

    try {
      if (this.ctx.state === 'suspended') {
        this.ctx.resume().catch(() => {});
      }
      const now = this.ctx.currentTime;
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc.type = urgent ? 'triangle' : 'sine';
      osc.frequency.setValueAtTime(urgent ? 1046 : 660, now);
      if (urgent) {
        osc.frequency.exponentialRampToValueAtTime(440, now + 0.09);
      }

      gain.gain.setValueAtTime(urgent ? 0.35 : 0.22, now);
      gain.gain.linearRampToValueAtTime(0.0001, now + (urgent ? 0.1 : 0.06));

      osc.connect(gain);
      const dest = this.getDestination('notifications');
      if (dest) gain.connect(dest);

      osc.start(now);
      osc.stop(now + (urgent ? 0.1 : 0.06));
    } catch (e) {
      console.warn('Tick audio error:', e);
    }
  }

  playVote() {
    return this.playVoteCast();
  }

  playTensionHeartbeat() {
    // V4.6: no physiological/horror soundtrack over player speeches.
    return;
  }

  playVoteCast() {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;

    const now = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();

    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(500, now);
    osc.frequency.exponentialRampToValueAtTime(220, now + 0.15);

    gain.gain.setValueAtTime(0.25, now);
    gain.gain.exponentialRampToValueAtTime(0.005, now + 0.18);

    osc.connect(gain);
    const dest = this.getDestination();
    if (dest) gain.connect(dest);

    osc.start(now);
    osc.stop(now + 0.18);
  }

  playPhaseTransition() {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;

    const now = this.ctx.currentTime;
    // Cyber synth sweep
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();

    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(180, now);
    osc.frequency.exponentialRampToValueAtTime(720, now + 0.25);
    osc.frequency.exponentialRampToValueAtTime(240, now + 0.55);

    gain.gain.setValueAtTime(0.2, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);

    osc.connect(gain);
    const dest = this.getDestination('notifications');
    if (dest) gain.connect(dest);

    osc.start(now);
    osc.stop(now + 0.6);
  }

  playSiren() {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;

    try {
      if (this.ctx.state === 'suspended') {
        this.ctx.resume().catch(() => {});
      }
      const now = this.ctx.currentTime;
      const osc1 = this.ctx.createOscillator();
      const osc2 = this.ctx.createOscillator();
      const filter = this.ctx.createBiquadFilter();
      const gain = this.ctx.createGain();

      osc1.type = 'sawtooth';
      osc2.type = 'triangle';

      filter.type = 'lowpass';
      filter.frequency.setValueAtTime(1200, now);

      // Pitch sweep cycle 1
      osc1.frequency.setValueAtTime(380, now);
      osc1.frequency.linearRampToValueAtTime(680, now + 0.5);
      osc1.frequency.linearRampToValueAtTime(380, now + 1.0);
      // Pitch sweep cycle 2
      osc1.frequency.linearRampToValueAtTime(680, now + 1.5);
      osc1.frequency.linearRampToValueAtTime(380, now + 2.0);

      // Sub oscillator for deep alarm roar
      osc2.frequency.setValueAtTime(190, now);
      osc2.frequency.linearRampToValueAtTime(340, now + 0.5);
      osc2.frequency.linearRampToValueAtTime(190, now + 1.0);
      osc2.frequency.linearRampToValueAtTime(340, now + 1.5);
      osc2.frequency.linearRampToValueAtTime(190, now + 2.0);

      // Мягкая комфортная громкость (было 0.35, теперь 0.08)
      gain.gain.setValueAtTime(0.08, now);
      gain.gain.setValueAtTime(0.08, now + 1.8);
      gain.gain.linearRampToValueAtTime(0.0001, now + 2.15);

      osc1.connect(filter);
      osc2.connect(filter);
      filter.connect(gain);
      const dest = this.getDestination('notifications');
      if (dest) gain.connect(dest);

      osc1.start(now);
      osc2.start(now);
      osc1.stop(now + 2.15);
      osc2.stop(now + 2.15);
    } catch (e) {
      console.warn('Siren audio error:', e);
    }
  }

  playElimination() {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;

    const now = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();

    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(180, now);
    osc.frequency.exponentialRampToValueAtTime(35, now + 0.9);

    gain.gain.setValueAtTime(0.35, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.9);

    osc.connect(gain);
    const dest = this.getDestination();
    if (dest) gain.connect(dest);

    osc.start(now);
    osc.stop(now + 0.9);
  }

  playVaultDoor() {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;

    const now = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();

    osc.type = 'square';
    osc.frequency.setValueAtTime(140, now);
    osc.frequency.exponentialRampToValueAtTime(32, now + 0.7);

    gain.gain.setValueAtTime(0.3, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.7);

    osc.connect(gain);
    const dest = this.getDestination();
    if (dest) gain.connect(dest);

    osc.start(now);
    osc.stop(now + 0.7);
  }

  playClick() {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;
    const now = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(850, now);
    osc.frequency.exponentialRampToValueAtTime(300, now + 0.04);
    gain.gain.setValueAtTime(0.15, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.04);
    osc.connect(gain);
    const dest = this.getDestination();
    if (dest) gain.connect(dest);
    osc.start(now);
    osc.stop(now + 0.04);
  }

  playBuzz() {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;
    const now = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(120, now);
    gain.gain.setValueAtTime(0.25, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.22);
    osc.connect(gain);
    const dest = this.getDestination();
    if (dest) gain.connect(dest);
    osc.start(now);
    osc.stop(now + 0.22);
  }

  playDice() {
    if (!this._audible()) return;
    this.init();
    if (!this.ctx || this.ctx.state !== 'running') return;
    this.playGeigerClicks(6);
  }

  play(soundName) {
    if (!this._audible()) return;
    this.init();
    switch (soundName) {
      case 'click':
        this.playClick();
        break;
      case 'tick':
        this.playTick(false);
        break;
      case 'urgent_tick':
        this.playTick(true);
        break;
      case 'flip':
      case 'card_reveal':
        this.playCardReveal();
        break;
      case 'stamp':
        this.playStampSlam();
        break;
      case 'geiger':
        this.playGeigerClicks();
        break;
      case 'heartbeat':
        this.playTensionHeartbeat();
        break;
      case 'vote':
        this.playVoteCast();
        break;
      case 'transition':
        this.playPhaseTransition();
        break;
      case 'siren':
      case 'alarm':
        this.playSiren();
        break;
      case 'elimination':
        this.playElimination();
        break;
      case 'vault':
      case 'door':
        this.playVaultDoor();
        break;
      case 'dice':
        this.playDice();
        break;
      case 'buzz':
        this.playBuzz();
        break;
      default:
        if (typeof this[soundName] === 'function') {
          this[soundName]();
        } else {
          this.playClick();
        }
        break;
    }
  }
}

window.soundFX = new BunkerSoundFX();
const bunkerUnlockAudio = () => { if(window.soundFX?.consent&&window.soundFX.enabled)window.soundFX.unlock(); };
window.addEventListener('pointerdown',bunkerUnlockAudio,{passive:true});
window.addEventListener('keydown',bunkerUnlockAudio,{passive:true});
window.addEventListener('pagehide',()=>window.soundFX?._stopLoops());
window.addEventListener('pageshow',()=>window.soundFX?._syncAmbient());
