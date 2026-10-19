"use strict";

// ---------- 小工具 ----------
const $ = (s) => document.querySelector(s);
const STATUS_LABEL = { doing: "進行中", todo: "待辦", blocked: "卡住", done: "已完成" };
const PRIORITY_LABEL = { high: "高", normal: "普通", low: "低" };
const DEV = new URLSearchParams(location.search).has("dev");
const REMOTE = window.agentTodoMode === "remote";
const MINI = !REMOTE && new URLSearchParams(location.search).has("mini");
let api = null;
let offline = false;
const READ_METHODS = new Set(["version", "list_todos", "list_trash", "parse_quick"]);

function setOffline(value) {
  if (!REMOTE) return;
  offline = value;
  document.body.classList.toggle("offline", value);
  $("#offlineBanner").classList.toggle("hidden", !value);
  if (!value) $("#offlineBanner").textContent = "連不到電腦，顯示的是上次的資料";
  document.querySelectorAll("#quickAdd input, #quickAdd textarea, #quickAdd select, #quickAdd button, .detail input, .detail textarea, .detail select, .detail .actions button, .detail .row button, .subtask button, .day-add input, .day-add button, .line input, .trash-item button, .calendar-head .danger").forEach(el => {
    if (value && !el.disabled) { el.dataset.offlineDisabled = "1"; el.disabled = true; }
    if (!value && el.dataset.offlineDisabled) { el.disabled = false; delete el.dataset.offlineDisabled; }
  });
}
new MutationObserver(() => { if (offline) setOffline(true); }).observe(document.body, { childList: true, subtree: true });

function toast(msg, ms = 2400, action = null) {
  const el = $("#toast");
  el.textContent = msg;
  if (action) el.append(h("button", { onclick: async (e) => {
    e.target.disabled = true;
    try { await action(); el.classList.add("hidden"); } catch { e.target.disabled = false; }
  } }, "復原"));
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
// 頂端的新增框、搜尋框不會被重新繪製，游標停在那裡時照樣自動更新
const editing = () => dragging || document.activeElement?.closest(".detail, #more, #aiPanel, .day-add, select");
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
  trash: [],
  view: localStorage.getItem("todoView") || "today",
  month: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  day: today(),
};
const VIEWS = { today: "今天", upcoming: "即將到期", all: "全部", calendar: "日曆", trash: "回收桶" };
const REPEAT_LABEL = { "": "不重複", daily: "每天", weekdays: "平日", weekly: "每週", monthly: "每月", yearly: "每年" };
if (!VIEWS[S.view]) S.view = "today";

async function reload() {
  try {
    const version = await api.version();
    const todos = await api.list_todos();
    const trash = await api.list_trash();
    Object.assign(S, { version, todos, trash });
    if (REMOTE) {
      try { localStorage.setItem("todoSnapshot", JSON.stringify({ todos, trash })); } catch { /* 儲存空間不足仍可操作 */ }
      setOffline(false);
    }
  } catch (e) {
    if (!REMOTE) throw e;
    setOffline(true);
    try {
      const cached = JSON.parse(localStorage.getItem("todoSnapshot"));
      if (cached) Object.assign(S, cached);
    } catch { /* 第一次開啟時還沒有快照 */ }
  }
  MINI ? renderMini() : render();
}

// AI 或 todo 指令改了清單：輪詢資料檔的修改時間，有變就重新載入
async function poll() {
  if (document.hidden) return;
  try {
    const v = await api.version();
    if (offline || (v !== S.version && !editing())) await reload();
  } catch {
    setOffline(true);
  } finally {
    if (!document.hidden) poll.timer = setTimeout(poll, 1500);
  }
}

