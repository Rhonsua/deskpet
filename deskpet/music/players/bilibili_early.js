// Observe a fresh page's own autoplay before the first host probe. If it
// genuinely began at zero, taking control later must preserve that intro.
window.addEventListener('playing', event => {
  const video = event.target;
  if (!(video instanceof Element) || typeof video.play !== 'function' ||
      !video.closest('.bpx-player-container, .bpx-player-video-wrap, .bilibili-player-video')) return;
  const old = window.__tianyiOpening;
  if (old && old.video === video) return;
  window.__tianyiOpening = {video, clock:performance.now(), position:video.currentTime,
    rate:video.playbackRate || 1, valid:!video.seeking && video.currentTime >= 0 && video.currentTime < .5};
}, true);
for (const name of ['seeking', 'loadedmetadata', 'emptied']) {
  window.addEventListener(name, event => {
    const opening = window.__tianyiOpening;
    if (opening && opening.video === event.target) opening.valid = false;
  }, true);
}
window.addEventListener('ratechange', event => {
  const opening = window.__tianyiOpening;
  if (opening && opening.video === event.target)
    opening.rate = Math.max(opening.rate, event.target.playbackRate || 1);
}, true);

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
