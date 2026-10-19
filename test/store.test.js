import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { beforeEach, test } from 'node:test';

process.env.AGENT_TODO_HOME = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-todo-'));
const store = await import('../src/store.js');

beforeEach(() => fs.rmSync(store.dataFile(), { force: true }));

test('add, update, note, complete', () => {
  const t = store.add({ title: ' Fix login ', context: 'OAuth callback 500s', project: '/home/me/web', priority: 'high' });
  assert.equal(t.id, 1);
  assert.equal(t.title, 'Fix login');
  assert.equal(t.status, 'todo');

  store.update(t.id, { status: 'doing' });
  store.addNote(t.id, 'Found it: missing redirect URI', 'claude-code');
  const done = store.complete(t.id, 'Added redirect URI', 'claude-code');
  assert.equal(done.status, 'done');
  assert.ok(done.completedAt);
  assert.deepEqual(done.notes.map((n) => n.author), ['claude-code', 'claude-code']);

  assert.equal(store.list().length, 0);
  assert.equal(store.list({ status: 'all' }).length, 1);
});

test('list sorts doing first, then priority', () => {
  store.add({ title: 'low', priority: 'low' });
  store.add({ title: 'high', priority: 'high' });
  const doing = store.add({ title: 'doing' });
  store.update(doing.id, { status: 'doing' });
  assert.deepEqual(store.list().map((t) => t.title), ['doing', 'high', 'low']);
});

test('project filter matches repo paths and names', () => {
  store.add({ title: 'a', project: 'web' });
  store.add({ title: 'b', project: '/home/me/code/web' });
  store.add({ title: 'c', project: 'api' });
  assert.deepEqual(store.list({ project: '/home/me/code/web' }).map((t) => t.title), ['a', 'b']);
  assert.deepEqual(store.list({ project: '/home/me/code/web/src' }).map((t) => t.title), ['b']);
  assert.deepEqual(store.list({ project: 'api' }).map((t) => t.title), ['c']);
});

test('validation', () => {
  assert.throws(() => store.add({ title: '' }), /title is required/);
  assert.throws(() => store.add({ title: 'x', priority: 'urgent' }), /Invalid priority/);
  assert.throws(() => store.get(99), /not found/);
});

test('writes a markdown snapshot', () => {
  store.add({ title: 'Ship it', context: 'line one\nline two', priority: 'high' });
  const md = fs.readFileSync(store.markdownFile(), 'utf8');
  assert.match(md, /\*\*#1 Ship it\*\*/);
  assert.match(md, /> line two/);
});
