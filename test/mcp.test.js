import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const bin = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'bin', 'todo.js');

test('MCP server over stdio', async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-todo-mcp-'));
  const child = spawn(process.execPath, [bin, 'mcp'], { env: { ...process.env, AGENT_TODO_HOME: home } });
  const lines = readline.createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  let nextId = 1;
  const rpc = async (method, params) => {
    const id = nextId++;
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    const res = JSON.parse((await lines.next()).value);
    assert.equal(res.id, id);
    return res;
  };
  const call = async (name, args) => (await rpc('tools/call', { name, arguments: args })).result;

  try {
    const init = await rpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'codex', version: '1' } });
    assert.equal(init.result.serverInfo.name, 'agent-todo');
    assert.equal(init.result.protocolVersion, '2025-06-18');
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');

    const { result } = await rpc('tools/list', {});
    assert.deepEqual(result.tools.map((t) => t.name), ['list_todos', 'get_todo', 'add_todo', 'update_todo', 'add_note', 'complete_todo']);

    await call('add_todo', { title: 'Write tests', context: 'Use node:test', project: 'todo' });
    assert.match((await call('list_todos', {})).content[0].text, /#1 Write tests/);
    assert.match((await call('get_todo', { id: 1 })).content[0].text, /Use node:test/);
    await call('add_note', { id: 1, text: 'halfway' });
    const done = await call('complete_todo', { id: 1, summary: 'all green' });
    assert.match(done.content[0].text, /status: done/);
    assert.match(done.content[0].text, /\(codex\) halfway/);

    const missing = await call('get_todo', { id: 42 });
    assert.equal(missing.isError, true);

    assert.equal((await rpc('nope', {})).error.code, -32601);
  } finally {
    child.kill();
  }
});
