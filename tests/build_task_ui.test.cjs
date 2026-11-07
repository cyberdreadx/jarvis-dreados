const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/build.js'), 'utf8');

function harness() {
  const timer = {hidden: true, textContent: ''};
  const ticks = new Map();
  let next = 0;
  const context = vm.createContext({
    $: () => timer,
    Date: {now: () => 9000},
    setInterval: fn => {ticks.set(++next, fn); return next;},
    clearInterval: id => ticks.delete(id),
    document: {createElement: tag => ({tag, dataset: {}, children: [], append(...items) {this.children.push(...items);}})},
  });
  vm.runInContext(source.slice(source.indexOf('let buildTask='), source.indexOf('function isOfflineDocsTool')), context);
  return {context, timer, ticks, poll: data => context.updateBuildTaskTimer(data)};
}
const user = (created = 1000, extra = {}) => ({info: {role: 'user', time: {created}}, parts: [{type: 'text', text: 'Build'}], ...extra});
const assistant = (created, completed, parts = []) => ({info: {role: 'assistant', time: {created, completed}}, parts});
const data = (messages, type = 'idle', extra = {}) => ({messages, status: {type}, ...extra});

test('running task measures from the persisted user request and labels approval wait', () => {
  const h = harness();
  h.poll(data([user(), assistant(2000)], 'busy', {permissions: [{id: 'p'}]}));
  assert.match(h.timer.textContent, /awaiting approval.*8s/);
  assert.equal(h.ticks.size, 1);
  h.poll(data([user(), assistant(2000)], 'retry'));
  assert.match(h.timer.textContent, /Task elapsed.*8s/);
  assert.equal(h.ticks.size, 1);
});

test('completion freezes the timer and reconstructs identically after refresh', () => {
  const snapshot = data([user(), assistant(2000, 6000)]);
  for (const h of [harness(), harness()]) {
    h.poll(snapshot);
    assert.equal(h.timer.textContent, 'Task took 5s');
    assert.equal(h.ticks.size, 0);
  }
});

test('a follow-up request starts its own timer instead of including earlier tasks', () => {
  const h = harness();
  h.poll(data([user(), assistant(2000, 6000), user(7000), assistant(7500, 8000)]));
  assert.equal(h.timer.textContent, 'Task took 1s');
});

test('compaction handoffs do not restart the user task timer', () => {
  const h = harness();
  h.poll(data([user(), user(5000, {parts: [{type: 'compaction', auto: true}]}), user(6000, {parts: [{type: 'text', synthetic: true, text: 'Continue'}]}), assistant(6500, 8000)]));
  assert.equal(h.timer.textContent, 'Task took 7s');
});

test('an aborted task without a completion timestamp reports only known elapsed time', () => {
  const h = harness();
  const stopped = assistant(2000, undefined, [{type: 'tool', state: {time: {end: 7000}}}]);
  stopped.info.error = {name: 'MessageAbortedError'};
  h.poll(data([user(), stopped]));
  assert.equal(h.timer.textContent, 'Task ended · at least 6s');
  assert.equal(h.ticks.size, 0);
  h.poll(data([user()]));
  assert.equal(h.timer.textContent, 'Task ended · duration unavailable');
});

test('reset clears stale timing while switching sessions', () => {
  const h = harness();
  h.poll(data([user()], 'busy'));
  h.context.resetBuildTaskTimer();
  assert.equal(h.timer.hidden, true);
  assert.equal(h.timer.textContent, '');
  assert.equal(h.ticks.size, 0);
  h.poll(data([]));
  assert.equal(h.timer.hidden, true);
});

test('duration formatting handles hours, missing and invalid timestamps', () => {
  const h = harness();
  assert.equal(h.context.formatBuildDuration(3661000), '1h 1m 1s');
  assert.equal(h.context.formatBuildDuration(NaN), 'unknown');
  h.poll(data([user(NaN)], 'busy'));
  assert.equal(h.timer.hidden, true);
});

test('provider reasoning displays as text, with user collapse preserved while streaming', () => {
  const h = harness();
  const part = {id: 'reason', text: '<script>untrusted</script>', time: {start: 1000}};
  let result = h.context.renderBuildReasoning(part, new Set(), new Set());
  assert.equal(result.open, true);
  assert.equal(result.children[1].textContent, part.text);
  result = h.context.renderBuildReasoning(part, new Set(), new Set(['reason']));
  assert.equal(result.open, false);
  result = h.context.renderBuildReasoning({...part, time: {end: 2000}}, new Set(), new Set());
  assert.equal(result.children[0].textContent, 'Model reasoning');
});

