(() => {
  const config = __CONFIG__;
  let state = window.__tianyiVideoState;
  if (!state || state.token !== config.token) {
    if (state && state.handler) window.removeEventListener('ended', state.handler, true);
    state = {token: config.token, ended: false, seen_playing: false, video: null};
    state.handler = event => {
      if (event.target !== state.video) return;
      state.ended = true;
      event.stopImmediatePropagation();
      event.stopPropagation();
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
  state.video = video;
  if (config.volume !== null) {
    video.volume = config.volume;
    if (config.volume > 0) video.muted = false;
  }
  if (config.command === 'pause') video.pause();
  if (config.command === 'seek' && Number.isFinite(config.position)) video.currentTime = config.position;
  if (config.command === 'play') { state.ended = false; Promise.resolve(video.play()).catch(() => {}); }
  if (!video.paused && video.readyState >= 2) state.seen_playing = true;
  return {token:config.token, has_video:true, title:document.title,
    position:Number.isFinite(video.currentTime)?video.currentTime:0,
    duration:Number.isFinite(video.duration)?video.duration:0,
    playing:!video.paused && !video.ended && video.readyState>=2,
    ended:state.ended || video.ended, seen_playing:state.seen_playing,
    muted:video.muted, volume:video.volume, error:video.error?video.error.code:0};
})()
