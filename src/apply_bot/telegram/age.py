from __future__ import annotations

import re
from datetime import date, datetime, timedelta

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MD = re.compile(r"\b([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?\b", re.I)
_DM = re.compile(r"\b(\d{1,2})\s+([a-z]{3})[a-z]*\.?(?:,?\s+(\d{4}))?\b", re.I)


def label_to_date(label: str | None, now: datetime) -> date | None:
    """Turn a Telegram date header ('Today', 'Yesterday', 'October 15', '15 Oct 2026') into a date."""
    if not label:
        return None
    text = label.strip().lower()
    if text.startswith("today"):
        return now.date()
    if text.startswith("yesterday"):
        return now.date() - timedelta(days=1)
    for rx, mi, di in ((_MD, 1, 2), (_DM, 2, 1)):
        m = rx.search(text)
        if not m:
            continue
        month = MONTHS.get(m.group(mi)[:3].lower())
        if not month:
            continue
        year = int(m.group(3)) if m.group(3) else now.year
        try:
            d = date(year, month, int(m.group(di)))
        except ValueError:
            return None
        if not m.group(3) and d > now.date():
            d = date(year - 1, month, d.day)
        return d
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, name in enumerate(weekdays):
        if text.startswith(name):
            back = (now.weekday() - i) % 7 or 7
            return now.date() - timedelta(days=back)
    return None


def post_age_hours(posted_at: float | None, date_label: str | None, now: datetime | None = None) -> float | None:
    """Hours since the post. Exact when Telegram gave a timestamp; otherwise measured from the end of its day
    (so a post is only called old when the whole day is outside the window). None if unknown."""
    now = now or datetime.now()
    if posted_at:
        return max(0.0, (now - datetime.fromtimestamp(posted_at)).total_seconds() / 3600)
    d = label_to_date(date_label, now)
    if d is None:
        return None
    end_of_day = datetime.combine(d, datetime.max.time())
    return max(0.0, (now - end_of_day).total_seconds() / 3600)


def is_recent(posted_at: float | None, date_label: str | None, max_hours: float | None,
              now: datetime | None = None, keep_undated: bool = True) -> tuple[bool, float | None]:
    if not max_hours or max_hours <= 0:
        return True, None
    age = post_age_hours(posted_at, date_label, now)
    if age is None:
        return keep_undated, None
    return age <= max_hours, age
