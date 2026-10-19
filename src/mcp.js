// Minimal MCP (Model Context Protocol) server over stdio: newline-delimited JSON-RPC 2.0.
import readline from 'node:readline';
import * as store from './store.js';

const SERVER_INFO = { name: 'agent-todo', version: '0.1.0' };

const INSTRUCTIONS = `This is the user's personal todo list. Each todo carries a "context" field with the
background the user would otherwise have to re-explain — always read it (get_todo) before working on a task.
- When asked to "do the next task", "看我的待辦", or similar: call list_todos (filter by project if you are inside a repo), pick one, then get_todo.
- When you start a task, set status to "doing". Record meaningful progress, decisions and blockers with add_note.
- When finished, call complete_todo with a short summary of what you did (files, PRs, follow-ups).
- If you discover new work, add it with add_todo including enough context for someone else to pick it up.`;

const filterProps = {
  status: { type: 'string', enum: ['open', 'all', ...store.STATUSES], description: 'Default "open" (everything not done)' },
  project: { type: 'string', description: 'Project name or path; matches by substring' },
  tag: { type: 'string' },
  assignee: { type: 'string', description: 'e.g. "me", "claude", "codex"' },
  query: { type: 'string', description: 'Full-text search across title, context, notes' },
};

const fieldProps = {
  title: { type: 'string' },
  context: { type: 'string', description: 'Background, links, acceptance criteria (markdown)' },
  priority: { type: 'string', enum: store.PRIORITIES },
  project: { type: 'string', description: 'Project name or absolute repo path' },
  tags: { type: 'array', items: { type: 'string' } },
  assignee: { type: 'string' },
  due: { type: 'string', description: 'YYYY-MM-DD' },
};

const id = { type: 'integer', description: 'Todo id' };

const TOOLS = [
  {
    name: 'list_todos',
    description: "List the user's todos (titles + metadata, no full context). Sorted: doing, then by priority and due date.",
    inputSchema: { type: 'object', properties: filterProps },
    run: (a) => {
      const todos = store.list(a);
      if (!todos.length) return 'No matching todos.';
      return todos.map((t) => store.formatTodo(t, { full: false }) + (t.context ? '  (has context)' : '')).join('\n');
    },
  },
  {
    name: 'get_todo',
    description: 'Get one todo with its full background context and progress notes. Read this before working on a task.',
    inputSchema: { type: 'object', properties: { id }, required: ['id'] },
    run: (a) => store.formatTodo(store.get(a.id)),
  },
  {
    name: 'add_todo',
    description: 'Create a new todo. Put all background needed to do it in "context".',
    inputSchema: { type: 'object', properties: fieldProps, required: ['title'] },
    run: (a) => `Created:\n${store.formatTodo(store.add(a))}`,
  },
  {
    name: 'update_todo',
    description: 'Change fields of a todo (e.g. status "doing"/"blocked", priority, context). Omitted fields stay unchanged.',
    inputSchema: {
      type: 'object',
      properties: { id, ...fieldProps, status: { type: 'string', enum: store.STATUSES } },
      required: ['id'],
    },
    run: ({ id, ...changes }) => `Updated:\n${store.formatTodo(store.update(id, changes))}`,
  },
  {
    name: 'add_note',
    description: 'Append a progress note / decision / blocker to a todo so the next person (or agent) has the history.',
    inputSchema: { type: 'object', properties: { id, text: { type: 'string' } }, required: ['id', 'text'] },
    run: (a, author) => `Noted:\n${store.formatTodo(store.addNote(a.id, a.text, author))}`,
  },
  {
    name: 'complete_todo',
    description: 'Mark a todo done, with a short summary of what was done.',
    inputSchema: { type: 'object', properties: { id, summary: { type: 'string' } }, required: ['id'] },
    run: (a, author) => `Completed:\n${store.formatTodo(store.complete(a.id, a.summary, author))}`,
  },
];

export function createHandler() {
  let author = 'agent';

  return function handle(msg) {
    const { id, method, params = {} } = msg;
    const reply = (result) => ({ jsonrpc: '2.0', id, result });
    const fail = (code, message) => ({ jsonrpc: '2.0', id, error: { code, message } });

    switch (method) {
      case 'initialize':
        author = params.clientInfo?.name || author;
        return reply({
          protocolVersion: params.protocolVersion || '2025-06-18',
          capabilities: { tools: {} },
          serverInfo: SERVER_INFO,
          instructions: INSTRUCTIONS,
        });
      case 'ping':
        return reply({});
      case 'tools/list':
        return reply({ tools: TOOLS.map(({ run, ...t }) => t) });
      case 'tools/call': {
        const tool = TOOLS.find((t) => t.name === params.name);
        if (!tool) return fail(-32602, `Unknown tool: ${params.name}`);
        try {
          const text = tool.run(params.arguments || {}, author);
          return reply({ content: [{ type: 'text', text }] });
        } catch (err) {
          return reply({ content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true });
        }
      }
      default:
        if (id === undefined) return null; // notification
        return fail(-32601, `Method not found: ${method}`);
    }
  };
}

export function runMcpServer() {
  const handle = createHandler();
  const rl = readline.createInterface({ input: process.stdin });
  rl.on('line', (line) => {
    if (!line.trim()) return;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } }) + '\n');
      return;
    }
    const res = handle(msg);
    if (res) process.stdout.write(JSON.stringify(res) + '\n');
  });
}
