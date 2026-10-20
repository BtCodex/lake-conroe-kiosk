// Only the supported YouTube IFrame API can assert playback state.
let youtubePromise;
function loadYouTube() {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (youtubePromise) return youtubePromise;
  youtubePromise = new Promise((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady;
    const script = document.createElement('script');
    let timer;
    const cleanup = () => {
      clearTimeout(timer);
      if (window.onYouTubeIframeAPIReady === ready) window.onYouTubeIframeAPIReady = previous;
    };
    const fail = message => {
      cleanup();
      youtubePromise = null;
      script.remove();
      reject(new Error(message));
    };
    const ready = () => {
      cleanup();
      try { if (typeof previous === 'function') previous(); }
      finally { resolve(window.YT); }
    };
    window.onYouTubeIframeAPIReady = ready;
    timer = setTimeout(() => fail('The video provider did not respond.'), 18000);
    script.src = 'https://www.youtube.com/iframe_api';
    script.async = true;
    script.onerror = () => fail('The video provider could not be reached.');
    document.head.append(script);
  });
  return youtubePromise;
}

export class CameraPlayer {
  constructor(elements, config = {}) {
    this.elements = elements;
    this.config = config;
    this.generation = 0;
    this.attempt = 0;
    this.retryClick = () => {
      this.attempt = 0;
      this.usingAlternative = false;
      this.start();
    };
    elements.retry?.addEventListener('click', this.retryClick);
    this.setState('CONNECTING', 'connecting', 'Connecting to the lake camera…');
  }

  setState(label, state, message = '') {
    const { status, message: overlay, retry } = this.elements;
    if (status) {
      status.textContent = label;
      status.dataset.state = state;
    }
    if (overlay) {
      overlay.textContent = message;
      overlay.hidden = !message;
    }
    if (retry) retry.hidden = state !== 'unavailable';
  }

  update(source) {
    if (!source) return;
    const key = JSON.stringify([source.provider, source.url, source.video_id, source.alternative_url]);
    this.source = source;
    if (this.key === key) return;
    this.key = key;
    this.attempt = 0;
    this.usingAlternative = false;
    this.start();
  }

  clearPlayback() {
    this.generation++;
    clearTimeout(this.retryTimer);
    this.retryTimer = null;
    clearTimeout(this.watchdog);
    clearInterval(this.imageTimer);
    clearInterval(this.progressTimer);
    this.fitObserver?.disconnect();
    this.fitObserver = null;
    if (this.player) {
      try { this.player.destroy(); } catch { /* Player may be only partially initialized. */ }
    }
    this.player = null;
    this.elements.container.replaceChildren();
  }

  fitFrame(frame) {
    // Fit the supported player in the available stage without stretching its viewport.
    const fit = () => {
      const bounds = this.elements.container.getBoundingClientRect();
      const width = Math.min(bounds.width, bounds.height * 16 / 9);
      frame.style.width = `${Math.max(0, width)}px`;
      frame.style.height = `${Math.max(0, width * 9 / 16)}px`;
      frame.style.flexShrink = '0';
    };
    this.fitObserver?.disconnect();
    fit();
    this.fitObserver = new ResizeObserver(fit);
    this.fitObserver.observe(this.elements.container);
  }

