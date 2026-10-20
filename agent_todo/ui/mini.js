"use strict";

const MINI_DEFAULTS = { layout: "focus", badges: { due: true, assignee: true, project: false,
  remind: true, subtasks: true, priority: true }, scope: "open", scopeValue: "", density: "compact",
  fontSize: "normal", addBox: "button", timelineDays: 14 };
const MINI_LAYOUTS = { list: "清單", focus: "現在做什麼", timeline: "時間軸" };
let miniPrefs = { ...MINI_DEFAULTS, badges: { ...MINI_DEFAULTS.badges } };
let miniAdding = false;
let miniUndated = false;
let prefWrites = 0;
let prefQueue = Promise.resolve();
let settingsTab = "general";
let miniSettingsTab = "layout";
let settingsOpener = null;

// 用本地日期的中午計算天數，避免日光節約時間造成跨日誤差。
function miniDayOffset(date, base) {
  return Math.round((new Date(`${date}T12:00:00`) - new Date(`${base}T12:00:00`)) / 86400000);
}
function miniRelativeDate(date, base) {
  const days = miniDayOffset(date, base);
  if (days === 0) return "今天";
  if (days === 1) return "明天";
  const day = new Date(`${date}T12:00:00`).getDay();
  if (days > 1 && days < 7) return `週${"日一二三四五六"[day]}`;
  const baseDay = new Date(`${base}T12:00:00`).getDay();
  const nextMonday = 8 - (baseDay || 7);
  if (days >= 7 && days >= nextMonday && days < nextMonday + 7) return `下週${"日一二三四五六"[day]}`;
  return `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}`;
}
function miniDueHint(date, base) {
  const days = miniDayOffset(date, base);
  return days < 0 ? `逾期 ${-days} 天` : `${miniRelativeDate(date, base)}到期`;
}
function miniNext(todos) {
  const rank = { high: 0, normal: 1, low: 2 };
  return todos.filter(t => t.status !== "done").slice().sort((a, b) => {
    if (a.due || b.due) return (a.due || "9999").localeCompare(b.due || "9999") ||
      (rank[a.priority] ?? 1) - (rank[b.priority] ?? 1) || Number(b.status === "doing") - Number(a.status === "doing");
    return Number(b.status === "doing") - Number(a.status === "doing") || (rank[a.priority] ?? 1) - (rank[b.priority] ?? 1);
  })[0];
}
function miniFocusGroups(todos, base) {
  const groups = { overdue: [], today: [], tomorrow: [], week: [], blocked: [], other: [] };
  for (const t of todos) {
    const days = t.due ? miniDayOffset(t.due, base) : null;
    const key = days !== null && days < 0 ? "overdue" : days === 0 ? "today" : days === 1 ? "tomorrow" :
      days !== null && days <= 7 ? "week" : t.status === "blocked" ? "blocked" : "other";
    groups[key].push(t);
  }
  return groups;
}
function miniTimelineGroups(todos, base, days) {
  const groups = { overdue: [], [base]: [], undated: [], later: [] };
  for (const t of todos) {
    const offset = t.due ? miniDayOffset(t.due, base) : null;
    const key = offset === null ? "undated" : offset < 0 ? "overdue" : offset >= days ? "later" : t.due;
    (groups[key] ||= []).push(t);
  }
  return groups;
}