async function save(id, fields) {
  const before = S.todos.find(t => t.id === id);
  const result = await call("update_todo", id, fields);
  await reload();
  if (fields.status === "done" && before?.status !== "done") {
    toast(result.nextId ? `已完成，已建立下一次 #${result.nextId}` : "已完成", 5000, async () => {
      await call("update_todo", id, { status: before.status });
      if (result.nextId) await call("purge_todo", result.nextId);
      await reload();
    });
  }
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
                   onchange: (e) => save(t.id, { status: e.target.checked ? "done" : t.reopenStatus || "todo" }) }),
      h("div", { class: "title", onclick: () => { open ? S.expanded.delete(t.id) : S.expanded.add(t.id); render(); } },
        h("span", { class: "id" }, `#${t.id}`), " ", t.title,
        h("div", { class: "badges" },
          t.priority === "high" && h("span", { class: "badge high" }, "高"),
          t.project && h("span", { class: "badge", title: t.project }, t.project.split(/[\\/]/).filter(Boolean).pop()),
          t.assignee && h("span", { class: "badge who" }, `@${t.assignee}`),
          t.due && h("span", { class: `badge${overdue ? " overdue" : t.due === today() ? " due-today" : ""}` }, t.due.slice(5)),
          t.subtasks.length > 0 && h("span", { class: "badge" }, `☑ ${t.subtasks.filter(s => s.done).length}/${t.subtasks.length}`),
          t.repeat && h("span", { class: "badge", title: REPEAT_LABEL[t.repeat] }, "🔁"),
          t.remindAt && h("span", { class: "badge", title: t.remindAt }, `⏰ ${t.remindAt.slice(11)}`),
          t.context && h("span", { class: "badge plain", title: "有背景說明" }, "📝"),
          t.notes.length > 0 && h("span", { class: "badge plain" }, `💬${t.notes.length}`)))));
  if (open) item.append(renderDetail(t));
  bindDrag(item, t, open);
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
  const subAdd = h("input", { placeholder: "新增子任務，Enter 送出", class: "sub-add" });
  subAdd.addEventListener("keydown", async e => {
    if (e.key !== "Enter" || e.isComposing || !subAdd.value.trim()) return;
    e.preventDefault();
    subAdd.disabled = true;
    try {
      await call("add_subtask", t.id, subAdd.value);
      await reload();
      document.querySelector(`#todo-${t.id} .sub-add`)?.focus();
    } finally { subAdd.disabled = false; }
  });

  return h("div", { class: "detail" },
    h("button", { class: "detail-close", onclick: () => { S.expanded.delete(t.id); render(); } }, "關閉詳細內容"),
    field("標題", text("title")),
    field("背景", context),
    h("div", { class: "row" }, field("狀態", select("status", STATUS_LABEL)), field("優先", select("priority", PRIORITY_LABEL))),
    h("div", { class: "row" }, field("專案", text("project", { list: "projects" })), field("負責", text("assignee", { list: "assignees" }))),
    h("div", { class: "row" },
      field("期限", text("due", { type: "date" })),
      field("標籤", h("input", { value: t.tags.join(", "), onchange: (e) => save(t.id, { tags: splitTags(e.target.value) }) }))),
    h("div", { class: "row" }, field("重複", select("repeat", REPEAT_LABEL))),
    field("提醒", h("div", { class: "row" }, text("remindAt", { type: "datetime-local" }),
      h("button", { onclick: () => save(t.id, { remindAt: "" }) }, "清除"))),
    h("div", { class: "subtasks" }, t.subtasks.map(s => h("div", { class: "subtask" },
      h("input", { type: "checkbox", checked: s.done, "aria-label": "完成子任務", onchange: async e => {
        await call("toggle_subtask", t.id, s.id, e.target.checked); await reload();
      } }),
      h("input", { value: s.title, "aria-label": "子任務標題", onchange: e => save(t.id, {
        subtasks: t.subtasks.map(x => x.id === s.id ? { ...x, title: e.target.value } : x)
      }) }),
      h("button", { title: "刪除子任務", onclick: async () => {
        await call("remove_subtask", t.id, s.id); await reload();
      } }, "×")))),
    subAdd,
    t.notes.length > 0 && h("ul", { class: "notes" },
      t.notes.map((n) => h("li", {}, h("span", { class: "meta" }, `${fmtTime(n.at)} · ${n.author}`), n.text))),
    note,
    h("div", { class: "actions" },
      !REMOTE && h("button", { onclick: () => copy(agentPrompt(t), "已複製，貼給 Claude Code／Codex 即可") }, "🤖 複製給 AI 的指令"),
      h("button", { class: "danger", onclick: async () => {
        await call("delete_todo", t.id);
        await reload();
        toast(`已刪除 #${t.id}`, 5000, async () => { await call("restore_todo", t.id); await reload(); });
      } }, "刪除")));
}

