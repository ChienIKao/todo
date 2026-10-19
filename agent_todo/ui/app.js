"use strict";

// ---------- 小工具 ----------
const $ = (s) => document.querySelector(s);
const STATUS_LABEL = { doing: "進行中", todo: "待辦", blocked: "卡住", done: "已完成" };
const PRIORITY_LABEL = { high: "高", normal: "普通", low: "低" };
const DEV = new URLSearchParams(location.search).has("dev");
const MINI = new URLSearchParams(location.search).has("mini");
let api = null;

function toast(msg, ms = 2400) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.add("hidden"), ms);
}
async function call(name, ...args) {
  try {
    return await api[name](...args);
  } catch (e) {
    toast(`錯誤：${e?.message || e}`, 5000);
    throw e;
  }
}
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  el.append(...children.flat().filter((c) => c != null && c !== false));
  return el;
}
function fmtTime(iso) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
const splitTags = (s) => s.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
const today = () => new Date().toLocaleDateString("sv");
const editing = () => document.activeElement?.closest(".detail, #more, #miniAdd, #aiPanel");
async function copy(text, msg = "已複製") {
  await navigator.clipboard.writeText(text);
  toast(msg);
}

// ---------- 狀態 ----------
const S = {
  todos: [],
  version: 0,
  expanded: new Set(),
  showDone: false,
};

async function reload() {
  S.version = await api.version();
  S.todos = await api.list_todos();
  MINI ? renderMini() : render();
}

// AI 或 todo 指令改了清單：輪詢資料檔的修改時間，有變就重新載入
async function poll() {
  try {
    const v = await api.version();
    if (v !== S.version && !editing()) await reload();
  } finally {
    setTimeout(poll, 1500);
  }
}

async function save(id, fields) {
  await call("update_todo", id, fields);
  reload();
}

function agentPrompt(t) {
  return `請用 todo MCP 的 get_todo 讀取待辦 #${t.id}（${t.title}），依照裡面的背景完成它；開始時把狀態設成 doing，過程中用 add_note 記錄重點，完成後用 complete_todo 附上摘要。`;
}

// ---------- 主視窗：清單 ----------
function renderItem(t) {
  const open = S.expanded.has(t.id);
  const overdue = t.due && t.status !== "done" && t.due < today();
  const item = h("article", { class: `item ${t.status}`, id: `todo-${t.id}` },
    h("div", { class: "line" },
      h("input", { type: "checkbox", checked: t.status === "done", title: "完成",
                   onchange: (e) => save(t.id, { status: e.target.checked ? "done" : "todo" }) }),
      h("div", { class: "title", onclick: () => { open ? S.expanded.delete(t.id) : S.expanded.add(t.id); render(); } },
        h("span", { class: "id" }, `#${t.id}`), " ", t.title,
        h("div", { class: "badges" },
          t.priority === "high" && h("span", { class: "badge high" }, "高"),
          t.project && h("span", { class: "badge", title: t.project }, t.project.split(/[\\/]/).filter(Boolean).pop()),
          t.assignee && h("span", { class: "badge who" }, `@${t.assignee}`),
          t.due && h("span", { class: `badge${overdue ? " overdue" : ""}` }, t.due.slice(5)),
          t.context && h("span", { class: "badge plain", title: "有背景說明" }, "📝"),
          t.notes.length > 0 && h("span", { class: "badge plain" }, `💬${t.notes.length}`)))));
  if (open) item.append(renderDetail(t));
  return item;
}

function renderDetail(t) {
  const field = (label, el) => h("label", {}, h("span", {}, label), el);
  const select = (key, labels) => h("select", { onchange: (e) => save(t.id, { [key]: e.target.value }) },
    Object.entries(labels).map(([v, text]) => h("option", { value: v, selected: t[key] === v }, text)));
  const text = (key, attrs = {}) => h("input", { value: t[key] || "", ...attrs,
                                                 onchange: (e) => save(t.id, { [key]: e.target.value }) });

  const context = h("textarea", { rows: 6, placeholder: "背景／脈絡（AI 會讀這段）" });
  context.value = t.context;
  context.addEventListener("change", () => save(t.id, { context: context.value }));

  const note = h("input", { placeholder: "新增進度筆記，Enter 送出" });
  note.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter" || e.isComposing || !note.value.trim()) return;
    await call("add_note", t.id, note.value);
    note.blur();
    reload();
  });

  return h("div", { class: "detail" },
    field("標題", text("title")),
    field("背景", context),
    h("div", { class: "row" }, field("狀態", select("status", STATUS_LABEL)), field("優先", select("priority", PRIORITY_LABEL))),
    h("div", { class: "row" }, field("專案", text("project", { list: "projects" })), field("負責", text("assignee", { list: "assignees" }))),
    h("div", { class: "row" },
      field("期限", text("due", { type: "date" })),
      field("標籤", h("input", { value: t.tags.join(", "), onchange: (e) => save(t.id, { tags: splitTags(e.target.value) }) }))),
    t.notes.length > 0 && h("ul", { class: "notes" },
      t.notes.map((n) => h("li", {}, h("span", { class: "meta" }, `${fmtTime(n.at)} · ${n.author}`), n.text))),
    note,
    h("div", { class: "actions" },
      h("button", { onclick: () => copy(agentPrompt(t), "已複製，貼給 Claude Code／Codex 即可") }, "🤖 複製給 AI 的指令"),
      h("button", { class: "danger", onclick: async () => {
        if (!confirm(`刪除 #${t.id}「${t.title}」？`)) return;
        await call("delete_todo", t.id);
        reload();
      } }, "刪除")));
}

