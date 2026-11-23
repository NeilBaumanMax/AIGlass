import assert from 'node:assert/strict';
import { test } from 'node:test';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { once } from 'node:events';

const lib = resolve(process.env.NANOMUSE_CHECKOUT || '.local/nanomuse-upstream', 'harness/dsh-nanomuse/lib');
const { startBridge } = await import(pathToFileURL(join(lib, 'edith-bridge.js')));
const { HubError } = await import(pathToFileURL(join(lib, 'hub.js')));

test('desktop bridge: auth, persistence, duplicates, scoped approvals, cancellation and restart', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'edith-bridge-'));
  const token = 'test-credential-'.repeat(4);
  let executions = 0, active, finish, reject, approvals = [];
  const runner = {
    async createTaskSession() { return 'test-session'; },
    async task(args, call) {
      executions++;
      active = call;
      call.event({ stage: 'tool', name: 'delegate', summary: 'Open an app on the phone' });
      call.event({ stage: 'approval', approval_id: 'test-approval', preview: 'Open app', timeout: 30 });
      return new Promise((res, rej) => { finish = res; reject = rej; });
    },
    async approve(args, call) { approvals.push([args, call.id]); return { ok: true }; },
    async stop(args, call) {
      assert.equal(args.call, active.id);
      assert.equal(call.from.id, 'edith-glasses');
      reject(new HubError('cancelled', 'stopped'));
      return { stopped: true };
    },
  };
  const options = { runner, token, port: 0, journalPath: join(dir, 'turns.json'), account: () => 'test-account', status: () => ({ hub_connected: false }) };
  let server = startBridge(options);
  await once(server, 'listening');
  let base = `http://127.0.0.1:${server.address().port}`;
  const call = async (path, body, extra = {}) => {
    const response = await fetch(base + path, { method: body ? 'POST' : 'GET',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json', ...extra },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    return { code: response.status, body: await response.json() };
  };
  const identity = { conversation: randomUUID(), turn_id: randomUUID() };
  const query = () => '/v1/task?' + new URLSearchParams(identity);
  const terminal = async () => {
    for (let i = 0; i < 100; i++) {
      const result = (await call(query())).body;
      if (result.state !== 'accepted') return result;
      await new Promise(resolve => setTimeout(resolve, 5));
    }
    throw Error('Turn did not settle');
  };
  try {
    assert.equal((await call('/v1/status', null, { Authorization: 'bad' })).code, 401);
    assert.equal((await call('/v1/status', null, { Origin: 'https://example.org' })).code, 401);
    assert.equal((await call('/v1/status')).body.protocol, 1);
    assert.equal((await call('/v1/task', { text: 'bad IDs' })).code, 400);
    const task = { ...identity, new_conversation: true, text: 'Open app and read page' };
    assert.equal((await call('/v1/task', task)).body.state, 'accepted');
    assert.equal((await call('/v1/task', task)).body.state, 'accepted');
    assert.equal(executions, 1);
    assert.equal((await call('/v1/task', { ...task, turn_id: randomUUID() })).code, 409);
    assert.equal((await call('/v1/approve', { ...identity, approval_id: 'wrong', allow: true })).code, 403);
    assert.equal((await call('/v1/approve', { ...identity, approval_id: 'test-approval', allow: true })).body.ok, true);
    assert.equal(approvals.length, 1);
    assert.equal((await call('/v1/stop', { ...identity, turn_id: randomUUID() })).body.stopped, false);
    assert.equal((await call('/v1/stop', identity)).body.stopped, true);
    assert.equal((await terminal()).state, 'cancelled');
    identity.turn_id = randomUUID();
    await call('/v1/task', { ...identity, text: 'Read current page', new_conversation: false });
    finish({ text: 'Actual test page contents' });
    assert.equal((await terminal()).text, 'Actual test page contents');
    await new Promise(resolve => server.close(resolve));
    server = startBridge(options);
    await once(server, 'listening');
    base = `http://127.0.0.1:${server.address().port}`;
    const replay = await call('/v1/task', { ...identity, text: 'Do not repeat this' });
    assert.equal(replay.body.state, 'completed');
    assert.equal(executions, 2);
  } finally {
    await new Promise(resolve => server.close(resolve));
    await rm(dir, { recursive: true, force: true });
  }
});