function render() {
  const project = $("#filterProject").value;
  const query = $("#filterQuery").value.trim().toLowerCase();
  const projects = [...new Set(S.todos.map((t) => t.project).filter(Boolean))].sort();
  $("#filterProject").replaceChildren(h("option", { value: "" }, "全部專案"),
    ...projects.map((p) => h("option", { value: p, selected: p === project }, p)));
  $("#projects").replaceChildren(...projects.map((p) => h("option", { value: p })));

  const matches = (t) => (!project || t.project === project) &&
    (!query || [t.title, t.context, t.project, ...t.tags, ...t.notes.map((n) => n.text)].join("\n").toLowerCase().includes(query));
  const filtered = S.todos.filter(matches);
  const visible = filtered.filter(t => inView(t, S.view));
  $("#tabs").replaceChildren(...Object.entries(VIEWS).map(([key, label]) => h("button", {
    class: S.view === key ? "active" : "", "aria-pressed": S.view === key,
    onclick: () => switchView(key)
  }, label, h("small", {}, key === "trash" ? S.trash.filter(matches).length : filtered.filter(t => inView(t, key)).length))));

  const board = $("#board");
  const scroll = board.scrollTop;
  board.replaceChildren();
  if (S.view === "calendar") { renderCalendar(board, filtered); return; }
  if (S.view === "trash") { renderTrash(board, S.trash.filter(matches)); return; }
  for (const status of ["doing", "todo", "blocked"]) {
    const items = visible.filter((t) => t.status === status);
    if (items.length) board.append(h("h2", {}, STATUS_LABEL[status], h("small", {}, items.length)), ...items.map(renderItem));
  }
  const done = visible.filter((t) => t.status === "done");
  if (done.length) {
    board.append(h("h2", { class: "toggle", onclick: () => { S.showDone = !S.showDone; render(); } },
      `${S.showDone ? "▾" : "▸"} 已完成`, h("small", {}, done.length)));
    if (S.showDone) board.append(...done.slice(0, 50).map(renderItem));
  }
  if (!visible.length) {
    board.append(h("p", { class: "empty" }, S.todos.length ? "沒有符合的待辦" : "還沒有待辦，從上面新增第一個吧",
      !S.todos.length && !REMOTE && h("br"), !S.todos.length && !REMOTE && "按右上角 🤖 接上 Claude Code／Codex"));
  }
  board.scrollTop = scroll;
}

// 小視窗點了某個待辦時，由 Python 呼叫
window.openTodo = async (id) => {
  await reload();
  const t = S.todos.find((x) => x.id === id);
  if (!t) return;
  S.view = "all";
  $("#filterQuery").value = "";
  $("#filterProject").value = "";
  if (t.status === "done") S.showDone = true;
  S.expanded.add(id);
  render();
  document.getElementById(`todo-${id}`)?.scrollIntoView({ block: "center" });
};

