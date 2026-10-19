from datetime import datetime

import pytest

from agent_todo.quickadd import parse


NOW = datetime(2026, 10, 19, 14, 0)  # 週一


@pytest.mark.parametrize("text,fields", [
    ("今天 工作", {"due": "2026-10-19"}),
    ("明天 工作", {"due": "2026-10-20"}),
    ("後天 工作", {"due": "2026-10-21"}),
    ("大後天 工作", {"due": "2026-10-22"}),
    ("週一 工作", {"due": "2026-10-26"}),
    ("星期三 工作", {"due": "2026-10-21"}),
    ("禮拜日 工作", {"due": "2026-10-25"}),
    ("下週一 工作", {"due": "2026-10-26"}),
    ("下週日 工作", {"due": "2026-11-01"}),
    ("10/25 工作", {"due": "2026-10-25"}),
    ("1/5 工作", {"due": "2027-01-05"}),
    ("2026-10-25 工作", {"due": "2026-10-25"}),
    ("today 工作", {"due": "2026-10-19"}),
    ("tomorrow 工作", {"due": "2026-10-20"}),
    ("mon 工作", {"due": "2026-10-26"}),
    ("SUN 工作", {"due": "2026-10-25"}),
    ("15:00 工作", {"due": "2026-10-19", "remindAt": "2026-10-19T15:00"}),
    ("早上9點 工作", {"due": "2026-10-20", "remindAt": "2026-10-20T09:00"}),
    ("下午3點 工作", {"due": "2026-10-19", "remindAt": "2026-10-19T15:00"}),
    ("晚上8點半 工作", {"due": "2026-10-19", "remindAt": "2026-10-19T20:30"}),
    ("3pm 工作", {"due": "2026-10-19", "remindAt": "2026-10-19T15:00"}),
    ("3:30pm 工作", {"due": "2026-10-19", "remindAt": "2026-10-19T15:30"}),
    ("明天 早上9點 工作", {"due": "2026-10-20", "remindAt": "2026-10-20T09:00"}),
    ("今天 早上9點 工作", {"due": "2026-10-19", "remindAt": "2026-10-19T09:00"}),
    ("每天 工作", {"repeat": "daily", "due": "2026-10-19"}),
    ("每個平日 工作", {"repeat": "weekdays", "due": "2026-10-19"}),
    ("平日 工作", {"repeat": "weekdays", "due": "2026-10-19"}),
    ("每週 工作", {"repeat": "weekly", "due": "2026-10-19"}),
    ("每週一 工作", {"repeat": "weekly", "due": "2026-10-26"}),
    ("每月 工作", {"repeat": "monthly", "due": "2026-10-19"}),
    ("每年 工作", {"repeat": "yearly", "due": "2026-10-19"}),
    ("every day 工作", {"repeat": "daily", "due": "2026-10-19"}),
    ("weekly 工作", {"repeat": "weekly", "due": "2026-10-19"}),
    ("every month 工作", {"repeat": "monthly", "due": "2026-10-19"}),
    ("yearly 工作", {"repeat": "yearly", "due": "2026-10-19"}),
    ("!高 工作", {"priority": "high"}),
    ("!! 工作", {"priority": "high"}),
    ("!1 工作", {"priority": "high"}),
    ("!低 工作", {"priority": "low"}),
    ("!3 工作", {"priority": "low"}),
    ("工作 #甲 #乙 +專案 @codex", {"tags": ["甲", "乙"], "project": "專案", "assignee": "codex"}),
])
def test_parse(text, fields):
    assert parse(text, NOW) == {"title": "工作", **fields}


@pytest.mark.parametrize("text", ["修登入頁 500 錯誤", "修正 v3 API", "明年處理", "25:99 工作", "2026-02-30 工作", "13pm 工作"])
def test_preserve_unknown(text):
    assert parse(text, NOW) == {"title": text}


def test_combined():
    assert parse("明天 下午3點 工作 !! #測試 +todo @codex", NOW) == {
        "title": "工作", "due": "2026-10-20", "remindAt": "2026-10-20T15:00",
        "priority": "high", "tags": ["測試"], "project": "todo", "assignee": "codex"}


def test_metadata_words_are_not_dates():
    assert parse("工作 #明天 +weekly @mon", NOW) == {
        "title": "工作", "tags": ["明天"], "project": "weekly", "assignee": "mon"}


@pytest.mark.parametrize("text", ["明天15:00工作", "10/20下午3點工作", "2026-10-20下午3點工作"])
def test_dates_and_times_next_to_chinese(text):
    assert parse(text, NOW) == {"title": "工作", "due": "2026-10-20", "remindAt": "2026-10-20T15:00"}
