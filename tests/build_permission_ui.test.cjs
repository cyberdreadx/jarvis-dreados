const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/build.js'), 'utf8');
const permissionSource = source.slice(source.indexOf('function sandboxedCommand('), source.indexOf('function buildToolLabel(')) +
  source.slice(source.indexOf('function renderBuildPermissions('), source.indexOf('async function pollBuild()'));
const pending = {id: 'perm_web', permission: 'webfetch', patterns: ['https://example.com']};

function harness(request = async () => true) {
  const node = tag => ({tag, children: [], disabled: false, textContent: '', attributes: {},
    append(...items) {this.children.push(...items);},
    replaceChildren(...items) {this.children = items;},
    setAttribute(name, value) {this.attributes[name] = value;},
  });
  const elements = {'build-project': {value: 'demo'}, 'build-session': {value: 'ses_first'}, 'build-status': node('p'), 'build-permissions': node('div')};
  const requests = [];
  let polls = 0;
  const context = vm.createContext({
    $: id => elements[id], document: {createElement: node}, buildEpoch: 1, buildPermissionsSnapshot: '',
    buildAction: async fn => {try {await fn();} catch (error) {elements['build-status'].textContent = error.message;}},
    buildRequest: async (action, data) => {requests.push({action, ...data}); return request(action, data);},
    pollBuild: async () => {polls++;},
  });
  vm.runInContext(permissionSource, context);
  const render = (permissions = [pending]) => context.renderBuildPermissions(permissions, context.buildEpoch, elements['build-project'].value, elements['build-session'].value);
  render();
  return {context, elements, requests, render, get polls() {return polls;},
    get box() {return elements['build-permissions'].children[0];},
    get buttons() {return this.box.children.filter(item => item.tag === 'button');},
    get error() {return this.box.children.at(-1);},
  };
}

test('approval prompt exposes once, session and reject with accurate session lifetime', async () => {
  const h = harness();
  assert.deepEqual(h.buttons.map(button => button.textContent), ['Allow once', 'Allow webfetch this session', 'Reject']);
  assert.match(h.buttons[1].title, /this coding session until DreadOS restarts/);
  await h.buttons[1].onclick();
  assert.deepEqual(h.requests, [{action: 'permission', project: 'demo', session: 'ses_first', permission: 'perm_web', reply: 'session'}]);
  assert.equal(h.polls, 1);
});

test('once and reject remain one explicit request each', async () => {
  for (const [index, reply] of [[0, 'once'], [2, 'reject']]) {
    const h = harness();
    await h.buttons[index].onclick();
    assert.equal(h.requests[0].reply, reply);
    assert.equal(h.requests.length, 1);
  }
});

test('an in-flight response disables all choices and prevents duplicate replies', async () => {
  let resolve;
  const h = harness(() => new Promise(done => {resolve = done;}));
  const action = h.buttons[1].onclick();
  assert.ok(h.buttons.every(button => button.disabled));
  await h.buttons[0].onclick();
  assert.equal(h.requests.length, 1);
  resolve(true);
  await action;
  await h.buttons[1].onclick();
  assert.equal(h.requests.length, 1);
});

test('failed approval stays visible and retryable across unchanged polls', async () => {
  let attempts = 0;
  const h = harness(async () => {if (++attempts === 1) throw Error('Approval connection failed'); return true;});
  await h.buttons[1].onclick();
  assert.equal(h.error.textContent, 'Approval connection failed');
  assert.equal(h.error.attributes.role, 'alert');
  assert.equal(h.elements['build-status'].textContent, 'Approval connection failed');
  assert.ok(h.buttons.every(button => !button.disabled));
  const box = h.box;
  h.render();
  assert.equal(h.box, box);
  assert.equal(h.error.textContent, 'Approval connection failed');
  await h.buttons[1].onclick();
  assert.equal(h.requests.length, 2);
  assert.equal(h.polls, 1);
});

test('poll updates cannot re-enable an in-flight prompt and failure re-enables its latest controls', async () => {
  let reject;
  const h = harness(() => new Promise((resolve, fail) => {reject = fail;}));
  const action = h.buttons[1].onclick();
  const oldBox = h.box;
  h.render([pending, {id: 'perm_edit', permission: 'edit', patterns: ['index.html']}]);
  assert.notEqual(h.box, oldBox);
  assert.ok(h.buttons.every(button => button.disabled));
  await h.buttons[0].onclick();
  assert.equal(h.requests.length, 1);
  reject(Error('Reply failed'));
  await action;
  assert.ok(h.buttons.every(button => !button.disabled));
  assert.equal(h.error.textContent, 'Reply failed');
  h.render([pending]);
  assert.equal(h.error.textContent, 'Reply failed');
});

test('stale permission controls cannot reply after changing project, session or epoch', async () => {
  for (const mutation of ['project', 'session', 'epoch']) {
    const h = harness();
    const button = h.buttons[1];
    if (mutation === 'epoch') h.context.buildEpoch++;
    else h.elements['build-' + mutation].value = 'different';
    await button.onclick();
    assert.equal(h.requests.length, 0, mutation);
  }
});

test('completion from an old session does not refresh or report errors in the new session', async () => {
  for (const fails of [false, true]) {
    let finish;
    const h = harness(() => new Promise((resolve, reject) => {finish = fails ? reject : resolve;}));
    const action = h.buttons[1].onclick();
    h.context.buildEpoch++;
    h.elements['build-session'].value = 'ses_second';
    h.elements['build-status'].textContent = 'New session';
    finish(fails ? Error('Old request failed') : true);
    await action;
    assert.equal(h.requests[0].session, 'ses_first');
    assert.equal(h.polls, 0);
    assert.equal(h.elements['build-status'].textContent, 'New session');
  }
});

test('identical permission lists in a different session get fresh controls', async () => {
  const h = harness();
  const original = h.box;
  h.context.buildEpoch++;
  h.elements['build-session'].value = 'ses_second';
  h.render();
  assert.notEqual(h.box, original);
  await h.buttons[1].onclick();
  assert.equal(h.requests[0].session, 'ses_second');
});

test('after accepted approval, a failed refresh never permits duplicate submission', async () => {
  const h = harness();
  h.context.pollBuild = async () => {throw Error('Status refresh failed');};
  await h.buttons[1].onclick();
  assert.equal(h.error.textContent, 'Status refresh failed');
  assert.ok(h.buttons.every(button => button.disabled));
  await h.buttons[1].onclick();
  assert.equal(h.requests.length, 1);
  assert.equal(h.context.buildPermissionsSnapshot, '');
});

test('sandboxed commands are shown as the original command, not the wrapper', () => {
  const payload = Buffer.from(JSON.stringify({c: 'npm install three', w: 'C:/p', t: 120})).toString('base64');
  const {context, elements} = harness();
  context.atob = value => Buffer.from(value, 'base64').toString('binary');
  context.TextDecoder = TextDecoder;
  context.renderBuildPermissions([{id: 'perm_bash', permission: 'bash', patterns: ['C:/x/python.exe -X utf8 C:/x/sandbox.py run ' + payload]}], context.buildEpoch, 'demo', 'ses_first');
  const text = elements['build-permissions'].children[0].children[0].textContent;
  assert.match(text, /In sandbox: npm install three/);
  assert.doesNotMatch(text, /python\.exe/);
});
