"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const vm = require("node:vm");
const context = vm.createContext({});
vm.runInContext(readFileSync(join(__dirname, "../agent_todo/ui/mini.js"), "utf8"), context);
const next = vm.runInContext("miniNext", context);
const relative = vm.runInContext("miniRelativeDate", context);
const hint = vm.runInContext("miniDueHint", context);
const focus = vm.runInContext("miniFocusGroups", context);
const timeline = vm.runInContext("miniTimelineGroups", context);
const todo = (id, fields = {}) => ({ id, status: "todo", priority: "normal", due: "", ...fields });

test("下一件事依期限、優先度、進行中排序，排除已完成並保留原順序", () => {
  const items = [todo(1, { due: "2026-10-21", priority: "high", status: "doing" }),
    todo(2, { due: "2026-10-19" }), todo(3, { due: "2026-10-18", status: "done" })];
  assert.equal(next(items).id, 2);
  assert.deepEqual(items.map(t => t.id), [1, 2, 3]);
  assert.equal(next([todo(1, { due: "2026-10-20", status: "doing" }), todo(2, { due: "2026-10-20", priority: "high" })]).id, 2);
  assert.equal(next([todo(1, { due: "2026-10-20" }), todo(2, { due: "2026-10-20", status: "doing" })]).id, 2);
  assert.equal(next([todo(1, { priority: "high" }), todo(2, { status: "doing" })]).id, 2);
  assert.equal(next([todo(1, { status: "doing" }), todo(2, { status: "doing", priority: "high" })]).id, 2);
  assert.equal(next([]), undefined);
});

test("相對日期涵蓋今天、明天、七天內、下週、跨年及逾期", () => {
  const base = "2026-10-20";
  for (const [date, expected] of [[base, "今天"], ["2026-10-21", "明天"], ["2026-10-22", "週四"],
    ["2026-10-27", "下週二"], ["2026-11-04", "11/4"], ["2026-10-19", "10/19"]]) {
    assert.equal(relative(date, base), expected);
  }
  assert.equal(relative("2027-01-01", "2026-12-31"), "明天");
  assert.equal(hint("2026-10-18", base), "逾期 2 天");
  assert.equal(hint(base, base), "今天到期");
  assert.equal(hint("2026-10-21", base), "明天到期");
});

test("聚焦分組每件只出現一次，七天邊界與卡住優先歸入期限組", () => {
  const items = [todo(1, { due: "2026-10-19" }), todo(2, { due: "2026-10-20" }),
    todo(3, { due: "2026-10-21" }), todo(4, { due: "2026-10-27", status: "blocked" }),
    todo(5, { due: "2026-10-28", status: "blocked" }), todo(6), todo(7, { due: "2026-10-28" })];
  const groups = focus(items, "2026-10-20");
  for (const [key, ids] of Object.entries({ overdue: [1], today: [2], tomorrow: [3], week: [4], blocked: [5], other: [6, 7] })) {
    assert.deepEqual(Array.from(groups[key], t => t.id), ids);
  }
});

test("時間軸保留空的今天，區分逾期、天數範圍外與沒有日期", () => {
  const items = [todo(1, { due: "2026-10-19" }), todo(2, { due: "2026-10-26" }),
    todo(3, { due: "2026-10-27" }), todo(4)];
  const groups = timeline(items, "2026-10-20", 7);
  assert.equal(groups["2026-10-20"].length, 0);
  assert.equal(groups.overdue[0].id, 1);
  assert.equal(groups["2026-10-26"][0].id, 2);
  assert.equal(groups.later[0].id, 3);
  assert.equal(groups.undated[0].id, 4);
  assert.equal(timeline(items, "2026-10-20", 14)["2026-10-27"][0].id, 3);
});