function updateMiniPref(changes) {
  miniPrefs = { ...miniPrefs, ...changes, badges: { ...miniPrefs.badges, ...changes.badges } };
  if (MINI) renderMini();
  // 每次只寫變動欄位，兩個視窗各自調整時不會覆蓋其他設定。
  ++prefWrites;
  prefQueue = prefQueue.catch(() => {}).then(() => call("set_prefs", { mini: changes }))
    .finally(() => { --prefWrites; });
  prefQueue.catch(() => {});
}
function miniScopeTodos() {
  return S.todos.filter(t => t.status !== "done" && (miniPrefs.scope === "today" ? inView(t, "today") :
    miniPrefs.scope === "project" ? t.project === miniPrefs.scopeValue :
    miniPrefs.scope === "assignee" ? t.assignee === miniPrefs.scopeValue : true));
}
function miniBadge(name, text, cls = "") {
  return h("span", { class: `mini-badge ${cls}`, title: text }, icon(name), text);
}
function miniBadges(t, focus = false, inTimeline = false) {
  const b = miniPrefs.badges;
  const badges = [];
  // 提醒跟期限同一天就只標提醒時間；時間軸左邊已經有日期，期限不用再標
  const remindSameDay = b.remind && t.remindAt && t.remindAt.slice(0, 10) === t.due;
  if (focus && b.priority) badges.push(miniBadge("flag", PRIORITY_LABEL[t.priority] || "普通", t.priority === "high" ? "overdue" : ""));
  if (b.due && t.due && !inTimeline && !remindSameDay) badges.push(miniBadge("calendar", focus ? miniDueHint(t.due, today()) : miniRelativeDate(t.due, today()),
    t.due < today() ? "overdue" : t.due === today() ? "due-today" : ""));
  if (b.assignee && t.assignee) badges.push(miniBadge("user", t.assignee));
  if (b.project && t.project) badges.push(miniBadge("folder", t.project.split(/[\\/]/).filter(Boolean).pop()));
  if (b.remind && t.remindAt) badges.push(miniBadge("alarm-clock", inTimeline && remindSameDay ? t.remindAt.slice(11, 16)
    : `${miniRelativeDate(t.remindAt.slice(0, 10), today())} ${t.remindAt.slice(11, 16)}`));
  if (b.subtasks && t.subtasks?.length) badges.push(miniBadge("checkbox-on", `${t.subtasks.filter(s => s.done).length}/${t.subtasks.length}`));
  if (focus && t.context) badges.push(miniBadge("note", "有背景"));
  return badges;
}
function miniRow(t, focus = false, inTimeline = false) {
  return h("div", { class: `mini-row${focus ? " mini-focus" : ""}` },
    miniPrefs.badges.priority && !focus && h("span", { class: `mini-dot ${t.priority}`, title: `優先度：${PRIORITY_LABEL[t.priority]}` }),
    checkbox({ title: `完成 ${t.title}`, onchange: e => { e.target.disabled = true; save(t.id, { status: "done" }).catch(() => { e.target.disabled = false; e.target.checked = false; }); } }),
    h("button", { class: "mini-title", title: t.title, onclick: () => call("open_in_main", t.id) }, t.title),
    h("div", { class: "mini-badges" }, miniBadges(t, focus, inTimeline)));
}
function miniSection(label, items) {
  return h("section", {}, h("h2", {}, label, h("small", {}, String(items.length))), items.map(t => miniRow(t)));
}
function renderMini() {
  const open = miniScopeTodos();
  const base = today();
  const root = $("#mini");
  root.dataset.density = miniPrefs.density;
  root.dataset.fontSize = miniPrefs.fontSize;
  $("#miniName").textContent = MINI_LAYOUTS[miniPrefs.layout];
  $("#miniCount").textContent = `今天 ${open.filter(t => inView(t, "today")).length} · 卡住 ${open.filter(t => t.status === "blocked").length}`;
  $("#miniAddBtn").classList.toggle("hidden", miniPrefs.addBox !== "button");
  $("#miniAdd").classList.toggle("hidden", miniPrefs.addBox === "button" && !miniAdding);
  $("#miniAdd").classList.toggle("at-bottom", miniPrefs.addBox === "bottom");
  const list = $("#miniList");
  list.replaceChildren();
  if (miniPrefs.layout === "list") {
    for (const status of ["doing", "todo", "blocked"]) {
      const items = open.filter(t => t.status === status);
      if (items.length) list.append(miniSection(STATUS_LABEL[status], items));
    }
  } else if (miniPrefs.layout === "focus") {
    const next = miniNext(open);
    if (next) list.append(h("section", { class: "mini-next" }, h("div", { class: "mini-kicker" }, "下一件事"), miniRow(next, true)));
    const groups = miniFocusGroups(open.filter(t => t !== next), base);
    for (const [key, label] of Object.entries({ overdue: "逾期", today: "今天到期", tomorrow: "明天到期", week: "這週", blocked: "卡住" })) {
      if (groups[key].length) list.append(miniSection(label, groups[key]));
    }
    if (groups.other.length) list.append(h("button", { class: "mini-more", onclick: () => updateMiniPref({ layout: "list" }) }, `還有 ${groups.other.length} 件　看全部`));
  } else {
    const groups = miniTimelineGroups(open, base, miniPrefs.timelineDays);
    for (const key of ["overdue", ...Object.keys(groups).filter(k => /^\d{4}-/.test(k)).sort()]) {
      const items = groups[key];
      if (!items.length && key !== base) continue;
      list.append(h("section", { class: `mini-day${key === base ? " today" : ""}` },
        h("div", { class: "mini-date" }, key === "overdue" ? "逾期" : miniRelativeDate(key, base),
          key !== "overdue" && /[天週]/.test(miniRelativeDate(key, base)) && h("small", {}, `${Number(key.slice(5, 7))}/${Number(key.slice(8, 10))}`)),
        h("div", { class: "mini-day-items" }, items.length ? items.map(t => miniRow(t, false, key !== "overdue")) : h("p", { class: "hint" }, "沒有到期的事"))));
    }
    if (groups.later.length) list.append(h("button", { class: "mini-more", onclick: () => updateMiniPref({ layout: "list" }) }, `範圍外 ${groups.later.length} 件　看全部`));
    list.append(h("button", { class: "mini-more", "aria-expanded": String(miniUndated), onclick: () => { miniUndated = !miniUndated; renderMini(); } },
      `沒有日期 ${groups.undated.length} 件　${miniUndated ? "收起" : "展開"}`));
    if (miniUndated) list.append(...groups.undated.map(t => miniRow(t)));
  }
  if (!open.length && miniPrefs.layout !== "timeline") list.append(h("p", { class: "empty" }, "這個範圍沒有待辦"));
}

