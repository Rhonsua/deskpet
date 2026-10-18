// Respect manual seeking/controls: automatic history protection belongs only
// to the initial, untouched playback of a track.
for (const name of ['pointerdown', 'keydown']) {
  window.addEventListener(name, event => {
    const state = window.__tianyiVideoState;
    if (state && event.isTrusted && event.target instanceof Element &&
        event.target.closest('.bpx-player-container, .bpx-player-video-wrap, .bilibili-player-video'))
      state.user_interacted = true;
  }, true);
}
// Register before site scripts, so the website cannot consume ended first and
// restart/navigate before the desktop playlist observes completion.
window.addEventListener('ended', event => {
  const state = window.__tianyiVideoState;
  if (!state || event.target !== state.video) return;
  event.stopImmediatePropagation();
  event.stopPropagation();
  if (state.restarting) return;
  state.ended = true;
  state.video.pause();
}, true);
