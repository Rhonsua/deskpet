(() => {
  const config = __CONFIG__;
  let state = window.__tianyiVideoState;
  if (!state || state.token !== config.token) {
    if (state && state.handler) window.removeEventListener('ended', state.handler, true);
    if (state && state.video) {
      if (state.onPlaying) state.video.removeEventListener('playing', state.onPlaying);
      if (state.onSeeked) state.video.removeEventListener('seeked', state.onSeeked);
    }
    state = {token: config.token, ended: false, seen_playing: false, video: null};
    state.handler = event => {
      if (event.target !== state.video) return;
      event.stopImmediatePropagation();
      event.stopPropagation();
      if (state.restarting) return;
      state.ended = true;
      state.video.pause();
    };
    window.addEventListener('ended', state.handler, true);
    window.__tianyiVideoState = state;
  }
  const candidates = Array.from(document.querySelectorAll(
    '.bpx-player-video-wrap video, .bilibili-player-video video, .bpx-player-container video, .bpx-player-container bwp-video'))
    .filter(v => typeof v.play === 'function' && typeof v.pause === 'function');
  const video = candidates.sort((a,b) => b.clientWidth*b.clientHeight-a.clientWidth*a.clientHeight)[0];
  if (!video) return {token:config.token, has_video:false, title:document.title};
  if (state.video !== video) {
    if (state.video && state.onPlaying) state.video.removeEventListener('playing', state.onPlaying);
    if (state.video && state.onSeeked) state.video.removeEventListener('seeked', state.onSeeked);
    state.video = video;
    state.media_id = (state.media_id || 0) + 1;
    state.onPlaying = () => { state.seen_playing = true; };
    video.addEventListener('playing', state.onPlaying);
  }
  // The desktop playlist owns repetition. Native HTML looping suppresses ended.
  video.loop = false;
  video.autoplay = false;
  video.removeAttribute('autoplay');
  if (config.volume !== null) {
    video.volume = config.volume;
    if (config.volume > 0) video.muted = false;
  }
  if (config.command === 'pause') video.pause();
  if (config.command === 'seek' && Number.isFinite(config.position)) video.currentTime = config.position;
  if (config.command === 'restart') {
    state.ended = false;
    state.restarting = true;
    video.pause();
    // Seeking is asynchronous. Start again on seeked as well as immediately;
    // the host verifies the result and retries if the site ignores the seek.
    if (state.onSeeked) video.removeEventListener('seeked', state.onSeeked);
    state.onSeeked = () => {
      if (state.restarting && video.currentTime < 1)
        Promise.resolve(video.play()).catch(() => {});
    };
    video.addEventListener('seeked', state.onSeeked, {once:true});
    video.currentTime = 0;
    Promise.resolve(video.play()).catch(() => {});
  }
  if (config.command === 'pause') {
    state.restarting = false;
    if (state.onSeeked) video.removeEventListener('seeked', state.onSeeked);
  }
  if (state.restarting && !video.seeking && !video.paused &&
      video.currentTime < Math.min(2, video.duration / 2))
    state.restarting = false;
  if (config.command === 'play') { state.ended = false; Promise.resolve(video.play()).catch(() => {}); }
  if (config.command === 'resume' && !state.ended && !video.ended && video.paused)
    Promise.resolve(video.play()).catch(() => {});
  if (!video.paused && video.readyState >= 2) state.seen_playing = true;
  return {token:config.token, has_video:true, title:document.title,
    position:Number.isFinite(video.currentTime)?video.currentTime:0,
    duration:Number.isFinite(video.duration)?video.duration:0,
    playing:!video.paused && !video.ended && video.readyState>=2, paused:video.paused,
    ended:!state.restarting && (state.ended || video.ended), seen_playing:state.seen_playing,
    media_id:state.media_id, seeking:video.seeking, ready_state:video.readyState,
    buffered_to_end:!!video.buffered && Array.from({length:video.buffered.length}, (_,i) => i).some(i =>
      video.buffered.start(i) <= video.currentTime + .05 && video.buffered.end(i) >= video.duration - .05),
    muted:video.muted, volume:video.volume, error:video.error?video.error.code:0};
})()
