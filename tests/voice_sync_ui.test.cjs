const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const appSource = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const voiceSource = fs.readFileSync(path.join(__dirname, '../web/voice.js'), 'utf8');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}
async function flush() {for (let i = 0; i < 20; i++) await Promise.resolve();}

function harness({play, fetch} = {}) {
  const node = tag => ({tag, textContent: '', dataset: {}, children: [], parentNode: null,
    append(...items) {for (const item of items) {item.parentNode = this; this.children.push(item);}},
    replaceWith(next) {
      const siblings = this.parentNode.children, index = siblings.indexOf(this);
      assert.notEqual(index, -1);
      siblings[index] = next; next.parentNode = this.parentNode; this.parentNode = null;
    },
  });
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, node('div'));
    return elements.get(id);
  };
  get('speak').checked = true;
  Object.assign(get('messages'), {scrollHeight: 100, scrollTop: 0, clientHeight: 100});
  const events = new Map(), frames = new Map(), utterances = [], activities = [], requests = [];
  const createdURLs = [], revokedURLs = [], played = [];
  let frameId = 0;
  let playerSrc;
  const player = Object.assign(get('voice-player'), {paused: true, ended: false, currentTime: 0, duration: 10,
    play() {this.paused = false; played.push(this.src); return play ? play() : Promise.resolve();},
    // Deliberately emit no pause/end/error: Stop must settle explicitly.
    pause() {this.paused = true;},
    load() {}, removeAttribute(name) {if (name === 'src') playerSrc = undefined; else delete this[name];},
    addEventListener(name, fn) {if (!events.has(name)) events.set(name, new Set()); events.get(name).add(fn);},
    removeEventListener(name, fn) {events.get(name)?.delete(fn);},
    emit(name) {this['on' + name]?.(); for (const fn of events.get(name) || []) fn();},
  });
  Object.defineProperty(player, 'src', {
    get() {return playerSrc;},
    set(value) {playerSrc = value; this.currentTime = 0; this.ended = false;},
  });
  const speech = {cancel() {}, getVoices() {return [];}, speak(utterance) {utterances.push(utterance);}};
  const context = vm.createContext({
    document: {getElementById: get, createElement: node},
    localStorage: {getItem() {return null;}},
    speechSynthesis: speech,
    SpeechSynthesisUtterance: class {constructor(text) {this.text = text;}},
    AbortController, AbortSignal, DOMException,
    URL: {
      createObjectURL(blob) {const url = `blob:test-${createdURLs.length + 1}`; createdURLs.push({url, blob}); return url;},
      revokeObjectURL(url) {revokedURLs.push(url);},
    },
    requestAnimationFrame(fn) {frames.set(++frameId, fn); return frameId;},
    cancelAnimationFrame(id) {frames.delete(id);},
    setTimeout, clearTimeout,
    fetch: async (url, options) => {
      requests.push({url, options});
      return fetch ? fetch(url, options) : {ok: true, blob: async () => ({})};
    },
    activity: (...args) => activities.push(args),
  });
  context.window = context;
  vm.runInContext(appSource.slice(0, appSource.indexOf('let activeRequestId=')), context);
  vm.runInContext(appSource.slice(appSource.indexOf('function browserSay('), appSource.indexOf('function showPendingReply(')), context);
  vm.runInContext(voiceSource.slice(0, voiceSource.indexOf('async function loadVoices(')), context);
  vm.runInContext('voiceAvailable = true;', context);
  return {context, get, player, frames, utterances, activities, requests, createdURLs, revokedURLs, played, events,
    article(text) {
      const article = node('article'), body = node('p'); body.textContent = text;
      article.append(node('div'), body); return article;
    },
    frame() {
      const current = [...frames.values()]; frames.clear();
      for (const fn of current) fn();
    },
  };
}

test('source positions reveal only the current word even when word lengths differ greatly', () => {
  const h = harness(), text = 'Supercalifragilisticexpialidocious is a word';
  const article = h.article(text), sync = h.context.voiceTextSync(article, text);
  sync.progress(text.indexOf(' '));
  assert.equal(article.children[1].textContent.trim(), text.split(' ')[0]);
  sync.progress(text.indexOf(' a'));
  assert.equal(article.children[1].textContent.trim(), 'Supercalifragilisticexpialidocious is');
  sync.done();
  assert.equal(article.children[1].textContent, text);
});

