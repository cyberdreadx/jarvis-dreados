import test from 'node:test';
import assert from 'node:assert/strict';
import { WebFetchDefaults } from '../opencode-plugins/webfetch-defaults.mjs';

const URL = 'https://www.pac-man.com/faq.html';
// Real OpenCode 1.18 user messages always carry a per-message summary with diffs.
const user = (id = 'user1', sessionID = 'ses_a', parts = [{type:'text',text:'Build the game'}]) =>
  ({info:{id,sessionID,role:'user',summary:{diffs:[]}},parts});
const tool = (error, {url = URL, sessionID = 'ses_a', status = 'error', callID = 'old'} = {}) =>
  ({info:{id:'assistant1',sessionID,role:'assistant'},parts:[{
    type:'tool',tool:'webfetch',callID,state:{status,input:{url},error,output:status === 'completed' ? 'Reference text' : undefined},
  }]});
const missing = () => tool(`StatusCode: non 2xx status code (404 GET ${URL})`);

async function harness(messages) {
  const calls = [];
  const client = {session:{messages:async options => {
    calls.push(options);
    return {data:messages.filter(message => message.info.sessionID === options.path.id)};
  }}};
  const hooks = await WebFetchDefaults({client,directory:'C:/projects/game'});
  let fetches = 0;
  return {hooks,messages,calls,get fetches(){return fetches;},
    async fetch(url = URL, sessionID = 'ses_a', args = {}) {
      const input = {tool:'webfetch',sessionID,callID:'current'};
      const output = {args:{url,...args}};
      await hooks['tool.execute.before'](input,output);
      fetches++; // Represents native webfetch execution, after the before hook.
      await hooks['tool.execute.after']({...input,args:output.args},{output:'Reference text'});
      return output.args;
    },
  };
}

test('blocks a repeated persisted 404 before network or approval without relying on after', async () => {
  const h = await harness([user(),missing()]);
  await assert.rejects(h.fetch(),/DREADOS_WEBFETCH_RETRY_BLOCKED.*HTTP 404.*No new request was sent/);
  assert.equal(h.fetches,0);
  assert.deepEqual(h.calls[0].path,{id:'ses_a'});
  assert.deepEqual(h.calls[0].query,{directory:'C:/projects/game',limit:120});
  assert.ok(h.calls[0].signal instanceof AbortSignal);
});

test('normalizes hostname, default port, and fragments without collapsing distinct URLs', async () => {
  const h = await harness([user(),missing()]);
  await assert.rejects(h.fetch('https://WWW.PAC-MAN.COM:443/faq.html#new'),/RETRY_BLOCKED/);
  await h.fetch('https://www.pac-man.com/');
  await h.fetch('https://www.pac-man.com/faq.html?lang=en');
  assert.equal(h.fetches,2);
});

test('a 404 stays blocked across new user tasks until the user names the URL again', async () => {
  const h = await harness([user(),missing(),user('user2',undefined,[{type:'text',text:'keeps trying to access a 404 webpage'}])]);
  await assert.rejects(h.fetch(),/HTTP 404 in this session.*unless the user explicitly asks/);
  h.messages.push(user('user3',undefined,[{type:'text',text:'Try www.pac-man.com/faq.html again, it is back up'}]));
  await h.fetch();
  assert.equal(h.fetches,1);
});

test('a 404 recorded only in an earlier block message still blocks after a new task', async () => {
  const h = await harness([user(),
    tool('DREADOS_WEBFETCH_RETRY_BLOCKED: This URL already failed with HTTP 404 in this session; the page does not exist.'),
    user('user2')]);
  await assert.rejects(h.fetch(),/HTTP 404/);
});

test('a new actual user task can retry after transient failures and their guard errors', async () => {
  const h = await harness([user(),tool('Request timed out'),tool('Request timed out'),
    tool('DREADOS_WEBFETCH_RETRY_BLOCKED: This URL already failed with two failed fetch attempts during the current user task.'),user('user2')]);
  await h.fetch();
  assert.equal(h.fetches,1);
});

test('automatic compaction and synthetic continuation do not reset retry guard', async () => {
  const h = await harness([user(),missing(),
    user('compact','ses_a',[{type:'compaction',auto:true}]),
    user('continue','ses_a',[{type:'text',synthetic:true,text:'Continue'}]),
  ]);
  await assert.rejects(h.fetch(),/RETRY_BLOCKED/);
});

