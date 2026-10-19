"""快速輸入：只拆出明確的日期、時間與欄位標記。"""
from __future__ import annotations

import re
from datetime import datetime, date, timedelta


_DAYS = {name: i for i, name in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
_CN_DAYS = "一二三四五六日天"


def parse(text: str, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    today = now.date()
    result = {}
    work = text

    def take(pattern, handler, flags=0):
        nonlocal work

        def replace(match):
            try:
                handler(match)
            except (ValueError, OverflowError):
                return match.group(0)
            return " "

        work = re.sub(pattern, replace, work, flags=flags)

    take(r"(?<!\S)#([^\s#]+)", lambda m: result.setdefault("tags", []).append(m[1]))
    take(r"(?<!\S)\+([^\s+]+)", lambda m: result.update(project=m[1]))
    take(r"(?<!\S)@([^\s@]+)", lambda m: result.update(assignee=m[1]))

    def weekday(token):
        if token.lower() in _DAYS:
            return _DAYS[token.lower()]
        return min(_CN_DAYS.index(token[-1]), 6)

    def nearest(day):
        return today + timedelta(days=(day - today.weekday()) % 7 or 7)

    def repeat(m):
        token = m[0].lower()
        if re.fullmatch(r"每(?:週|周|星期|禮拜)[一二三四五六日天]", token):
            result.update(repeat="weekly", due=nearest(weekday(token)).isoformat())
        else:
            rules = {"每天": "daily", "每日": "daily", "每個平日": "weekdays", "平日": "weekdays",
                     "每週": "weekly", "每周": "weekly", "每月": "monthly", "每年": "yearly",
                     "every day": "daily", "daily": "daily", "every weekday": "weekdays",
                     "every weekdays": "weekdays", "weekdays": "weekdays", "every week": "weekly",
                     "weekly": "weekly", "every month": "monthly", "monthly": "monthly",
                     "every year": "yearly", "yearly": "yearly"}
            result["repeat"] = rules[token]

    take(r"每(?:週|周|星期|禮拜)[一二三四五六日天]|每個平日|每天|每日|平日|每週|每周|每月|每年|\b(?:every weekdays?|every day|every week|every month|every year|weekdays|daily|weekly|monthly|yearly)\b", repeat, re.I)

    def explicit_date(m):
        token = m[0]
        if "-" in token:
            due = date.fromisoformat(token)
        else:
            month, day = map(int, token.split("/"))
            due = date(today.year, month, day)
            if due < today:  # 已經過了的月／日指的是明年
                due = date(today.year + 1, month, day)
        result["due"] = due.isoformat()

    take(r"(?<![A-Za-z0-9_/\-])\d{4}-\d{2}-\d{2}(?![\d-])|(?<![A-Za-z0-9_/])\d{1,2}/\d{1,2}(?![\d/])", explicit_date)

    def relative(m):
        offsets = {"今天": 0, "明天": 1, "後天": 2, "大後天": 3, "today": 0, "tomorrow": 1}
        result["due"] = (today + timedelta(days=offsets[m[0].lower()])).isoformat()

    take(r"大後天|後天|明天|今天|\b(?:today|tomorrow)\b", relative, re.I)

    def day_of_week(m):
        if m[0].startswith("下"):
            due = today + timedelta(days=7 - today.weekday() + weekday(m[0]))
        else:
            due = nearest(weekday(m[0]))
        result["due"] = due.isoformat()

    take(r"下(?:週|周|星期|禮拜)[一二三四五六日天]|(?:週|周|星期|禮拜)[一二三四五六日天]|\b(?:mon|tue|wed|thu|fri|sat|sun)\b", day_of_week, re.I)

    clock = None

    def time_value(m):
        nonlocal clock
        token = m[0].lower()
        cn = re.fullmatch(r"(凌晨|早上|上午|中午|下午|晚上)?(\d{1,2})點(?:(\d{1,2})分?|([半]))?", token)
        if cn:
            period, hour, minute, half = cn.groups()
            hour, minute = int(hour), 30 if half else int(minute or 0)
            if period in ("中午", "下午", "晚上") and hour < 12:
                hour += 12
            elif period in ("凌晨", "早上", "上午") and hour == 12:
                hour = 0
        else:
            en = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", token)
            hour, minute, period = int(en[1]), int(en[2] or 0), en[3]
            if period:
                if not 1 <= hour <= 12:
                    raise ValueError
                hour = hour % 12 + (12 if period == "pm" else 0)
        clock = datetime(today.year, today.month, today.day, hour, minute).time()

    take(r"(?<!\d)(?:凌晨|早上|上午|中午|下午|晚上)?\d{1,2}點(?:\d{1,2}分?|半)?(?!\d)|(?<![A-Za-z0-9_:])(?:\d{1,2}:\d{2}(?:\s*(?:am|pm))?|\d{1,2}\s*(?:am|pm))(?![A-Za-z0-9_:])", time_value, re.I)
    if clock is not None:
        due = date.fromisoformat(result["due"]) if "due" in result else today
        if "due" not in result and datetime.combine(due, clock) < now.replace(tzinfo=None):
            due += timedelta(days=1)
        result.update(due=due.isoformat(), remindAt=f"{due.isoformat()}T{clock:%H:%M}")
    if result.get("repeat") and "due" not in result:
        result["due"] = today.isoformat()

    def priority(m):
        result["priority"] = "low" if m[0] in ("!低", "!3") else "high"

    take(r"!高|!!|!1(?!\d)|!低|!3(?!\d)", priority)
    result["title"] = " ".join(work.split())
    return result
