/**
 * Advanced Procedural Web Audio API Sound Synthesizer for Bunker.
 * Real-time procedural audio, ambient ventilation drone, hydraulic stamps, Geiger counter clicks.
 * Zero external audio files required!
 */
class BunkerSoundFX {
  constructor() {
    this.ctx = null;
    this.enabled = localStorage.getItem('bunker_sound_enabled') !== 'false';
    this.ambientEnabled = localStorage.getItem('bunker_ambient_enabled') === 'true';
    const savedVol = localStorage.getItem('bunker_sound_volume');
    this.volume = savedVol !== null ? Math.max(0, Math.min(1, parseFloat(savedVol))) : 0.7;
    if (isNaN(this.volume)) this.volume = 0.7;
    this.masterGain = null;
    this.ambientNode = null;
    this.ambientGain = null;
  }

  init() {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        this.ctx = new AudioCtx();
      }
    }
    if (this.ctx) {
      if (!this.masterGain) {
        this.masterGain = this.ctx.createGain();
        this.masterGain.gain.setValueAtTime(this.enabled ? this.volume : 0, this.ctx.currentTime);
        this.masterGain.connect(this.ctx.destination);
      }
      if (this.ctx.state === 'suspended') {
        this.ctx.resume().catch(() => {});
      }
    }
  }

  getDestination() {
    this.init();
    return this.masterGain || (this.ctx ? this.ctx.destination : null);
  }

  setVolume(value) {
    let num = parseFloat(value);
    if (isNaN(num)) return;
    num = Math.max(0, Math.min(1, num));
    this.volume = num;
    try {
      localStorage.setItem('bunker_sound_volume', this.volume.toString());
    } catch (_) {}

    if (this.volume > 0 && !this.enabled) {
      this.enabled = true;
      try {
        localStorage.setItem('bunker_sound_enabled', 'true');
      } catch (_) {}
    }

    if (this.ctx && this.masterGain) {
      const now = this.ctx.currentTime;
      this.masterGain.gain.cancelScheduledValues(now);
      this.masterGain.gain.setValueAtTime(this.enabled ? this.volume : 0, now);
    }
  }

  getVolume() {
    return this.volume;
  }

  toggleSound() {
    this.enabled = !this.enabled;
    try {
      localStorage.setItem('bunker_sound_enabled', this.enabled);
    } catch (_) {}
    if (this.ctx && this.masterGain) {
      const now = this.ctx.currentTime;
      this.masterGain.gain.cancelScheduledValues(now);
      this.masterGain.gain.setValueAtTime(this.enabled ? this.volume : 0, now);
    }
    if (!this.enabled && this.ambientNode) {
      this.stopAmbient();
    }
    return this.enabled;
  }

  toggleAmbient() {
    this.ambientEnabled = !this.ambientEnabled;
    localStorage.setItem('bunker_ambient_enabled', this.ambientEnabled);
    if (this.ambientEnabled) {
      this.startAmbient();
    } else {
      this.stopAmbient();
    }
    return this.ambientEnabled;
  }

  startAmbient() {
    if (!this.enabled) return;
    this.init();
    if (!this.ctx || this.ambientNode) return;

    try {
      const now = this.ctx.currentTime;
      // Generate pink/brown noise for low ventilation rumble
      const bufferSize = this.ctx.sampleRate * 2;
      const noiseBuffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
      const output = noiseBuffer.getChannelData(0);
      let b0 = 0, b1 = 0, b2 = 0;
      for (let i = 0; i < bufferSize; i++) {
        const white = Math.random() * 2 - 1;
        b0 = 0.99 * b0 + white * 0.05;
        b1 = 0.95 * b1 + white * 0.08;
        b2 = 0.9 * b2 + white * 0.1;
        output[i] = (b0 + b1 + b2) * 0.4;
      }

      const whiteNoise = this.ctx.createBufferSource();
      whiteNoise.buffer = noiseBuffer;
      whiteNoise.loop = true;

      // Low-pass filter to sound like heavy subterranean air ducts
      const filter = this.ctx.createBiquadFilter();
      filter.type = 'lowpass';
      filter.frequency.setValueAtTime(140, now);

      // Low frequency hum generator (55 Hz reactor turbine)
      const humOsc = this.ctx.createOscillator();
      humOsc.type = 'sine';
      humOsc.frequency.setValueAtTime(55, now);

      const humGain = this.ctx.createGain();
      humGain.gain.setValueAtTime(0.04, now);

      this.ambientGain = this.ctx.createGain();
      this.ambientGain.gain.setValueAtTime(0.001, now);
      this.ambientGain.gain.exponentialRampToValueAtTime(0.06, now + 2.0);

      whiteNoise.connect(filter);
      filter.connect(this.ambientGain);
      humOsc.connect(humGain);
      humGain.connect(this.ambientGain);

      const dest = this.getDestination();
      if (dest) {
        this.ambientGain.connect(dest);
      }

      whiteNoise.start(now);
      humOsc.start(now);

      this.ambientNode = { noise: whiteNoise, hum: humOsc };
    } catch (e) {
      console.warn('Could not start ambient audio:', e);
    }
  }

  stopAmbient() {
    if (this.ambientGain && this.ctx) {
      try {
        const now = this.ctx.currentTime;
        this.ambientGain.gain.linearRampToValueAtTime(0.0001, now + 1.0);
        setTimeout(() => {
          if (this.ambientNode) {
            try { this.ambientNode.noise.stop(); } catch (_) {}
            try { this.ambientNode.hum.stop(); } catch (_) {}
            this.ambientNode = null;
          }
        }, 1100);
      } catch (_) {
        this.ambientNode = null;
      }
    } else {
      this.ambientNode = null;
    }
  }

  playCardReveal() {
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;

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
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;

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
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;

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
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;

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
      const dest = this.getDestination();
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
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;

    const now = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(80, now);
    osc.frequency.exponentialRampToValueAtTime(45, now + 0.18);

    gain.gain.setValueAtTime(0.3, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.2);

    osc.connect(gain);
    const dest = this.getDestination();
    if (dest) gain.connect(dest);

    osc.start(now);
    osc.stop(now + 0.2);
  }

  playVoteCast() {
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;

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
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;

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
    const dest = this.getDestination();
    if (dest) gain.connect(dest);

    osc.start(now);
    osc.stop(now + 0.6);
  }

  playSiren() {
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;

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
      const dest = this.getDestination();
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
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;

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
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;

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
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;
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
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;
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
    if (!this.enabled) return;
    this.init();
    if (!this.ctx) return;
    this.playGeigerClicks(6);
  }

  play(soundName) {
    if (!this.enabled) return;
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

// Auto-unlock AudioContext on first user gesture (Chrome/Edge autoplay policy)
if (typeof window !== 'undefined') {
  const unlockAudio = () => {
    if (window.soundFX) {
      window.soundFX.init();
      if (window.soundFX.ctx) {
        if (window.soundFX.ctx.state === 'suspended') {
          window.soundFX.ctx.resume().catch(() => {});
        }
        try {
          // Silent 1-sample buffer burst to officially unlock Web Audio
          const buffer = window.soundFX.ctx.createBuffer(1, 1, 22050);
          const source = window.soundFX.ctx.createBufferSource();
          source.buffer = buffer;
          source.connect(window.soundFX.ctx.destination);
          source.start(0);
        } catch (_) {}
      }
    }
    window.removeEventListener('click', unlockAudio);
    window.removeEventListener('keydown', unlockAudio);
    window.removeEventListener('touchstart', unlockAudio);
    document.removeEventListener('click', unlockAudio);
  };
  window.addEventListener('click', unlockAudio, { passive: true });
  window.addEventListener('keydown', unlockAudio, { passive: true });
  window.addEventListener('touchstart', unlockAudio, { passive: true });
  document.addEventListener('click', unlockAudio, { passive: true });
}