test('revealing speech preserves additional result cards and does not scroll a reader away', () => {
  const h = harness(), text = 'First second third';
  const article = h.article(text), card = {parentNode: null}; article.append(card);
  Object.assign(h.get('messages'), {scrollHeight: 1000, scrollTop: 20, clientHeight: 100});
  const sync = h.context.voiceTextSync(article, text);
  sync.progress(5);
  assert.equal(article.children[2], card);
  assert.equal(h.get('messages').scrollTop, 20);
  sync.done(); sync.progress(1);
  assert.equal(article.children[1].textContent, text);
});

test('browser word boundaries with zero charLength reveal the current word', async () => {
  const h = harness(), text = 'Supercalifragilisticexpialidocious is a word';
  const article = h.article(text), sync = h.context.voiceTextSync(article, text);
  const pending = h.context.say(text, false, {engine: 'browser'}, sync.progress);
  const utterance = h.utterances[0];
  utterance.onboundary({name: 'word', charIndex: 0, charLength: 0});
  assert.equal(article.children[1].textContent.trim(), text.split(' ')[0]);
  utterance.onboundary({name: 'word', charIndex: text.indexOf(' is') + 1, charLength: 0});
  assert.equal(article.children[1].textContent.trim(), 'Supercalifragilisticexpialidocious is');
  utterance.onend();
  await pending;
});

test('Stop settles browser speech and restores the complete reply without terminal events', async () => {
  const h = harness(), text = 'Read this complete response';
  vm.runInContext("voiceConfig = {engine: 'browser'};", h.context);
  const article = h.article(text);
  let finished = false;
  const pending = h.context.speakAssistantReply(text, article).then(() => {finished = true;});
  h.context.stopVoice();
  await flush();
  assert.equal(finished, true);
  assert.equal(article.children[1].textContent, text);
  await pending;
});

test('Stop during a pending play call settles and ignores its later rejection', async () => {
  const playback = deferred(), h = harness({play: () => playback.promise});
  const text = 'The full reply remains readable after stopping.';
  const article = h.article(text);
  let finished = false;
  const pending = h.context.speakAssistantReply(text, article).then(() => {finished = true;});
  await flush();
  assert.equal(h.requests.length, 1);
  h.context.stopVoice();
  await flush();
  assert.equal(finished, true);
  assert.equal(article.children[1].textContent, text);
  h.get('voice-note').textContent = 'Current voice is ready';
  playback.reject(Error('The play request was interrupted'));
  await flush();
  assert.equal(h.get('voice-note').textContent, 'Current voice is ready');
  assert.equal(h.frames.size, 0);
  await pending;
});

test('unavailable voice and synthesis errors always restore the response', async () => {
  for (const unavailable of [false, true]) {
    const h = harness({fetch: async () => ({ok: false, json: async () => ({error: 'Speech engine failed'})})});
    if (unavailable) vm.runInContext('voiceAvailable = false;', h.context);
    const text = 'A readable answer despite missing speech.', article = h.article(text);
    await h.context.speakAssistantReply(text, article);
    assert.equal(article.children[1].textContent, text);
    assert.match(h.get('voice-note').textContent, unavailable ? /unavailable/ : /Speech engine failed/);
  }
});

test('cleaned speech retains source positions around omitted code and shortened links', () => {
  const h = harness();
  const code = "```js\nconst hidden = 'many unspoken code words';\n```";
  const url = 'https://example.com/a/very/long/path?q=one';
  const text = `Before ${code} after ${url} finally.`;
  const segments = h.context.speechSegments(text);
  const spoken = segments.map(part => part.text).join('');
  const ends = segments.flatMap(part => Array.from(part.sourceEnds));
  assert.doesNotMatch(spoken, /const hidden|https:/);
  assert.match(spoken, /Code example omitted from speech/);
  assert.match(spoken, /link/);
  assert.equal(ends.length, spoken.length);
  assert.equal(ends[spoken.indexOf('Code')], text.indexOf(code));
  assert.equal(ends[spoken.indexOf('link')], text.indexOf(url));
  const after = spoken.indexOf('after') + 'after'.length - 1;
  assert.equal(ends[after], text.indexOf('after') + 'after'.length);
  assert.equal(ends.at(-1), text.length);
  assert.ok(ends.every((end, index) => index === 0 || end >= ends[index - 1]));
});