  unavailable(reason, generation) {
    if (generation !== this.generation) return;
    this.setState('UNAVAILABLE', 'unavailable', `Camera unavailable. ${reason}`);
    clearTimeout(this.watchdog);
    if (this.retryTimer) return;
    const base = Math.max(10, Number(this.source?.retry_seconds || this.config.retry_seconds || 30));
    const delay = Math.min(300, base * 2 ** Math.min(this.attempt++, 4));
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (this.source?.alternative_url && !this.usingAlternative) this.usingAlternative = true;
      this.start();
    }, delay * 1000);
  }

  async start() {
    this.clearPlayback();
    const generation = this.generation;
    const source = this.source;
    if (!source || source.provider === 'disabled') {
      this.setState('OFFLINE', 'unavailable', 'Camera unavailable. No camera source is enabled.');
      return;
    }
    let provider = source.provider;
    let url = source.url;
    let videoId = source.video_id;
    if (this.usingAlternative && source.alternative_url) {
      url = source.alternative_url;
      provider = source.alternative_provider || 'iframe';
      if (provider === 'youtube') videoId = this.youtubeId(url);
    }
    this.setState('CONNECTING', 'connecting', this.usingAlternative ? 'Connecting to the alternative camera…' : 'Connecting to the lake camera…');
    if (provider === 'youtube') {
      try {
        const YT = await loadYouTube();
        if (generation !== this.generation) return;
        const target = document.createElement('div');
        this.elements.container.append(target);
        this.player = new YT.Player(target, {
          width: '100%', height: '100%', videoId,
          playerVars: { autoplay: 1, controls: 0, playsinline: 1, rel: 0, fs: 0, disablekb: 1, origin: window.location.origin },
          events: {
            onReady: event => {
              if (generation !== this.generation) return;
              this.fitFrame(event.target.getIframe());
              event.target.mute();
              event.target.playVideo();
            },
            onStateChange: event => {
              if (generation !== this.generation) return;
              if (event.data === YT.PlayerState.PLAYING) {
                clearTimeout(this.watchdog);
                clearTimeout(this.retryTimer);
                this.retryTimer = null;
                this.attempt = 0;
                this.setState('LIVE', 'live');
              } else if (event.data === YT.PlayerState.BUFFERING || event.data === YT.PlayerState.UNSTARTED || event.data === YT.PlayerState.CUED) {
                this.setState('BUFFERING', 'connecting', 'Waiting for the live camera…');
                clearTimeout(this.watchdog);
                this.watchdog = setTimeout(() => this.unavailable('Playback did not start. Retrying automatically.', generation), 35000);
              } else {
                this.unavailable('Playback stopped. Retrying automatically.', generation);
              }
            },
            onError: () => this.unavailable('The source may be offline or restrict embedding. Retrying automatically.', generation),
          },
        });
        this.watchdog = setTimeout(() => this.unavailable('The player did not start. Retrying automatically.', generation), 40000);
        let lastTime = null, stalled = 0;
        this.progressTimer = setInterval(() => {
          if (generation !== this.generation || !this.player?.getPlayerState) return;
          if (this.player.getPlayerState() !== YT.PlayerState.PLAYING) return;
          const current = this.player.getCurrentTime();
          stalled = current === lastTime ? stalled + 1 : 0;
          lastTime = current;
          if (stalled >= 3) this.unavailable('The camera connection stalled. Retrying automatically.', generation);
        }, 15000);
      } catch (error) {
        this.unavailable(error.message, generation);
      }
    } else if (provider === 'image') {
      const image = document.createElement('img');
      image.alt = 'Periodically refreshed lake camera image';
      image.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block';
      let pending = false;
      image.onload = () => {
        if (generation !== this.generation) return;
        pending = false;
        clearTimeout(this.watchdog);
        clearTimeout(this.retryTimer);
        this.retryTimer = null;
        this.attempt = 0;
        this.setState('REFRESHED IMAGE', 'image');
        if (this.elements.status) this.elements.status.title = `Image successfully loaded at ${new Date().toLocaleTimeString([], { timeZone: this.config.timezone || 'America/Chicago' })}; camera capture time is supplied by the image source.`;
      };
      image.onerror = () => {
        pending = false;
        this.unavailable('The camera image could not be loaded.', generation);
      };
      const refresh = () => {
        if (pending || generation !== this.generation) return;
        pending = true;
        clearTimeout(this.watchdog);
        this.watchdog = setTimeout(() => {
          pending = false;
          this.unavailable('The camera image did not respond.', generation);
        }, 30000);
        const imageURL = new URL(url, window.location.origin);
        imageURL.searchParams.set('_camera_refresh', String(Date.now()));
        image.src = imageURL.href;
      };
      this.elements.container.append(image);
      refresh();
      this.imageTimer = setInterval(refresh, Math.max(15, source.image_refresh_seconds || 60) * 1000);
    } else if (provider === 'iframe') {
      const iframe = document.createElement('iframe');
      iframe.title = 'Configured alternative lake camera';
      iframe.allow = 'autoplay; encrypted-media; fullscreen; picture-in-picture';
      iframe.referrerPolicy = 'strict-origin-when-cross-origin';
      iframe.style.cssText = 'width:100%;height:100%;border:0;display:block';
      iframe.src = url;
      iframe.onload = () => {
        if (generation !== this.generation) return;
        clearTimeout(this.watchdog);
        // Cross-origin load events cannot prove successful video playback.
        this.setState('CAMERA', 'embedded');
        if (this.elements.status) this.elements.status.title = 'Embedded alternative source; playback state cannot be verified.';
      };
      iframe.onerror = () => this.unavailable('The alternative camera could not be loaded.', generation);
      this.elements.container.append(iframe);
      this.fitFrame(iframe);
      this.watchdog = setTimeout(() => this.unavailable('The alternative camera did not respond.', generation), 35000);
    } else {
      this.unavailable('Unsupported camera provider.', generation);
    }
  }

  youtubeId(value) {
    const url = new URL(value);
    if (url.hostname === 'youtu.be') return url.pathname.slice(1);
    return url.pathname.startsWith('/embed/') || url.pathname.startsWith('/live/') ? url.pathname.split('/')[2] : url.searchParams.get('v');
  }

  destroy() {
    this.clearPlayback();
    this.elements.retry?.removeEventListener('click', this.retryClick);
    this.source = null;
  }
}