test('changing projects during session creation does not select the old project session', async () => {
  const elements = {'new-build-session': {}, 'build-project': {value: 'first'}, 'build-session': {value: 'second-session'}};
  let resolveRequest;
  const context = vm.createContext({
    $: id => elements[id], buildEpoch: 1,
    buildAction: fn => fn(), requireBuildProject: () => true,
    resetBuildTerminalApproval() {},
    buildRequest: () => new Promise(resolve => {resolveRequest = resolve;}),
    resetBuildTaskTimer: () => assert.fail('Stale session must not alter the new timer'),
    loadBuildSessions: () => assert.fail('Stale project must not reload sessions'),
    pollBuild: () => assert.fail('Stale project must not poll'),
  });
  vm.runInContext(source.split('\n').find(line => line.startsWith("$('new-build-session').onclick=")), context);
  const pending = elements['new-build-session'].onclick();
  context.buildEpoch = 2;
  elements['build-project'].value = 'second';
  resolveRequest({id: 'first-session'});
  await pending;
  assert.equal(elements['build-session'].value, 'second-session');
});

function recoveryHarness(request = async () => ({session: {id: 'fresh', title: 'Recovered'}, prompt: 'Review this handoff'})) {
  const elements = Object.fromEntries(['build-project', 'build-session', 'build-prompt', 'build-status', 'build-output', 'build-permissions', 'build-recovery', 'build-recovery-label', 'build-recovery-detail', 'build-continue', 'send-build', 'build-diff'].map(id => [id, {
    value: '', textContent: '', options: [], add(option) {this.options.push(option);},
    replaceChildren() {}, focus() {}, click() {calls.push(['send']);},
  }]));
  elements['build-project'].value = 'demo';
  elements['build-session'].value = 'old';
  elements['build-session'].options.push({value: 'old'});
  const calls = [];
  const context = vm.createContext({
    $: id => elements[id], buildEpoch: 1, buildBusy: false, buildAgentBusy: false, buildImages: [],
    buildPolling: false, buildMessagesSnapshot: 'old', buildPermissionsSnapshot: 'old',
    window: {showContextMeter: true}, showContextMeter: (...args) => calls.push(['meter', ...args]),
    Option: class {constructor(title, value) {this.title = title; this.value = value;}},
    buildAction: async fn => {try {await fn();} catch (error) {elements['build-status'].textContent = error.message;}},
    buildRequest: async (...args) => {calls.push(['request', ...args]); return request(...args);},
    resetBuildTerminalApproval: () => calls.push(['approval-reset']),
    resetBuildTaskTimer: () => calls.push(['timer-reset']),
    beginBuildPolling: () => calls.push(['begin-poll']),
    pollBuild: async () => calls.push(['poll', elements['build-session'].value]),
  });
  vm.runInContext(source.slice(source.indexOf('function isBuildContextOverflow'), source.indexOf('let docsTimer=')), context);
  const render = (recovery = {label: 'Context limit reached', action: 'recover_context', can_continue: true}, type = 'idle') => context.renderBuildRecovery({status: {type}, recovery});
  render();
  return {context, elements, calls, render, click: () => elements['build-continue'].onclick()};
}

test('context overflow names and wrapped errors get fresh-session recovery copy', () => {
  const h = recoveryHarness();
  for (const error of [
    {name: 'ContextWindowExceededError'},
    {data: {message: 'request (136065 tokens) exceeds the available context size (32768 tokens)'}},
    {data: {message: '{"error":{"code":"context_length_exceeded"}}'}},
    {data: {message: 'Context size has been exceeded.'}},
  ]) assert.equal(h.context.isBuildContextOverflow(error), true);
  assert.equal(h.context.isBuildContextOverflow({name: 'MessageAbortedError'}), false);
  assert.equal(h.context.isBuildContextOverflow({data: {message: 'Model unloaded by user'}}), false);
  assert.equal(h.elements['build-continue'].textContent, 'Start fresh session ↗');
  h.render({can_continue: true});
  assert.equal(h.elements['build-continue'].textContent, 'Continue task ↗');
});