// ---------- 主視窗：新增 ----------
function bindMain() {
  $("#newTitle").addEventListener("input", previewQuick);
  $("#moreBtn").onclick = () => {
    $("#more").classList.toggle("hidden");
    if (!$("#more").classList.contains("hidden")) $("#newContext").focus();
  };
  $("#quickAdd").onsubmit = async (e) => {
    e.preventDefault();
    const raw = $("#newTitle").value;
    const explicit = {};
    for (const [key, id] of Object.entries({ context: "newContext", project: "newProject", priority: "newPriority",
      assignee: "newAssignee", due: "newDue", tags: "newTags", repeat: "newRepeat", remindAt: "newRemind" })) {
      const value = $(`#${id}`).value;
      if (value) explicit[key] = key === "tags" ? splitTags(value) : value;
    }
    const project = $("#filterProject").value;
    // 先清空再送出，送出期間接著打的下一件才不會被清掉
    e.target.reset();
    clearTimeout(previewQuick.timer);
    ++previewQuick.serial;
    $("#quickPreview").replaceChildren();
    $("#more").classList.add("hidden");
    $("#newTitle").focus();
    try {
      const fields = { ...await call("parse_quick", raw), ...explicit };
      if (!fields.project) fields.project = project;
      await call("add_todo", fields);
    } catch {
      if (!$("#newTitle").value) $("#newTitle").value = raw;
      return;
    }
    reload();
  };
  $("#filterProject").onchange = render;
  $("#filterQuery").oninput = render;
  $("#miniBtn").onclick = () => call("show_mini");
  if (DEV) $("#miniBtn").classList.add("hidden");
  $("#aiBtn").onclick = openAiPanel;
  if (REMOTE) ["aiBtn", "miniBtn", "mobileBtn"].forEach(id => $(`#${id}`).classList.add("hidden"));
  $("#mobileBtn").onclick = async () => {
    $("#mobilePanel").classList.remove("hidden");
    $("#mobileBody").textContent = "正在偵測 Tailscale…";
    try { renderMobile(await call("mobile_info")); } catch { $("#mobileBody").textContent = "讀取失敗，請關閉後重試"; }
  };
  $("#mobileClose").onclick = () => $("#mobilePanel").classList.add("hidden");
  $("#mobilePanel").onclick = e => { if (e.target.id === "mobilePanel") $("#mobileClose").click(); };
  $("#aiClose").onclick = () => $("#aiPanel").classList.add("hidden");
  $("#aiPanel").onclick = (e) => { if (e.target.id === "aiPanel") $("#aiPanel").classList.add("hidden"); };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $("#aiPanel").classList.add("hidden");
    if (e.key === "Escape") $("#mobilePanel").classList.add("hidden");
    if (e.key === "n" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $("#newTitle").focus(); }
    if (e.isComposing || e.ctrlKey || e.metaKey || e.altKey || e.target.closest("input, textarea, select, [contenteditable]")) return;
    if (e.key === "/") { e.preventDefault(); $("#filterQuery").focus(); }
    if (/^[1-5]$/.test(e.key)) switchView(Object.keys(VIEWS)[Number(e.key) - 1]);
  });
}

// ---------- 接上 AI ----------
function renderMobile(info) {
  const enabled = h("input", { type: "checkbox", checked: info.enabled, "aria-label": "手機存取" });
  const port = h("input", { type: "number", min: 1, max: 65535, value: info.port, "aria-label": "連接埠" });
  const configure = async (regenerate = false) => {
    try { renderMobile(await call("mobile_configure", enabled.checked, Number(port.value), regenerate)); }
    catch { enabled.checked = info.enabled; }
  };
  enabled.onchange = () => configure();
  const body = $("#mobileBody");
  body.replaceChildren(
    h("label", { class: "mobile-toggle" }, enabled, "開啟手機存取"),
    h("div", { class: "row" }, h("label", {}, "連接埠", port), h("button", { onclick: () => configure() }, "套用")),
    h("button", { onclick: () => { if (confirm("重新產生 token 後，舊的手機都要重新掃描 QR code 配對。繼續？")) configure(true); } }, "重新產生 token"),
    info.error && h("p", { class: "danger" }, info.error));
  if (!info.logged_in) {
    body.append(h("p", {}, "在電腦和手機安裝 Tailscale，登入同一個帳號，並確認電腦已連線。"),
      h("a", { href: "https://tailscale.com/download", target: "_blank", rel: "noopener noreferrer" }, "Tailscale 官網與下載"),
      info.tailscale_error && h("pre", { class: "cmd" }, info.tailscale_error));
  } else if (!info.serve_ready) {
    body.append(h("p", {}, "將 HTTPS 443 轉到這個連接埠："), h("pre", { class: "cmd" }, info.command),
      h("button", { onclick: async e => {
        e.target.disabled = true;
        try { renderMobile(await call("mobile_setup")); }
        catch (err) { body.append(h("pre", { class: "cmd" }, err.message)); }
        finally { e.target.disabled = false; }
      } }, "幫我設定"));
  }
  if (info.pair_url) {
    const qr = h("div", { class: "pair-qr" });
    qr.innerHTML = info.qr_svg;
    body.append(qr, h("button", { onclick: () => copy(info.pair_url) }, "複製網址"));
  } else if (!info.enabled) body.append(h("p", {}, "開啟手機存取後即可配對。"));
  body.append(h("button", { onclick: async () => renderMobile(await call("mobile_info")) }, "重新偵測"),
    h("p", { class: "hint" }, "iPhone：用 Safari 開啟，按分享 →「加入主畫面」。Android：用 Chrome 開啟，選「安裝應用程式」。電腦要開著 App，手機才能使用；縮到系統匣後仍可連線。"));
}

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
    const title = $("#miniTitle").value;
    if (!title.trim()) return;
    $("#miniTitle").value = "";
    try {
      await call("add_todo", await call("parse_quick", title));
    } catch {
      if (!$("#miniTitle").value) $("#miniTitle").value = title;
      return;
    }
    if (!$("#miniTitle").value) $("#miniTitle").blur();
    reload();
  };
  $("#miniExpand").onclick = () => api.close_mini();
  $("#miniClose").onclick = () => api.close_mini();
}

