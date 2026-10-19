const $ = (s, el = document) => el.querySelector(s);
const STATUS_LABEL = { doing: '進行中', todo: '待辦', blocked: '卡住', done: '已完成' };
const PRIORITY_LABEL = { high: '高', normal: '普通', low: '低' };

let todos = [];
const expanded = new Set();
let showDone = false;

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'content-type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function refresh() {
  todos = await api('GET', '/api/todos');
  render();
}

function toast(msg) {
  const el = $('#toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), 1800);
}

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? '' : v);
  }
  el.append(...children.flat().filter((c) => c != null && c !== false));
  return el;
}

function fmtTime(iso) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function agentPrompt(t) {
  return `請用 agent-todo MCP 的 get_todo 讀取待辦 #${t.id}（${t.title}），依照裡面的背景完成它；開始時把狀態設成 doing，過程中用 add_note 記錄重點，完成後用 complete_todo 附上摘要。`;
}

function save(id, changes) {
  return api('PATCH', `/api/todos/${id}`, changes).then(refresh).catch((e) => toast(e.message));
}

function renderItem(t) {
  const open = expanded.has(t.id);
  const overdue = t.due && t.status !== 'done' && t.due < new Date().toISOString().slice(0, 10);
  const item = h(
    'article',
    { class: `item ${t.status} p-${t.priority}${open ? ' open' : ''}` },
    h(
      'div',
      { class: 'line' },
      h('input', {
        type: 'checkbox',
        checked: t.status === 'done',
        title: '完成',
        onchange: (e) => save(t.id, { status: e.target.checked ? 'done' : 'todo' }),
      }),
      h(
        'div',
        { class: 'title', onclick: () => (open ? expanded.delete(t.id) : expanded.add(t.id), render()) },
        h('span', { class: 'id' }, `#${t.id}`),
        ' ',
        t.title,
        h(
          'div',
          { class: 'badges' },
          t.priority === 'high' && h('span', { class: 'badge high' }, '高'),
          t.project && h('span', { class: 'badge' }, t.project.split('/').filter(Boolean).pop()),
          t.assignee && h('span', { class: 'badge who' }, `@${t.assignee}`),
          t.due && h('span', { class: `badge${overdue ? ' overdue' : ''}` }, t.due.slice(5)),
          t.context && h('span', { class: 'badge muted', title: '有背景說明' }, '📝'),
          t.notes.length > 0 && h('span', { class: 'badge muted' }, `💬${t.notes.length}`),
        ),
      ),
    ),
  );
  if (open) item.append(renderDetail(t));
  return item;
}

function renderDetail(t) {
  const field = (label, el) => h('label', {}, h('span', {}, label), el);
  const select = (key, options, labels) =>
    h(
      'select',
      { onchange: (e) => save(t.id, { [key]: e.target.value }) },
      options.map((o) => h('option', { value: o, selected: t[key] === o }, labels[o])),
    );
  const text = (key, attrs = {}) =>
    h('input', { value: t[key] || '', ...attrs, onchange: (e) => save(t.id, { [key]: e.target.value }) });

  const context = h('textarea', { rows: 6, placeholder: '背景 / 脈絡（AI 會讀這段）' });
  context.value = t.context;
  context.addEventListener('change', () => save(t.id, { context: context.value }));

  const note = h('input', { placeholder: '新增進度筆記，Enter 送出' });
  note.addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter' || !note.value.trim() || e.isComposing) return;
    await api('POST', `/api/todos/${t.id}/notes`, { text: note.value }).catch((err) => toast(err.message));
    refresh();
  });

  return h(
    'div',
    { class: 'detail' },
    field('標題', text('title')),
    field('背景', context),
    h(
      'div',
      { class: 'row' },
      field('狀態', select('status', ['todo', 'doing', 'blocked', 'done'], STATUS_LABEL)),
      field('優先', select('priority', ['high', 'normal', 'low'], PRIORITY_LABEL)),
    ),
    h('div', { class: 'row' }, field('專案', text('project', { list: 'projects' })), field('負責', text('assignee', { list: 'assignees' }))),
    h(
      'div',
      { class: 'row' },
      field('期限', text('due', { type: 'date' })),
      field(
        '標籤',
        h('input', {
          value: t.tags.join(', '),
          onchange: (e) => save(t.id, { tags: splitTags(e.target.value) }),
        }),
      ),
    ),
    t.notes.length > 0 &&
      h(
        'ul',
        { class: 'notes' },
        t.notes.map((n) => h('li', {}, h('span', { class: 'meta' }, `${fmtTime(n.at)} · ${n.author}`), n.text)),
      ),
    note,
    h(
      'div',
      { class: 'actions' },
      h(
        'button',
        {
          onclick: async () => {
            await navigator.clipboard.writeText(agentPrompt(t));
            toast('已複製，貼給 Claude Code / Codex 即可');
          },
        },
        '🤖 複製給 AI 的指令',
      ),
      h(
        'button',
        {
          class: 'danger',
          onclick: async () => {
            if (!confirm(`刪除 #${t.id}「${t.title}」？`)) return;
            await api('DELETE', `/api/todos/${t.id}`);
            refresh();
          },
        },
        '刪除',
      ),
    ),
  );
}