test('fresh-session recovery selects before polling and prepares a draft without sending', async () => {
  const h = recoveryHarness();
  await h.click();
  assert.equal(h.elements['build-session'].value, 'fresh');
  assert.deepEqual(h.elements['build-session'].options.map(x => x.value), ['old', 'fresh']);
  assert.equal(h.elements['build-prompt'].value, 'Review this handoff');
  assert.equal(h.context.buildEpoch, 2);
  assert.equal(h.context.buildMessagesSnapshot, '');
  assert.equal(h.context.buildPermissionsSnapshot, '');
  assert.equal(h.context.buildBusy, false);
  assert.equal(h.calls.filter(x => x[0] === 'request').length, 1);
  assert.equal(h.calls[0][1], 'recover_context');
  assert.equal(h.calls.some(x => x[0] === 'send'), false);
  assert.deepEqual(h.calls.filter(x => x[0] === 'poll'), [['poll', 'fresh']]);
  assert.equal(h.calls.filter(x => x[0] === 'approval-reset').length, 1);
  assert.equal(h.calls.filter(x => x[0] === 'timer-reset').length, 1);
  assert.match(h.elements['build-status'].textContent, /Review the handoff/);
});

test('double-clicking recovery creates only one session', async () => {
  let resolve;
  const h = recoveryHarness(() => new Promise(r => {resolve = r;}));
  const pending = h.click();
  await h.click();
  assert.equal(h.calls.filter(x => x[0] === 'request').length, 1);
  assert.equal(h.elements['build-continue'].disabled, true);
  resolve({session: {id: 'fresh', title: 'Recovered'}, prompt: 'Review'});
  await pending;
});

test('project or session changes during recovery cannot overwrite the new selection', async () => {
  for (const id of ['build-project', 'build-session']) {
    let resolve;
    const h = recoveryHarness(() => new Promise(r => {resolve = r;}));
    const pending = h.click();
    h.elements[id].value = 'another';
    h.context.buildEpoch++;
    resolve({session: {id: 'fresh', title: 'Recovered'}, prompt: 'Review'});
    await pending;
    assert.equal(h.elements[id].value, 'another');
    assert.equal(h.elements['build-prompt'].value, '');
    assert.equal(h.elements['build-session'].options.length, 1);
    assert.equal(h.calls.some(x => x[0] === 'poll'), false);
  }
});

test('drafts and attachments entered while creating a session are preserved', async () => {
  for (const attachment of [false, true]) {
    let resolve;
    const h = recoveryHarness(() => new Promise(r => {resolve = r;}));
    const pending = h.click();
    if (attachment) h.context.buildImages = [{name: 'keep.png'}];
    else h.elements['build-prompt'].value = 'New draft';
    resolve({session: {id: 'fresh', title: 'Recovered'}, prompt: 'Review'});
    await pending;
    assert.equal(h.elements['build-session'].value, 'old');
    assert.equal(h.elements['build-prompt'].value, attachment ? '' : 'New draft');
    assert.equal(h.context.buildImages.length, attachment ? 1 : 0);
    assert.equal(h.elements['build-session'].options.length, 2);
    assert.match(h.elements['build-status'].textContent, /preserved/);
    assert.equal(h.calls.some(x => x[0] === 'send'), false);
  }
});

test('existing drafts or images prevent recovery and a stale recovery card cannot act', async () => {
  for (const kind of ['draft', 'image', 'stale']) {
    const h = recoveryHarness();
    if (kind === 'draft') h.elements['build-prompt'].value = 'Keep';
    if (kind === 'image') h.context.buildImages = [{name: 'keep.png'}];
    if (kind === 'stale') h.elements['build-session'].value = 'different';
    await h.click();
    assert.equal(h.calls.length, 0);
  }
});

test('failed recovery restores controls and leaves the original conversation selected', async () => {
  const h = recoveryHarness(async () => {throw Error('Connection failed');});
  await h.click();
  assert.equal(h.elements['build-session'].value, 'old');
  assert.equal(h.elements['build-prompt'].value, '');
  assert.equal(h.context.buildBusy, false);
  assert.equal(h.elements['send-build'].disabled, false);
  assert.match(h.elements['build-status'].textContent, /Connection failed/);
});

test('ordinary interrupted tasks still continue in the same session', async () => {
  const h = recoveryHarness();
  h.render({can_continue: true});
  await h.click();
  assert.match(h.elements['build-prompt'].value, /^Continue the unfinished task in this session/);
  assert.equal(h.elements['build-session'].value, 'old');
  assert.deepEqual(h.calls, [['send']]);
});