test('multi-chunk synthesis preserves monotonic positions through Markdown cleanup', () => {
  const h = harness(), text = '**Opening** ' + 'small words of varying length. '.repeat(45) + '_Ending_';
  const segments = h.context.speechSegments(text);
  assert.ok(segments.length > 1);
  assert.ok(segments.every(part => part.text.length === part.sourceEnds.length && part.text.length <= 500));
  const ends = segments.flatMap(part => Array.from(part.sourceEnds));
  assert.ok(ends.every((end, index) => index === 0 || end >= ends[index - 1]));
  assert.ok(ends.at(-1) >= text.indexOf('Ending') + 'Ending'.length);
});

test('cancelled synthesis cannot replace a later reply when its response arrives late', async () => {
  const oldResponse = deferred();
  const h = harness({fetch: () => oldResponse.promise});
  const article = h.article('Old reply'), pending = h.context.speakAssistantReply('Old reply', article);
  await flush();
  h.context.stopVoice();
  let finished = false; pending.then(() => {finished = true;});
  await flush();
  assert.equal(finished, true);
  h.get('voice-note').textContent = 'New reply';
  oldResponse.resolve({ok: true, blob: async () => ({})});
  await flush();
  assert.equal(h.player.src, undefined);
  assert.equal(h.get('voice-note').textContent, 'New reply');
  assert.equal(article.children[1].textContent, 'Old reply');
});

test('local reply follows playback time, pauses with audio, and resumes from its position', async () => {
  const h = harness(), text = 'One two six ten.', article = h.article(text);
  const pending = h.context.speakAssistantReply(text, article);
  await flush();
  assert.equal(article.children[1].textContent.trim(), 'One');
  h.player.currentTime = 2.5; h.frame();
  assert.equal(article.children[1].textContent.trim(), 'One two');
  h.frame();
  assert.equal(article.children[1].textContent.trim(), 'One two');
  h.player.pause(); h.player.currentTime = 5; h.frame();
  assert.equal(article.children[1].textContent.trim(), 'One two');
  h.player.paused = false; h.player.emit('playing');
  assert.equal(article.children[1].textContent.trim(), 'One two six');
  h.player.ended = true; h.player.emit('ended');
  await pending;
  assert.equal(article.children[1].textContent, text);
  assert.equal(h.frames.size, 0);
});

test('late browser callbacks from a stopped reply cannot disturb a newer voice session', async () => {
  const h = harness();
  vm.runInContext("voiceConfig = {engine: 'browser'};", h.context);
  const oldArticle = h.article('Old words'), oldPending = h.context.speakAssistantReply('Old words', oldArticle);
  const oldUtterance = h.utterances[0], staleBoundary = oldUtterance.onboundary, staleEnd = oldUtterance.onend;
  const newArticle = h.article('New words'), newPending = h.context.speakAssistantReply('New words', newArticle);
  const newUtterance = h.utterances[1];
  newUtterance.onstart();
  const activityCount = h.activities.length;
  staleBoundary({name: 'word', charIndex: 4}); staleEnd();
  await oldPending;
  assert.equal(oldArticle.children[1].textContent, 'Old words');
  assert.equal(newArticle.children[1].textContent.trim(), 'New');
  assert.equal(h.activities.length, activityCount);
  newUtterance.onend(); await newPending;
  assert.equal(newArticle.children[1].textContent, 'New words');
});

test('speech prefetches only one chunk ahead and plays every chunk in order with monotonic text', async () => {
  const h = harness({fetch: async (url, options) => ({ok: true, blob: async () => JSON.parse(options.body)})});
  const text = 'First words. ' + 'More words of different lengths. '.repeat(40) + 'Last words.';
  const chunks = Array.from(h.context.speechSegments(text)), progress = [];
  assert.ok(chunks.length > 3);
  const pending = h.context.say(text, false, {engine: 'kokoro', voice: 'bm_george', speed: 1}, offset => progress.push(offset));
  await flush();
  assert.equal(h.played.length, 1);
  assert.equal(h.requests.length, 2, 'the next chunk must start before current playback ends');
  for (let index = 0; index < chunks.length; index++) {
    assert.equal(h.played.length, index + 1);
    assert.equal(h.requests.length, Math.min(chunks.length, index + 2), 'prefetch must remain bounded');
    assert.equal(h.createdURLs[index].blob.text, chunks[index].text);
    h.player.currentTime = 7; h.frame();
    assert.ok(progress.at(-1) <= chunks[index].sourceEnds.at(-1), 'text must stay with the playing chunk');
    h.player.ended = true; h.player.emit('ended');
    await flush();
  }
  await pending;
  assert.deepEqual(h.requests.map(request => JSON.parse(request.options.body).text), chunks.map(chunk => chunk.text));
  assert.equal(progress.at(-1), text.length);
  assert.ok(progress.every((offset, index) => index === 0 || offset >= progress[index - 1]));
  assert.deepEqual(h.revokedURLs, h.createdURLs.slice(0, -1).map(item => item.url));
  assert.equal(h.frames.size, 0);
  assert.ok([...h.events.values()].every(listeners => listeners.size === 0));
});