// 設定面板共用同一組控制項；頁籤只切換當前的一頁。
function settingsTabs(labels, selected, change, name) {
  const tabs = h("div", { class: "settings-tabs", role: "tablist", "aria-label": name });
  for (const [key, label] of Object.entries(labels)) tabs.append(h("button", {
    role: "tab", id: `${name}-${key}`, "aria-controls": `${name}-body`, "aria-selected": String(selected === key), tabindex: selected === key ? 0 : -1,
    onclick: () => { change(key); document.getElementById(`${name}-${key}`)?.focus(); },
    onkeydown: e => {
      const keys = Object.keys(labels);
      const index = keys.indexOf(key);
      const target = e.key === "ArrowRight" ? (index + 1) % keys.length : e.key === "ArrowLeft" ? (index + keys.length - 1) % keys.length : e.key === "Home" ? 0 : e.key === "End" ? keys.length - 1 : null;
      if (target !== null) { e.preventDefault(); change(keys[target]); document.getElementById(`${name}-${keys[target]}`)?.focus(); }
    }
  }, label));
  return tabs;
}
function miniSettingsControls() {
  const section = miniSettingsTab;
  const content = h("div", { class: "settings-content", id: "mini-settings-body", role: "tabpanel", "aria-labelledby": `mini-settings-${section}` });
  const select = (label, key, choices, numeric = false) => h("label", {}, label,
    h("select", { "aria-label": label, onchange: e => {
      updateMiniPref({ [key]: numeric ? Number(e.target.value) : e.target.value, ...(key === "scope" ? { scopeValue: "" } : {}) });
      if (key === "scope") renderSettings();
    } },
      Object.entries(choices).map(([value, text]) => h("option", { value, selected: String(miniPrefs[key]) === value }, text))));
  if (section === "layout") content.append(select("排法", "layout", MINI_LAYOUTS), select("時間軸天數", "timelineDays", { 7: "7 天", 14: "14 天", 30: "30 天" }, true));
  if (section === "badges") {
    for (const [key, label] of Object.entries({ due: "期限", assignee: "負責人", project: "專案", remind: "提醒時間", subtasks: "子任務進度", priority: "優先度色點" })) {
      content.append(h("label", { class: "settings-check" }, checkbox({ checked: miniPrefs.badges[key], title: label, onchange: e => updateMiniPref({ badges: { [key]: e.target.checked } }) }), label));
    }
  }
  if (section === "scope") {
    content.append(select("範圍", "scope", { open: "全部未完成", today: "今天＋進行中", project: "專案", assignee: "負責人" }));
    if (["project", "assignee"].includes(miniPrefs.scope)) {
      const options = [...new Set(S.todos.map(t => t[miniPrefs.scope]).filter(Boolean))].sort();
      if (miniPrefs.scopeValue && !options.includes(miniPrefs.scopeValue)) options.push(miniPrefs.scopeValue);
      content.append(select(miniPrefs.scope === "project" ? "專案" : "負責人", "scopeValue", { "": "請選擇", ...Object.fromEntries(options.map(v => [v, v])) }));
    }
  }
  if (section === "appearance") content.append(select("密度", "density", { compact: "精簡", cozy: "寬鬆" }),
    select("字級", "fontSize", { small: "小（14px）", normal: "中（16px）", large: "大（18px）" }),
    select("新增框", "addBox", { button: "標題列按鈕", bottom: "底部常駐" }));
  return [settingsTabs({ layout: "排法", badges: "顯示", scope: "範圍", appearance: "外觀" }, section, key => { miniSettingsTab = key; renderSettings(); }, "mini-settings"), content];
}
function renderSettings() {
  const body = $("#settingsBody");
  const active = body.contains(document.activeElement) ? document.activeElement : null;
  const activeId = active?.id;
  const activeLabel = active?.getAttribute("aria-label");
  body.replaceChildren();
  if (!MINI) body.append(settingsTabs({ general: "一般", mini: "小視窗" }, settingsTab, key => { settingsTab = key; renderSettings(); }, "settings"));
  const panel = h("div", MINI ? {} : { id: "settings-body", role: "tabpanel", "aria-labelledby": `settings-${settingsTab}` });
  if (MINI || settingsTab === "mini") panel.append(...miniSettingsControls());
  else panel.append(h("div", { class: "settings-content" }, h("label", {}, "主題", h("select", { "aria-label": "主題", onchange: e => {
    themeChoice = e.target.value; savePref("theme", themeChoice); syncTheme();
  } }, Object.entries(THEMES).map(([key, [label]]) => h("option", { value: key, selected: document.documentElement.dataset.theme === key }, label))))));
  body.append(panel);
  if (activeId) document.getElementById(activeId)?.focus();
  else if (activeLabel) [...body.querySelectorAll("[aria-label]")].find(el => el.getAttribute("aria-label") === activeLabel)?.focus();
}
function bindSettings() {
  const panel = $("#settingsPanel");
  const close = () => { panel.classList.add("hidden"); settingsOpener?.focus(); };
  const open = e => { settingsOpener = e.currentTarget; panel.classList.remove("hidden"); renderSettings(); $("#settingsClose").focus(); };
  $("#settingsBtn").onclick = open;
  $("#miniSettings").onclick = open;
  $("#settingsClose").onclick = close;
  panel.onclick = e => { if (e.target === panel) close(); };
  panel.onkeydown = e => {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    if (e.key === "Tab") {
      const controls = [...panel.querySelectorAll('button:not([tabindex="-1"]), select, input')];
      const first = controls[0], last = controls.at(-1);
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  };
  if (REMOTE) $("#settingsBtn").classList.add("hidden");
}