function render() {
  const project = $("#filterProject").value;
  const query = $("#filterQuery").value.trim().toLowerCase();
  const projects = [...new Set(S.todos.map((t) => t.project).filter(Boolean))].sort();
  $("#filterProject").replaceChildren(h("option", { value: "" }, "全部專案"),
    ...projects.map((p) => h("option", { value: p, selected: p === project }, p)));
  $("#projects").replaceChildren(...projects.map((p) => h("option", { value: p })));

  const visible = S.todos.filter((t) => (!project || t.project === project) &&
    (!query || [t.title, t.context, t.project, ...t.tags, ...t.notes.map((n) => n.text)].join("\n").toLowerCase().includes(query)));

  const board = $("#board");
  const scroll = board.scrollTop;
  board.replaceChildren();
  for (const status of ["doing", "todo", "blocked"]) {
    const items = visible.filter((t) => t.status === status);
    if (items.length) board.append(h("h2", {}, STATUS_LABEL[status], h("small", {}, items.length)), ...items.map(renderItem));
  }
  const done = visible.filter((t) => t.status === "done").sort((a, b) => (b.completedAt || "").localeCompare(a.completedAt || ""));
  if (done.length) {
    board.append(h("h2", { class: "toggle", onclick: () => { S.showDone = !S.showDone; render(); } },
      `${S.showDone ? "▾" : "▸"} 已完成`, h("small", {}, done.length)));
    if (S.showDone) board.append(...done.slice(0, 50).map(renderItem));
  }
  if (!visible.length) {
    board.append(h("p", { class: "empty" }, S.todos.length ? "沒有符合的待辦" : "還沒有待辦，從上面新增第一個吧",
      !S.todos.length && h("br"), !S.todos.length && "按右上角 🤖 接上 Claude Code／Codex"));
  }
  board.scrollTop = scroll;
}

// 小視窗點了某個待辦時，由 Python 呼叫
window.openTodo = async (id) => {
  await reload();
  const t = S.todos.find((x) => x.id === id);
  if (!t) return;
  if (t.status === "done") S.showDone = true;
  S.expanded.add(id);
  render();
  document.getElementById(`todo-${id}`)?.scrollIntoView({ block: "center" });
};

// ---------- 主視窗：新增 ----------
function bindMain() {
  $("#moreBtn").onclick = () => {
    $("#more").classList.toggle("hidden");
    if (!$("#more").classList.contains("hidden")) $("#newContext").focus();
  };
  $("#quickAdd").onsubmit = async (e) => {
    e.preventDefault();
    await call("add_todo", {
      title: $("#newTitle").value,
      context: $("#newContext").value,
      project: $("#newProject").value || $("#filterProject").value,
      priority: $("#newPriority").value,
      assignee: $("#newAssignee").value,
      due: $("#newDue").value,
      tags: splitTags($("#newTags").value),
    });
    e.target.reset();
    $("#more").classList.add("hidden");
    $("#newTitle").focus();
    reload();
  };
  $("#filterProject").onchange = render;
  $("#filterQuery").oninput = render;
  $("#miniBtn").onclick = () => call("show_mini");
  if (DEV) $("#miniBtn").classList.add("hidden");
  $("#aiBtn").onclick = openAiPanel;
  $("#aiClose").onclick = () => $("#aiPanel").classList.add("hidden");
  $("#aiPanel").onclick = (e) => { if (e.target.id === "aiPanel") $("#aiPanel").classList.add("hidden"); };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $("#aiPanel").classList.add("hidden");
    if (e.key === "n" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $("#newTitle").focus(); }
  });
}