test('slow prefetched audio waits after current playback without replaying or advancing text', async () => {
  const next = deferred(); let request = 0;
  const h = harness({fetch: async () => ++request === 1 ? {ok: true, blob: async () => ({})} : next.promise});
  const text = 'Words in a long reply. '.repeat(25), chunks = h.context.speechSegments(text), progress = [];
  assert.equal(chunks.length, 2);
  const pending = h.context.say(text, false, {engine: 'kokoro'}, offset => progress.push(offset));
  await flush();
  assert.equal(h.requests.length, 2);
  assert.equal(h.played.length, 1);
  h.player.ended = true; h.player.emit('ended');
  await flush();
  assert.equal(h.played.length, 1);
  assert.equal(progress.at(-1), chunks[0].sourceEnds.at(-1));
  next.resolve({ok: true, blob: async () => ({})});
  await flush();
  assert.equal(h.played.length, 2);
  h.player.ended = true; h.player.emit('ended');
  await pending;
  assert.equal(h.requests.length, 2);
});

test('Stop aborts prefetch and a late audio body cannot replace a new reply', async () => {
  const lateBody = deferred(); let request = 0;
  const h = harness({fetch: async () => ({ok: true, blob: ++request === 2 ? () => lateBody.promise : async () => ({})})});
  const text = 'Old words in a long reply. '.repeat(40), oldArticle = h.article(text);
  const oldPending = h.context.speakAssistantReply(text, oldArticle);
  await flush();
  assert.equal(h.requests.length, 2);
  const prefetchedSignal = h.requests[1].options.signal;
  h.context.stopVoice();
  await oldPending;
  assert.equal(prefetchedSignal.aborted, true);
  assert.equal(oldArticle.children[1].textContent, text);
  assert.equal(h.frames.size, 0);
  const newArticle = h.article('New reply'), newPending = h.context.speakAssistantReply('New reply', newArticle);
  await flush();
  const currentURL = h.player.src, count = h.played.length;
  lateBody.resolve({old: true});
  await flush();
  assert.equal(h.player.src, currentURL);
  assert.equal(h.played.length, count);
  assert.equal(h.requests.length, 3);
  h.player.ended = true; h.player.emit('ended');
  await newPending;
  assert.equal(newArticle.children[1].textContent, 'New reply');
});

test('early prefetch rejection finishes the current audio then restores the complete reply', async () => {
  let request = 0;
  const h = harness({fetch: async () => {
    if (++request === 2) throw Error('Next speech chunk failed');
    return {ok: true, blob: async () => ({})};
  }});
  const text = 'Words in a long reply. '.repeat(40), article = h.article(text);
  const pending = h.context.speakAssistantReply(text, article);
  await flush();
  // Allow an event-loop turn so an unhandled rejection would be caught by node:test.
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.played.length, 1);
  assert.equal(h.get('voice-note').textContent, '');
  h.player.ended = true; h.player.emit('ended');
  await pending;
  assert.equal(article.children[1].textContent, text);
  assert.equal(h.get('voice-note').textContent, 'Next speech chunk failed');
  assert.equal(h.requests.length, 2);
  assert.equal(h.frames.size, 0);
});

test('blocked playback cancels pending prefetch and restores the complete reply', async () => {
  const next = deferred(); let request = 0;
  const h = harness({
    play: () => Promise.reject(Error('Autoplay denied')),
    fetch: async () => ++request === 1 ? {ok: true, blob: async () => ({})} : next.promise,
  });
  const text = 'Words in a long reply. '.repeat(40), article = h.article(text);
  await h.context.speakAssistantReply(text, article);
  assert.equal(h.requests.length, 2);
  assert.equal(article.children[1].textContent, text);
  assert.match(h.get('voice-note').textContent, /Playback was blocked/);
  assert.equal(h.requests[1].options.signal.aborted, true, 'a failed playback must cancel its unused prefetch');
  next.reject(new DOMException('Cancelled', 'AbortError'));
  await flush();
  assert.equal(h.played.length, 1);
  assert.equal(h.frames.size, 0);
});
