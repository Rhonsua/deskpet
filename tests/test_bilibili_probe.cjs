// Run the actual page probe with a deterministic media clock; no website/API.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../deskpet/music/players/bilibili_probe.js'), 'utf8');
let clock = 0;
class Video extends EventTarget {
  constructor() {
    super(); this.position = 10; this.duration = 100; this.seeks = [];
    this.clientWidth = 640; this.clientHeight = 480;
    this.readyState = 4; this.paused = false; this.seeking = false; this.ended = false;
    this.playbackRate = 1; this.buffered = {length: 0};
  }
  get currentTime() { return this.position; }
  set currentTime(t) { this.seeks.push(t); if (!this.ignoreSeek) this.position = t; }
  play() { this.paused = false; return Promise.resolve(); }
  pause() { this.paused = true; }
  removeAttribute() {}
}
let video = new Video();
const window = new EventTarget();
const context = vm.createContext({window, document: {querySelectorAll: () => [video], title: 'fixture'},
                                  performance: {now: () => clock}, Promise});
function probe(config = {}) {
  return vm.runInContext(script.replace('__CONFIG__', JSON.stringify({token:'one', command:null,
    restart_id:1, position:null, volume:null, ...config})), context);
}
let value = probe({command:'restart'});
assert.deepEqual(video.seeks, [0]);
assert.equal(value.restart_observed, true);
// The first response is "lost"; replaying that exact command cannot rewind.
clock = 4200; video.position = 4.2;
window.__tianyiVideoState.restart_settled = false;
value = probe({command:'restart'});
assert.deepEqual(video.seeks, [0]);
assert.equal(value.position, 4.2);
assert.equal(value.restart_observed, true);
assert.equal(value.restart_elapsed, 4.2);
// A genuinely new explicit playback/loop is still allowed to restart.
probe({command:'restart', token:'two', restart_id:2});
assert.deepEqual(video.seeks, [0, 0]);
// The next media element must not inherit a successful seek from the old one.
video = new Video();
value = probe({token:'two', restart_id:2});
assert.equal(value.restart_observed, false);
assert.equal(value.restart_settled, false);
assert.equal(value.media_id, 2);
video.ignoreSeek = true;
value = probe({command:'restart', token:'two', restart_id:3});
assert.equal(value.restart_observed, false);
assert.equal(value.position, 10);
video.ignoreSeek = false;
value = probe({command:'restart', token:'two', restart_id:4});
assert.equal(value.position, 0);
assert.equal(value.restart_observed, true);
console.log('PASS: lost reply deduplicated, late seek ack preserved, explicit replay and media replacement handled');

// Run the document-start observer too: a site can autoplay several seconds
// before the desktop's very first probe arrives.
context.Element = Video;
Video.prototype.closest = () => ({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../deskpet/music/players/bilibili_early.js'), 'utf8'), context);
function event(name) {
  const e = new Event(name);
  Object.defineProperty(e, 'target', {value:video});
  window.dispatchEvent(e);
}
video = new Video(); video.position = .04; clock = 10000;
event('playing');
video.position = 3.24; clock = 13200;
value = probe({token:'fresh', command:'restart', restart_id:5, allow_opening:true});
assert.equal(value.position, 3.24);
assert.deepEqual(video.seeks, []);
assert.equal(value.restart_observed, true);
// An explicit same-page replay/loop still rewinds, as requested by the user.
probe({token:'loop', command:'restart', restart_id:6, allow_opening:false});
assert.deepEqual(video.seeks, [0]);
// An intervening site history seek invalidates the autoplay proof.
event('seeking');
video.position = 80;
probe({token:'history', command:'restart', restart_id:7, allow_opening:true});
assert.deepEqual(video.seeks, [0, 0]);
// Starting straight at an old progress point is not a start from the beginning.
video = new Video(); video.position = 50;
event('playing');
probe({token:'history2', command:'restart', restart_id:8, allow_opening:true});
assert.deepEqual(video.seeks, [0]);
console.log('PASS: pre-probe autoplay preserved; explicit loops and old-history starts still reset');