// ---------- 接上 AI ----------
async function openAiPanel() {
  $("#aiPanel").classList.remove("hidden");
  renderAi(await call("info"));
}

function renderAi(info) {
  const check = (ok, text) => h("div", { class: ok ? "ok" : "" }, `${ok ? "✓" : "○"} ${text}`);
  const tool = (name, key, st, manual) => {
    const done = st.mcp && st.instructions;
    return h("section", { class: "tool" },
      h("div", { class: "tool-head" },
        h("b", {}, name),
        h("button", { class: done ? "" : "primary", onclick: async (e) => {
          e.target.disabled = true;
          try {
            renderAi(await call(key));
            toast(`${name} 設定完成，重新開啟 ${name} 後生效`, 4000);
          } finally {
            e.target.disabled = false;
          }
        } }, done ? "重新設定" : "一鍵設定")),
      h("div", { class: "checks" },
        check(st.mcp, "MCP server（讓它能讀寫待辦）"),
        check(st.instructions, `全域指示（${key === "setup_claude" ? "~/.claude/CLAUDE.md" : "~/.codex/AGENTS.md"}）`)),
      !st.installed && h("div", { class: "hint" }, `這台電腦好像還沒有安裝 ${name}。`),
      h("details", {}, h("summary", {}, "手動設定"), manual));
  };
  const s = info.status;
  $("#aiBody").replaceChildren(
    h("p", { class: "hint" }, "設定好之後，在 Claude Code 或 Codex 裡說「看一下我的待辦」「處理 #3」，它就會自己讀背景、記進度、完成後回報。"),
    tool("Claude Code", "setup_claude", s.claude,
      h("div", {}, h("pre", { class: "cmd" }, info.claude_command),
        h("button", { onclick: () => copy(info.claude_command) }, "複製指令"))),
    tool("Codex", "setup_codex", s.codex,
      h("div", {}, h("div", { class: "hint" }, "加到 ~/.codex/config.toml："), h("pre", { class: "cmd" }, info.codex_toml),
        h("button", { onclick: () => copy(info.codex_toml) }, "複製設定"))),
    h("section", { class: "tool" },
      h("b", {}, "全域指示內容"),
      h("pre", { class: "cmd" }, info.instructions),
      h("button", { onclick: () => copy(info.instructions) }, "複製")),
    h("section", { class: "tool" },
      h("div", { class: "hint" }, `資料檔：${info.data_file}`, h("br"), `沒接 MCP 的 AI 也可以直接讀：${info.markdown_file}`),
      h("div", { class: "tool-head" },
        h("button", { onclick: () => call("open_data_dir") }, "開啟資料夾"),
        h("span", { class: "hint" }, `版本 ${info.version}`))));
}

// ---------- 置頂小視窗 ----------
function renderMini() {
  const open = S.todos.filter((t) => t.status !== "done");
  $("#miniCount").textContent = open.length ? `${open.length} 件` : "";
  $("#miniList").replaceChildren(...open.map((t) =>
    h("div", { class: `mini-item ${t.status}${t.priority === "high" ? " high" : ""}` },
      h("input", { type: "checkbox", title: "完成", onchange: () => save(t.id, { status: "done" }) }),
      h("div", { class: "t", title: "在主視窗開啟", onclick: () => api.open_in_main(t.id) }, t.title))));
  if (!open.length) $("#miniList").append(h("p", { class: "empty" }, "都做完了 🎉"));
}

function bindMini() {
  document.body.classList.add("mini-mode");
  $("#app").classList.add("hidden");
  $("#mini").classList.remove("hidden");
  $("#miniAdd").onsubmit = async (e) => {
    e.preventDefault();
    if (!$("#miniTitle").value.trim()) return;
    await call("add_todo", { title: $("#miniTitle").value });
    $("#miniTitle").value = "";
    $("#miniTitle").blur();
    reload();
  };
  $("#miniExpand").onclick = () => api.close_mini();
  $("#miniClose").onclick = () => api.close_mini();
}

// ---------- 啟動 ----------
async function init() {
  api = window.pywebview.api;
  MINI ? bindMini() : bindMain();
  await reload();
  poll();
}

// 開發模式（python main.py --dev）：在一般瀏覽器開啟時，透過 HTTP 呼叫同一組 API
function httpApi() {
  return new Proxy({}, { get: (_, name) => async (...args) => {
    const r = await fetch(`/api/${name}`, { method: "POST", body: JSON.stringify(args) });
    const body = await r.json();
    if (body.error) throw new Error(body.error);
    return body.result;
  } });
}
if (window.pywebview?.api) init();
else if (DEV) { window.pywebview = { api: httpApi() }; init(); }
else window.addEventListener("pywebviewready", init);
