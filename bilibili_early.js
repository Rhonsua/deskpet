// Register before site scripts, so the website cannot consume ended first and
// restart/navigate before the desktop playlist observes completion.
window.addEventListener('ended', event => {
  const state = window.__tianyiVideoState;
  if (!state || event.target !== state.video) return;
  state.ended = true;
  event.stopImmediatePropagation();
  event.stopPropagation();
  state.video.pause();
}, true);