test('compaction users and synthetic or ignored attachments do not reset retry guard', async () => {
  const summary = user('summary');
  summary.info.agent = 'compaction';
  // Transient failures, so an actual new task (the final file) is allowed to retry.
  const h = await harness([user(),tool('Request timed out'),tool('Request timed out'),summary,
    user('synthetic_file','ses_a',[{type:'file',synthetic:true,url:'data:image/png;base64,AA=='}]),
    user('ignored_file','ses_a',[{type:'file',ignored:true,url:'data:image/png;base64,AA=='}]),
  ]);
  await assert.rejects(h.fetch(),/RETRY_BLOCKED/);
  h.messages.push(user('actual_file','ses_a',[{type:'file',url:'data:image/png;base64,AA=='}]));
  await h.fetch();
  assert.equal(h.fetches,1);
});

test('a real user message with a per-message summary still starts a new task', async () => {
  const next = user('user2',undefined,[{type:'text',text:'Continue the unfinished task'}]);
  next.info.summary = {title:'Continue task',diffs:[]};
  const h = await harness([user(),tool('Request timed out'),tool('Request timed out'),next]);
  await h.fetch();
  assert.equal(h.fetches,1);
});

test('sessions are isolated and completed fetches remain repeatable', async () => {
  const h = await harness([user(),missing(),user('user_b','ses_b'),tool(undefined,{sessionID:'ses_b',status:'completed'})]);
  await h.fetch(URL,'ses_b');
  await h.fetch(URL,'ses_b');
  await assert.rejects(h.fetch(),/RETRY_BLOCKED/);
  assert.equal(h.fetches,2);
});

test('allows one transient retry then blocks repeated failures; a success resets failures', async () => {
  const h = await harness([user(),tool('Request timed out')]);
  await h.fetch();
  h.messages.push(tool('StatusCode: non 2xx status code (503 GET example)'));
  await assert.rejects(h.fetch(),/two failed fetch attempts/);
  h.messages.push(tool(undefined,{status:'completed'}));
  await h.fetch();
  assert.equal(h.fetches,2);
});

test('handles common 404/410 messages and ignores rejected approval or cancellation', async () => {
  for (const error of ['Request failed with status code: 404','HTTP 410','404 Not Found','410 Gone']) {
    const h = await harness([user(),tool(error)]);
    await assert.rejects(h.fetch(),/RETRY_BLOCKED/);
  }
  const h = await harness([user(),tool('Permission request rejected'),tool('Tool execution aborted'),tool('Cancelled')]);
  await h.fetch();
  assert.equal(h.fetches,1);
});

test('preserves metadata defaults and explicitly supplied options', async () => {
  const h = await harness([user()]);
  assert.deepEqual(await h.fetch(),{url:URL,timeout:30,format:'markdown'});
  assert.deepEqual(await h.fetch(URL,'ses_a',{timeout:60,format:'text'}),{url:URL,timeout:60,format:'text'});
});

test('history unavailable does not break ordinary tools or attempt external requests itself', async () => {
  for (const response of [async()=>{throw new Error('offline');},async()=>({error:{message:'bad request'}}),async()=>({data:{}})]) {
    const hooks = await WebFetchDefaults({client:{session:{messages:response}}});
    await hooks['tool.execute.before']({tool:'webfetch',sessionID:'ses_a'},{args:{url:URL}});
  }
  const hooks = await WebFetchDefaults();
  await hooks['tool.execute.before']({tool:'webfetch',sessionID:'ses_a'},{args:{url:URL}});
});

test('retains Windows curl executable correction and alias failure guidance', async () => {
  const hooks = await WebFetchDefaults();
  const output = {args:{command:'curl --fail https://example.test'}};
  await hooks['tool.execute.before']({tool:'bash'},output);
  assert.equal(output.args.command,process.platform === 'win32' ? 'curl.exe --fail https://example.test' : 'curl --fail https://example.test');
  await assert.rejects(hooks['tool.execute.after']({tool:'bash'},
    {output:'Invoke-WebRequest failed: missing mandatory parameters: Uri'}),/Use curl\.exe/);
});
