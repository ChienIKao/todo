#!/usr/bin/env node
import { execFile } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import * as store from '../src/store.js';

const HELP = `agent-todo — 待辦清單，Claude Code / Codex 也看得到

用法:
  todo                         列出未完成待辦（同 todo ls）
  todo ls [選項]               列出待辦
      -a, --all                  含已完成
      -p, --project <名稱>       只看某專案
      --here                     只看目前資料夾（git repo）的專案
      -q, --query <文字>         搜尋
  todo add <標題> [選項]       新增待辦
      -c, --context <文字>       背景說明（給 AI 看）；用 "-" 從 stdin 讀
      -p, --project <名稱>       專案名稱或路徑；--here 用目前 repo 路徑
      --high | --low             優先度
      --assign <who>             me / claude / codex …
      --due <YYYY-MM-DD>         期限
      -t, --tags <a,b>           標籤
  todo show <id>               顯示完整內容（含背景與筆記）
  todo start <id>              標記進行中
  todo block <id> [原因]       標記卡住
  todo done <id> [摘要]        標記完成
  todo note <id> <文字>        新增進度筆記
  todo edit <id> [選項]        修改欄位（同 add 的選項，另有 --title、--status）
  todo rm <id>                 刪除
  todo serve [--port 4567] [--open]   啟動桌面看板
  todo mcp                     以 MCP server 模式執行（給 Claude Code / Codex 用）
  todo setup                   顯示接上 Claude Code / Codex 的設定方式
  todo path                    顯示資料檔位置
`;

const OPTIONS = {
  all: { type: 'boolean', short: 'a' },
  project: { type: 'string', short: 'p' },
  here: { type: 'boolean' },
  query: { type: 'string', short: 'q' },
  context: { type: 'string', short: 'c' },
  high: { type: 'boolean' },
  low: { type: 'boolean' },
  assign: { type: 'string' },
  due: { type: 'string' },
  tags: { type: 'string', short: 't' },
  title: { type: 'string' },
  status: { type: 'string' },
  priority: { type: 'string' },
  port: { type: 'string' },
  open: { type: 'boolean' },
  help: { type: 'boolean', short: 'h' },
};

function repoRoot(dir = process.cwd()) {
  for (let d = dir; ; d = path.dirname(d)) {
    if (fs.existsSync(path.join(d, '.git'))) return d;
    if (path.dirname(d) === d) return dir;
  }
}

function fieldsFrom(values) {
  const fields = {};
  if (values.title !== undefined) fields.title = values.title;
  if (values.context !== undefined) fields.context = values.context === '-' ? fs.readFileSync(0, 'utf8') : values.context;
  if (values.here) fields.project = repoRoot();
  else if (values.project !== undefined) fields.project = values.project;
  if (values.high) fields.priority = 'high';
  if (values.low) fields.priority = 'low';
  if (values.priority) fields.priority = values.priority;
  if (values.status) fields.status = values.status;
  if (values.assign !== undefined) fields.assignee = values.assign;
  if (values.due !== undefined) fields.due = values.due;
  if (values.tags !== undefined) fields.tags = values.tags.split(',').map((s) => s.trim()).filter(Boolean);
  return fields;
}

const ICON = { todo: '○', doing: '◐', blocked: '⊘', done: '●' };

function printList(todos) {
  if (!todos.length) return console.log('（沒有待辦）');
  for (const t of todos) {
    const meta = [
      t.priority === 'high' && '!高',
      t.project && path.basename(t.project),
      t.assignee && `@${t.assignee}`,
      t.due && `due ${t.due}`,
      t.context && '📝',
      t.notes.length && `💬${t.notes.length}`,
    ].filter(Boolean);
    console.log(`${ICON[t.status]} #${String(t.id).padEnd(3)} ${t.title}${meta.length ? `  [${meta.join(' · ')}]` : ''}`);
  }
}

function setupText() {
  const bin = fileURLToPath(import.meta.url);
  return `資料檔: ${store.dataFile()}
Markdown 快照: ${store.markdownFile()}

── Claude Code ──────────────────────────────
claude mcp add --scope user todo -- node "${bin}" mcp

── Codex（~/.codex/config.toml）────────────
[mcp_servers.todo]
command = "node"
args = [${JSON.stringify(bin)}, "mcp"]

── 建議：讓 agent 預設會去看待辦 ────────────
把 docs/agent-instructions.md 的內容貼到
  ~/.claude/CLAUDE.md   （Claude Code 全域指示）
  ~/.codex/AGENTS.md    （Codex 全域指示）
`;
}

function openBrowser(url) {
  const cmd = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'explorer' : 'xdg-open';
  execFile(cmd, [url], () => {});
}

async function main() {
  const { values, positionals } = parseArgs({ options: OPTIONS, allowPositionals: true, strict: true });
  const [cmd = 'ls', ...rest] = positionals;
  if (values.help || cmd === 'help') return console.log(HELP);

  const id = rest[0];
  const needId = () => {
    if (!id || Number.isNaN(Number(id))) throw new Error(`用法: todo ${cmd} <id>`);
  };

  switch (cmd) {
    case 'ls':
    case 'list':
      return printList(
        store.list({
          status: values.all ? 'all' : 'open',
          project: values.here ? repoRoot() : values.project,
          query: values.query,
        }),
      );
    case 'add': {
      const fields = { ...fieldsFrom(values), title: rest.join(' ') || values.title };
      const t = store.add(fields);
      return console.log(`已新增 #${t.id} ${t.title}`);
    }
    case 'show':
      needId();
      return console.log(store.formatTodo(store.get(id)));
    case 'start':
      needId();
      store.update(id, { status: 'doing' });
      return console.log(`#${id} → 進行中`);
    case 'block':
      needId();
      store.update(id, { status: 'blocked' });
      if (rest[1]) store.addNote(id, `⊘ ${rest.slice(1).join(' ')}`);
      return console.log(`#${id} → 卡住`);
    case 'done':
      needId();
      store.complete(id, rest.slice(1).join(' '));
      return console.log(`#${id} → 完成 ✅`);
    case 'note':
      needId();
      store.addNote(id, rest.slice(1).join(' '));
      return console.log(`#${id} 已新增筆記`);
    case 'edit':
      needId();
      store.update(id, fieldsFrom(values));
      return console.log(store.formatTodo(store.get(id)));
    case 'rm':
      needId();
      store.remove(id);
      return console.log(`已刪除 #${id}`);
    case 'serve': {
      const { runServer } = await import('../src/server.js');
      const port = Number(values.port) || Number(process.env.AGENT_TODO_PORT) || 4567;
      runServer(port).on('listening', () => values.open && openBrowser(`http://localhost:${port}`));
      return;
    }
    case 'mcp': {
      const { runMcpServer } = await import('../src/mcp.js');
      return runMcpServer();
    }
    case 'setup':
      return console.log(setupText());
    case 'path':
      return console.log(store.dataFile());
    default:
      throw new Error(`未知指令: ${cmd}\n\n${HELP}`);
  }
}

main().catch((err) => {
  console.error(`錯誤: ${err.message}`);
  process.exit(1);
});