// ---------- 檢視與排序 ----------
function inView(t, view) {
  const date = today();
  const end = new Date(`${date}T12:00:00`);
  end.setDate(end.getDate() + 7);
  if (view === "today") return t.status !== "done" && (t.status === "doing" ||
    (t.due && t.due <= date) || (t.remindAt && t.remindAt.slice(0, 10) <= date));
  if (view === "upcoming") return t.status !== "done" && t.due > date && t.due <= end.toLocaleDateString("sv");
  if (view === "calendar") return Boolean(t.due);
  return true;
}
function switchView(view) {
  S.view = view;
  localStorage.setItem("todoView", view);
  render();
}
window.focusNewTodo = focus => { window.focus(); if (focus) $("#newTitle").focus(); };

async function previewQuick() {
  clearTimeout(previewQuick.timer);
  const serial = ++previewQuick.serial;
  const raw = $("#newTitle").value;
  previewQuick.timer = setTimeout(async () => {
    try {
      const p = await call("parse_quick", raw);
      if (serial !== previewQuick.serial) return;
      const labels = [p.due && `📅 ${p.due.slice(5).replace("-", "/")}`,
        p.remindAt && `⏰ ${p.remindAt.slice(11)}`, p.repeat && `🔁 ${REPEAT_LABEL[p.repeat]}`,
        ...(p.tags || []).map(x => `#${x}`), p.project && `+${p.project}`,
        p.assignee && `@${p.assignee}`, p.priority && `!${PRIORITY_LABEL[p.priority]}`].filter(Boolean);
      $("#quickPreview").replaceChildren(...labels.map(x => h("span", { class: "badge" }, x)));
    } catch { /* 錯誤由 call 顯示 */ }
  }, 150);
}
previewQuick.serial = 0;

let dragging = null;
function bindDrag(item, todo, open) {
  if (matchMedia("(pointer: coarse)").matches || offline) return;
  item.draggable = !open;
  item.addEventListener("dragstart", e => {
    if (open || editing() || e.target.closest("input, textarea, select, button")) { e.preventDefault(); return; }
    dragging = todo;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(todo.id));
    item.classList.add("dragging");
  });
  const allowed = () => dragging && !open && dragging.id !== todo.id &&
    dragging.status === todo.status && dragging.priority === todo.priority;
  item.addEventListener("dragover", e => {
    e.dataTransfer.dropEffect = allowed() ? "move" : "none";
    if (allowed()) e.preventDefault();
  });
  item.addEventListener("drop", async e => {
    if (!allowed()) return;
    e.preventDefault();
    const group = S.todos.filter(t => t.status === todo.status && t.priority === todo.priority).map(t => t.id);
    const source = dragging.id;
    const after = e.clientY > item.getBoundingClientRect().top + item.getBoundingClientRect().height / 2;
    group.splice(group.indexOf(source), 1);
    group.splice(group.indexOf(todo.id) + (after ? 1 : 0), 0, source);
    dragging = null;
    await call("reorder", group);
    await reload();
  });
  item.addEventListener("dragend", () => { dragging = null; item.classList.remove("dragging"); });
}

function renderTrash(board, todos) {
  board.append(h("div", { class: "calendar-head" }, h("h2", {}, "回收桶"), h("button", {
    class: "danger", disabled: !S.trash.length, onclick: async () => {
      if (!confirm("永久刪除回收桶內所有待辦？")) return;
      for (const t of S.trash) await call("purge_todo", t.id);
      await reload();
    }
  }, "清空回收桶")));
  board.append(...todos.map(t => h("article", { class: "item trash-item" },
    h("div", {}, `#${t.id} ${t.title}`, h("div", { class: "hint" }, `刪除於 ${fmtTime(t.deletedAt)}`)),
    h("div", { class: "actions" }, h("button", { onclick: async () => {
      await call("restore_todo", t.id); await reload();
    } }, "還原"), h("button", { class: "danger", onclick: async () => {
      if (!confirm(`永久刪除 #${t.id}？`)) return;
      await call("purge_todo", t.id); await reload();
    } }, "永久刪除")))));
  if (!todos.length) board.append(h("p", { class: "empty" }, "回收桶沒有符合的待辦"));
}

