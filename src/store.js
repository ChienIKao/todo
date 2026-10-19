import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export const STATUSES = ['todo', 'doing', 'blocked', 'done'];
export const PRIORITIES = ['high', 'normal', 'low'];

export function dataDir() {
  return process.env.AGENT_TODO_HOME || path.join(os.homedir(), '.agent-todo');
}

export function dataFile() {
  return path.join(dataDir(), 'todos.json');
}

export function markdownFile() {
  return path.join(dataDir(), 'TODO.md');
}

function emptyDb() {
  return { version: 1, nextId: 1, todos: [] };
}

export function load() {
  try {
    const db = JSON.parse(fs.readFileSync(dataFile(), 'utf8'));
    db.todos ??= [];
    db.nextId ??= db.todos.reduce((m, t) => Math.max(m, t.id), 0) + 1;
    return db;
  } catch (err) {
    if (err.code === 'ENOENT') return emptyDb();
    throw err;
  }
}

function save(db) {
  fs.mkdirSync(dataDir(), { recursive: true });
  const tmp = `${dataFile()}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(db, null, 2) + '\n');
  fs.renameSync(tmp, dataFile());
  fs.writeFileSync(markdownFile(), toMarkdown(db.todos));
}

// CLI, web UI and MCP servers may all write at once, so serialize
// read-modify-write cycles with an exclusive lock file.
function withLock(fn) {
  fs.mkdirSync(dataDir(), { recursive: true });
  const lock = path.join(dataDir(), '.lock');
  const deadline = Date.now() + 5000;
  let fd;
  while (fd === undefined) {
    try {
      fd = fs.openSync(lock, 'wx');
    } catch (err) {
      if (err.code !== 'EEXIST') throw err;
      try {
        if (Date.now() - fs.statSync(lock).mtimeMs > 10000) fs.rmSync(lock, { force: true });
      } catch {}
      if (Date.now() > deadline) throw new Error(`Could not acquire lock ${lock}`);
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 20);
    }
  }
  try {
    return fn();
  } finally {
    fs.closeSync(fd);
    fs.rmSync(lock, { force: true });
  }
}

function mutate(fn) {
  return withLock(() => {
    const db = load();
    const result = fn(db);
    save(db);
    return result;
  });
}

function now() {
  return new Date().toISOString();
}

function findIn(db, id) {
  const todo = db.todos.find((t) => t.id === Number(id));
  if (!todo) throw new Error(`Todo #${id} not found`);
  return todo;
}

function check(field, value, allowed) {
  if (value !== undefined && !allowed.includes(value)) {
    throw new Error(`Invalid ${field} "${value}". Use one of: ${allowed.join(', ')}`);
  }
}

const PRIORITY_RANK = { high: 0, normal: 1, low: 2 };
const STATUS_RANK = { doing: 0, todo: 1, blocked: 2, done: 3 };

export function sortTodos(todos) {
  return [...todos].sort(
    (a, b) =>
      STATUS_RANK[a.status] - STATUS_RANK[b.status] ||
      PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority] ||
      (a.due || '9999').localeCompare(b.due || '9999') ||
      a.id - b.id,
  );
}

// "web" matches "~/code/web"; a repo path matches todos tagged with that path,
// a parent path, or just the repo's folder name.
export function projectMatches(todoProject, filter) {
  if (!todoProject) return false;
  const a = todoProject.toLowerCase().replace(/\/+$/, '');
  const b = filter.toLowerCase().replace(/\/+$/, '');
  return a.includes(b) || b.startsWith(`${a}/`) || path.basename(a) === path.basename(b);
}

/**
 * Filters: status ("open" = anything not done, "all" = everything),
 * project (substring match, case-insensitive), tag, assignee, query (text search).
 */
export function list(filters = {}) {
  const { status = 'open', project, tag, assignee, query } = filters;
  let todos = load().todos;
  if (status === 'open') todos = todos.filter((t) => t.status !== 'done');
  else if (status !== 'all') todos = todos.filter((t) => t.status === status);
  if (project) todos = todos.filter((t) => projectMatches(t.project, project));
  if (tag) todos = todos.filter((t) => t.tags.includes(tag));
  if (assignee) todos = todos.filter((t) => t.assignee === assignee);
  if (query) {
    const q = query.toLowerCase();
    todos = todos.filter((t) =>
      [t.title, t.context, t.project, ...t.tags, ...t.notes.map((n) => n.text)]
        .filter(Boolean)
        .some((s) => s.toLowerCase().includes(q)),
    );
  }
  return sortTodos(todos);
}