function splitTags(s) {
  return s.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
}

function render() {
  const project = $('#filter-project').value;
  const query = $('#filter-query').value.trim().toLowerCase();

  const projects = [...new Set(todos.map((t) => t.project).filter(Boolean))].sort();
  const sel = $('#filter-project');
  sel.replaceChildren(h('option', { value: '' }, '全部專案'), ...projects.map((p) => h('option', { value: p, selected: p === project }, p)));
  $('#projects').replaceChildren(...projects.map((p) => h('option', { value: p })));

  const visible = todos.filter(
    (t) =>
      (!project || t.project === project) &&
      (!query || [t.title, t.context, t.project, ...t.tags, ...t.notes.map((n) => n.text)].join('\n').toLowerCase().includes(query)),
  );

  const board = $('#board');
  board.replaceChildren();
  for (const status of ['doing', 'todo', 'blocked']) {
    const items = visible.filter((t) => t.status === status);
    if (!items.length) continue;
    board.append(h('h2', {}, `${STATUS_LABEL[status]} `, h('small', {}, items.length)), ...items.map(renderItem));
  }
  const done = visible.filter((t) => t.status === 'done').sort((a, b) => (b.completedAt || '').localeCompare(a.completedAt || ''));
  if (done.length) {
    board.append(
      h('h2', { class: 'toggle', onclick: () => ((showDone = !showDone), render()) }, `${showDone ? '▾' : '▸'} 已完成 `, h('small', {}, done.length)),
    );
    if (showDone) board.append(...done.slice(0, 50).map(renderItem));
  }
  if (!visible.length) board.append(h('p', { class: 'empty' }, todos.length ? '沒有符合的待辦' : '還沒有待辦，從上面新增第一個吧 ✨'));
}

$('#toggle-more').addEventListener('click', () => {
  $('#more').hidden = !$('#more').hidden;
  if (!$('#more').hidden) $('#new-context').focus();
});

$('#quick-add').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
    title: $('#new-title').value,
    context: $('#new-context').value,
    project: $('#new-project').value || $('#filter-project').value,
    priority: $('#new-priority').value,
    assignee: $('#new-assignee').value,
    due: $('#new-due').value,
    tags: splitTags($('#new-tags').value),
  };
  try {
    await api('POST', '/api/todos', body);
    e.target.reset();
    $('#more').hidden = true;
    refresh();
  } catch (err) {
    toast(err.message);
  }
});

$('#filter-project').addEventListener('change', render);
$('#filter-query').addEventListener('input', render);

// Live updates when Claude Code / Codex / the CLI change the list.
new EventSource('/api/events').onmessage = () => {
  // Don't clobber a field the user is typing in.
  if (document.activeElement?.closest('.detail')) return;
  refresh();
};

refresh();