function renderCalendar(board, todos) {
  const move = offset => { S.month = new Date(S.month.getFullYear(), S.month.getMonth() + offset, 1); render(); };
  board.append(h("div", { class: "calendar-head" },
    h("button", { title: "上個月", onclick: () => move(-1) }, "‹"),
    h("b", {}, `${S.month.getFullYear()} / ${S.month.getMonth() + 1}`),
    h("button", { title: "下個月", onclick: () => move(1) }, "›"),
    h("button", { onclick: () => { S.month = new Date(new Date().getFullYear(), new Date().getMonth(), 1); S.day = today(); render(); } }, "今天")));
  const grid = h("div", { class: "calendar" });
  for (const name of ["日", "一", "二", "三", "四", "五", "六"]) grid.append(h("div", { class: "weekday" }, name));
  const first = S.month.getDay();
  const count = new Date(S.month.getFullYear(), S.month.getMonth() + 1, 0).getDate();
  for (let i = 0; i < Math.ceil((first + count) / 7) * 7; i++) {
    const day = i - first + 1;
    if (day < 1 || day > count) { grid.append(h("div", { class: "calendar-blank" })); continue; }
    const date = new Date(S.month.getFullYear(), S.month.getMonth(), day).toLocaleDateString("sv");
    const items = todos.filter(t => t.due === date);
    grid.append(h("button", { class: `calendar-day${S.day === date ? " selected" : ""}${date === today() ? " current" : ""}`,
      "aria-label": `${date}，${items.length} 件`, onclick: () => { S.day = date; render(); } },
      h("span", {}, day), h("div", { class: "day-titles" }, items.slice(0, 3).map(t => h("div", { title: t.title }, t.title)),
        items.length > 3 && h("div", {}, `+${items.length - 3}`)),
      items.length > 0 && h("div", { class: "day-dots", title: `${items.length} 件` }, `● ${items.length}`)));
  }
  board.append(grid, h("h2", {}, S.day), ...todos.filter(t => t.due === S.day).map(renderItem));
  const input = h("input", { placeholder: "新增這一天的待辦…", required: true });
  const form = h("form", { class: "day-add", onsubmit: async e => {
    e.preventDefault();
    const raw = input.value;
    if (!raw.trim()) return;
    const fields = await call("parse_quick", raw);
    if (!fields.due) fields.due = S.day;
    await call("add_todo", fields);
    await reload();
    $(".day-add input")?.focus();
  } }, input, h("button", { type: "submit" }, "新增"));
  board.append(form);
}

// ---------- 啟動 ----------
async function init() {
  if (init.started) return;
  init.started = true;
  api = window.pywebview?.api || httpApi();
  MINI ? bindMini() : bindMain();
  await reload();
  poll();
  document.addEventListener("visibilitychange", async () => {
    clearTimeout(poll.timer);
    if (!document.hidden) { await reload(); poll(); }
  });
  window.addEventListener("online", () => reload());
  if (REMOTE && "serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => toast("離線介面快取未啟用"));
}

// 開發模式（python main.py --dev）：在一般瀏覽器開啟時，透過 HTTP 呼叫同一組 API
function httpApi() {
  return new Proxy({}, { get: (_, name) => async (...args) => {
    if (offline && !READ_METHODS.has(name)) throw new Error("連不到電腦，目前僅供檢視");
    const r = await fetch(`/api/${name}`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(args), signal: AbortSignal.timeout(10000) });
    if (!r.ok) {
      if (REMOTE && r.status === 401) $("#offlineBanner").textContent = "請重新從電腦上的 App 掃描 QR code";
      throw new Error(r.status === 401 ? "請重新從電腦上的 App 掃描 QR code" : `HTTP ${r.status}`);
    }
    const body = await r.json();
    if (body.error) throw new Error(body.error);
    return body.result;
  } });
}
if (window.pywebview?.api) init();
else if (REMOTE || DEV) init();
else window.addEventListener("pywebviewready", init);