export function get(id) {
  return findIn(load(), id);
}

export function add(input) {
  if (!input.title?.trim()) throw new Error('title is required');
  check('priority', input.priority, PRIORITIES);
  check('status', input.status, STATUSES);
  return mutate((db) => {
    const ts = now();
    const todo = {
      id: db.nextId++,
      title: input.title.trim(),
      context: input.context?.trim() || '',
      status: input.status || 'todo',
      priority: input.priority || 'normal',
      project: input.project?.trim() || '',
      tags: input.tags || [],
      assignee: input.assignee || '',
      due: input.due || '',
      notes: [],
      createdAt: ts,
      updatedAt: ts,
      completedAt: input.status === 'done' ? ts : null,
    };
    db.todos.push(todo);
    return todo;
  });
}

const EDITABLE = ['title', 'context', 'status', 'priority', 'project', 'tags', 'assignee', 'due'];

export function update(id, changes) {
  check('priority', changes.priority, PRIORITIES);
  check('status', changes.status, STATUSES);
  return mutate((db) => {
    const todo = findIn(db, id);
    for (const key of EDITABLE) {
      if (changes[key] !== undefined) todo[key] = changes[key];
    }
    if (changes.status === 'done' && !todo.completedAt) todo.completedAt = now();
    if (changes.status && changes.status !== 'done') todo.completedAt = null;
    todo.updatedAt = now();
    return todo;
  });
}

export function addNote(id, text, author = 'me') {
  if (!text?.trim()) throw new Error('note text is required');
  return mutate((db) => {
    const todo = findIn(db, id);
    todo.notes.push({ at: now(), author, text: text.trim() });
    todo.updatedAt = now();
    return todo;
  });
}

export function complete(id, summary, author = 'me') {
  return mutate((db) => {
    const todo = findIn(db, id);
    if (summary?.trim()) todo.notes.push({ at: now(), author, text: `✅ ${summary.trim()}` });
    todo.status = 'done';
    todo.completedAt = now();
    todo.updatedAt = now();
    return todo;
  });
}

export function remove(id) {
  return mutate((db) => {
    const todo = findIn(db, id);
    db.todos = db.todos.filter((t) => t !== todo);
    return todo;
  });
}

export function formatTodo(t, { full = true } = {}) {
  const meta = [
    `status: ${t.status}`,
    `priority: ${t.priority}`,
    t.project && `project: ${t.project}`,
    t.assignee && `assignee: ${t.assignee}`,
    t.due && `due: ${t.due}`,
    t.tags.length && `tags: ${t.tags.join(', ')}`,
  ].filter(Boolean);
  let out = `#${t.id} ${t.title}\n  ${meta.join(' | ')}`;
  if (!full) return out;
  if (t.context) out += `\n\n## Context\n${t.context}`;
  if (t.notes.length) {
    out += '\n\n## Notes';
    for (const n of t.notes) out += `\n- [${n.at.slice(0, 16).replace('T', ' ')}] (${n.author}) ${n.text}`;
  }
  return out;
}

export function toMarkdown(todos) {
  const lines = [
    '# TODO',
    '',
    '> 由 agent-todo 自動產生，請勿手動編輯。用 `todo` CLI、桌面看板或 MCP 工具修改。',
    '',
  ];
  const groups = [
    ['doing', '進行中'],
    ['todo', '待辦'],
    ['blocked', '卡住'],
  ];
  const sorted = sortTodos(todos);
  for (const [status, label] of groups) {
    const items = sorted.filter((t) => t.status === status);
    if (!items.length) continue;
    lines.push(`## ${label}`, '');
    for (const t of items) {
      const meta = [t.priority !== 'normal' && t.priority, t.project, t.due && `due ${t.due}`, t.assignee && `@${t.assignee}`]
        .filter(Boolean)
        .join(' · ');
      lines.push(`- [ ] **#${t.id} ${t.title}**${meta ? ` — ${meta}` : ''}`);
      if (t.context) lines.push(...t.context.split('\n').map((l) => `  > ${l}`));
      for (const n of t.notes) lines.push(`  - _${n.at.slice(0, 10)} ${n.author}_: ${n.text}`);
    }
    lines.push('');
  }
  const done = todos
    .filter((t) => t.status === 'done')
    .sort((a, b) => (b.completedAt || '').localeCompare(a.completedAt || ''))
    .slice(0, 20);
  if (done.length) {
    lines.push('## 最近完成', '');
    for (const t of done) lines.push(`- [x] #${t.id} ${t.title}`);
    lines.push('');
  }
  return lines.join('\n');
}
