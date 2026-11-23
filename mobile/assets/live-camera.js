import {CameraPlayer as DashboardCamera} from '/static/camera.js';

const liveTolerance = 30;
const seekBuffer = 5;
const seekCooldown = 30_000;

export class CameraPlayer extends DashboardCamera {
  constructor(elements, config) {
    super(elements, config);
    this.goLive = document.getElementById('camera-go-live');
    this.goLive.addEventListener('click', () => this.checkLiveEdge(true));
    document.addEventListener('visibilitychange', () => this.checkLiveEdge());
  }

  clearPlayback() {
    clearInterval(this.liveTimer);
    this.liveTimer = null;
    this.lastDuration = 0;
    this.durationIncreases = 0;
    this.lastSeekAt = -Infinity;
    this.liveConfirmed = false;
    this.goLive.hidden = true;
    super.clearPlayback();
  }

  setState(label, state, message) {
    if (state === 'live') {
      // PLAYING can start at any point in YouTube's DVR buffer.
      if (!this.liveTimer) this.liveTimer = setInterval(() => this.checkLiveEdge(), 5000);
      this.checkLiveEdge();
      return;
    }
    if (state === 'unavailable') {
      clearInterval(this.liveTimer);
      this.liveTimer = null;
      this.goLive.hidden = true;
    }
    super.setState(label, state, message);
  }

  checkLiveEdge(manual = false) {
    const player = this.player;
    if (document.hidden || !player || player.getPlayerState?.() !== window.YT?.PlayerState?.PLAYING) return;

    const duration = player.getDuration?.();
    const position = player.getCurrentTime?.();
    if (Number.isFinite(duration) && duration > 0) {
      // The documented duration grows as a live stream runs; a replay stays fixed.
      if (duration < this.lastDuration) this.durationIncreases = 0;
      if (this.lastDuration > 0 && duration - this.lastDuration > 0.5) this.durationIncreases++;
      this.lastDuration = duration;
      this.liveConfirmed ||= player.getVideoData?.()?.isLive === true || this.durationIncreases >= 2;
    }

    if (!this.liveConfirmed || !(duration > 0) || !Number.isFinite(position)) {
      super.setState('PLAYING', 'embedded');
      return;
    }

    const lag = duration - position;
    this.goLive.hidden = typeof player.seekTo !== 'function';
    const now = Date.now();
    if (!this.goLive.hidden && lag > (manual ? seekBuffer : liveTolerance) &&
        (manual || now - this.lastSeekAt >= seekCooldown)) {
      this.lastSeekAt = now;
      super.setState('CATCHING UP', 'embedded');
      player.seekTo(Math.max(0, duration - seekBuffer), true);
      return;
    }

    if (lag <= liveTolerance) super.setState('LIVE', 'live');
    else super.setState(now - this.lastSeekAt < 10_000 ? 'CATCHING UP' : 'DELAYED', 'embedded');
  }
}
