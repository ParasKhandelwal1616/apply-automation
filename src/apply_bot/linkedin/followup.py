"""LinkedIn reply follow-up: collect replies, classify, draft, and (optionally) send.

Usage via CLI:
  run.ps1 linkedin-followup                 # collect + classify + draft (dry run)
  run.ps1 linkedin-followup --since 2026-11-08
  run.ps1 linkedin-followup --send          # send drafts marked "approved": true

Job matches for JD/role requests come from data/followup_jobs.json
({"company lower": [{"title","url","job_id","location"}]}) - only verified,
live, company-posted roles that fit the rules should be added there.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from apply_bot.config import Settings
from apply_bot.linkedin.messenger import (
    _click_send,
    _fill_message_box,
    attach_resume_to_dm,
    recipient_name_matches,
    resolve_resume_path,
    should_stop,
)

SELF_TOKENS = {"sumanth", "ponugupati"}
PORTFOLIO = "https://sumanth3036.github.io/my-portfolio/"
FOLLOWUP_DAILY_KEY_SUFFIX = "_followup"

_EXTRACT_JS = r"""
() => {
  const out = []; let dt = null, sender = null, tm = null;
  document.querySelectorAll('li.msg-s-message-list__event').forEach(li => {
    const th = li.querySelector('time.msg-s-message-list__time-heading');
    if (th) dt = th.innerText.trim();
    const h = li.querySelector('.msg-s-event-listitem--group-a11y-heading');
    if (h) {
      const t = h.innerText.trim();
      const m = t.match(/^(.*?) sent the following .*? at (.+)$/i);
      if (m) { sender = m[1].trim(); tm = m[2].trim(); } else { sender = t; }
    }
    const ev = li.querySelector('.msg-s-event-listitem');
    const other = ev ? ev.classList.contains('msg-s-event-listitem--other') : null;
    const body = li.querySelector('.msg-s-event-listitem__body');
    const att = li.querySelector('.msg-s-event-listitem__attachment-item, .msg-s-event-listitem__attachment, [class*="attachment-item"], a[href*="/dms/"]');
    const links = Array.from(li.querySelectorAll('.msg-s-event-listitem__body a')).map(a => a.href);
    out.push({date: dt, sender, time: tm, other, text: body ? body.innerText.trim() : '',
              attachment: !!att, links});
  });
  return out;
}
"""

_HEADER_SELS = [
    ".msg-entity-lockup__entity-title",
    "h2.msg-entity-lockup__entity-title",
    ".msg-thread__link-to-profile",
    ".msg-title-bar h2",
    "#thread-detail-jump-target",
]


def is_self(name: str) -> bool:
    toks = set((name or "").lower().split())
    return bool(toks) and toks <= SELF_TOKENS


def parse_heading_date(label: str | None, today: date | None = None) -> str:
    """'Today' / 'Yesterday' / 'Monday' / 'Nov 8' / 'Oct 30, 2025' -> ISO date."""
    today = today or date.today()
    if not label:
        return ""
    s = label.strip().lower()
    if s == "today":
        return today.isoformat()
    if s == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if s in days:
        delta = (today.weekday() - days.index(s)) % 7 or 7
        return (today - timedelta(days=delta)).isoformat()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d", "%B %d"):
        try:
            d = datetime.strptime(label.strip().title(), fmt).date()
            if "%Y" not in fmt:
                d = d.replace(year=today.year)
                if d > today:
                    d = d.replace(year=today.year - 1)
            return d.isoformat()
        except ValueError:
            continue
    return ""


# ---------------- classification ----------------
_JD = re.compile(
    r"\b(jd|j\.d|job ?id|jobid|job id's|job ids|req(uisition)? ?id|job link|job links|link of the job|"
    r"job description|which role|what role|which position|what position|which roles|role you|"
    r"roles you|position you|opening you|send (me )?the link|share (me )?the link|share (the )?(job|role)|"
    r"send (the )?(job|role)|apply link|let me know the role|specific role|particular role|"
    r"which (job|opening)|any (specific|particular) (role|job|opening)|interested in)\b",
    re.I,
)
_RESUME = re.compile(r"\b(resume|cv|résumé)\b", re.I)
_REFERRED = re.compile(r"\b(referred|i have referred|i've referred|submitted (your|the) referral|referral (done|submitted)|done with the referral)\b", re.I)
_APPLY_FIRST = re.compile(r"\b(apply (first|on|through|via|directly)|please apply|you can apply|kindly apply)\b", re.I)
_NEG = re.compile(r"\b(not hiring|no openings?|hiring freeze|can'?t refer|cannot refer|unable to refer|not possible|no vacanc|not able to refer)\b", re.I)


def classify(text: str) -> str:
    t = text or ""
    if _REFERRED.search(t):
        return "referred_applied"
    if _NEG.search(t):
        return "not_hiring"
    if _JD.search(t):
        return "asks_for_jd"
    if _APPLY_FIRST.search(t):
        return "ask_to_apply_first"
    if _RESUME.search(t):
        return "asks_for_resume"
    return "other"


def ask_key(thread_url: str, their_text: str, their_date: str) -> str:
    raw = f"{thread_url}|{their_date}|{(their_text or '').strip()[:300]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def analyze_thread(t: dict[str, Any]) -> dict[str, Any]:
    msgs = t["messages"]
    for m in msgs:
        m["is_me"] = is_self(m.get("sender") or "")
        m["iso_date"] = parse_heading_date(m.get("date"))
    their_idx = [i for i, m in enumerate(msgs) if not m["is_me"] and (m["text"] or m["attachment"])]
    t["has_reply"] = bool(their_idx)
    if not their_idx:
        return t
    last = their_idx[-1]
    # Find the latest "ask" (JD/resume/role) message from them and whether we answered it.
    ask_i = None
    for i in reversed(their_idx):
        c = classify(msgs[i]["text"])
        if c in {"asks_for_jd", "asks_for_resume"}:
            ask_i = i
            break
    # Combine their consecutive trailing messages for classification context
    tail_start = last
    while tail_start - 1 >= 0 and not msgs[tail_start - 1]["is_me"]:
        tail_start -= 1
    their_tail = "\n".join(m["text"] for m in msgs[tail_start:last + 1] if m["text"])
    t["their_last_text"] = their_tail
    t["their_last_date"] = msgs[last]["iso_date"]
    t["we_replied_after_last"] = any(m["is_me"] for m in msgs[last + 1:])
    t["category"] = classify(their_tail)
    t["ask_unanswered"] = False
    if ask_i is not None:
        after = msgs[ask_i + 1:]
        ours = [m for m in after if m["is_me"]]
        delivered = any(m["attachment"] or any("http" in (l or "") for l in m.get("links", []))
                        or "http" in (m["text"] or "") for m in ours)
        t["ask_text"] = msgs[ask_i]["text"]
        t["ask_date"] = msgs[ask_i]["iso_date"]
        t["ask_category"] = classify(msgs[ask_i]["text"])
        # Unanswered when nothing we sent after their ask carried a link/attachment.
        t["ask_unanswered"] = not delivered
        if t["ask_category"] == "asks_for_resume" and any(m["attachment"] for m in msgs if m["is_me"]):
            # Resume was already attached somewhere in the thread before/after; still offer link.
            t["resume_already_sent"] = True
    return t


# ---------------- collection ----------------
def _scroll_list(page: Page, max_threads: int) -> None:
    for _ in range(40):
        n = page.locator("li.msg-conversation-listitem").count()
        if n >= max_threads:
            break
        page.evaluate(
            "() => { const el = document.querySelector('.msg-conversations-container__conversations-list')"
            " || document.querySelector('.msg-conversations-container--inbox-shortcuts');"
            " if (el) el.scrollTop = el.scrollHeight; }"
        )
        page.wait_for_timeout(1800)
        if page.locator("li.msg-conversation-listitem").count() == n:
            page.wait_for_timeout(1500)
            if page.locator("li.msg-conversation-listitem").count() == n:
                break


def thread_header_name(page: Page) -> str:
    for sel in _HEADER_SELS:
        loc = page.locator(sel)
        for i in range(min(loc.count(), 4)):
            try:
                txt = " ".join(loc.nth(i).inner_text(timeout=1500).split())
                if txt:
                    return txt
            except Exception:
                continue
    return ""


def collect_threads(page: Page, max_threads: int = 120) -> list[dict[str, Any]]:
    page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    _scroll_list(page, max_threads)
    items = page.locator("li.msg-conversation-listitem")
    total = min(items.count(), max_threads)
    print(f"Conversation list loaded: {items.count()} (reading {total})")
    threads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i in range(total):
        try:
            it = page.locator("li.msg-conversation-listitem").nth(i)
            name_el = it.locator(".msg-conversation-listitem__participant-names").first
            name = " ".join(name_el.inner_text(timeout=2000).split()) if name_el.count() else ""
            ts_el = it.locator(".msg-conversation-listitem__time-stamp").first
            list_ts = ts_el.inner_text(timeout=1000).strip() if ts_el.count() else ""
            if "," in name or " and " in name.lower():
                print(f"  [{i}] group thread skipped: {name}")
                continue
            link = it.locator(".msg-conversation-listitem__link, a").first
            it.scroll_into_view_if_needed(timeout=3000)
            link.click(timeout=5000)
            page.wait_for_timeout(2500)
            url = page.url.split("?")[0]
            if url in seen:
                continue
            seen.add(url)
            msgs = page.evaluate(_EXTRACT_JS)
            other_hrefs = page.evaluate(
                "() => Array.from(document.querySelectorAll('.msg-s-event-listitem--other a.msg-s-event-listitem__link')).map(a=>a.href)"
            )
            t = {
                "name": name,
                "list_time": list_ts,
                "thread_url": url,
                "header_name": thread_header_name(page),
                "profile_urn_url": other_hrefs[0] if other_hrefs else "",
                "messages": msgs,
            }
            threads.append(analyze_thread(t))
            print(f"  [{i}] {name} ({list_ts}) msgs={len(msgs)} reply={t.get('has_reply')}")
        except Exception as exc:
            print(f"  [{i}] error reading thread: {exc}")
            continue
    return threads


def load_outreach(settings: Settings) -> dict[str, dict[str, str]]:
    p = settings.project_root / "data" / "linkedin_outreach.csv"
    out: dict[str, dict[str, str]] = {}
    if not p.exists():
        return out
    with open(p, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("sent_at") and row.get("name"):
                out[row["name"].strip().lower()] = row
    return out


def load_contact_companies(settings: Settings) -> dict[str, str]:
    """name(lower) -> company, from linkedin_contacts.csv company or headline ('X at Co' / 'X @ Co')."""
    p = settings.project_root / "data" / "linkedin_contacts.csv"
    out: dict[str, str] = {}
    if not p.exists():
        return out
    with open(p, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip().lower()
            co = (row.get("company") or "").strip()
            if not co:
                m = re.search(r"(?:@|\bat)\s+([A-Z][\w&.\- ]{1,40}?)(?:\s*[|,(]|$)", row.get("headline") or "")
                co = m.group(1).strip() if m else ""
            if name and co:
                out[name] = co
    return out


def load_jobs(settings: Settings) -> dict[str, list[dict[str, str]]]:
    p = settings.project_root / "data" / "followup_jobs.json"
    if not p.exists():
        return {}
    return {k.lower(): v for k, v in json.loads(p.read_text(encoding="utf-8")).items()}


def load_overrides(settings: Settings) -> dict[str, str]:
    """Optional data/followup_overrides.json: {"name": "asks_for_jd" | "skip" | ...}."""
    p = settings.project_root / "data" / "followup_overrides.json"
    if not p.exists():
        return {}
    return {k.lower(): v for k, v in json.loads(p.read_text(encoding="utf-8")).items()}


# ---------------- drafting ----------------
def _first(name: str) -> str:
    n = (name or "there").split()
    f = n[0] if n else "there"
    return f.title() if f.isupper() else f


def _email() -> str:
    try:
        from apply_bot.config import load_profile
        return (load_profile().email or "").strip()
    except Exception:
        return ""


def build_draft(category: str, name: str, company: str, jobs: list[dict[str, str]]) -> str:
    first = _first(name)
    co = company or "your team"
    if category in {"asks_for_jd", "asks_for_resume", "ask_to_apply_first"} and jobs:
        noun = "role" if len(jobs[:2]) == 1 else "roles"
        lines = [f"Hi {first}, following up as promised! Here's the {co} {noun} I'd love a referral for:"]
        for j in jobs[:2]:
            jid = f" (Job ID: {j['job_id']})" if j.get("job_id") else ""
            loc = f", {j['location']}" if j.get("location") else ""
            lines.append(f"- {j['title']}{loc}{jid}: {j['url']}")
        lines.append(
            "I'm a 2026 grad working on backend and AI/ML (Python, FastAPI, RAG, AI agents), "
            "ex-Software & ML Engineer Intern at LogiXair, with 3 IEEE papers. Resume attached; "
            f"portfolio: {PORTFOLIO}."
        )
        em = _email()
        if em:
            lines.append(f"My email for the referral: {em}. Thank you so much!")
        if category == "ask_to_apply_first":
            lines.insert(1, "I'll apply on the careers page right away and share the confirmation.")
        return "\n".join(lines)
    if category == "asks_for_resume":
        return (
            f"Hi {first}, thank you! I've attached my resume here. I'm a 2026 grad focused on backend "
            "and AI/ML (Python, FastAPI, RAG, AI agents), ex-Software & ML Engineer Intern at LogiXair, "
            f"with 3 IEEE papers. Portfolio: {PORTFOLIO}. Happy to share anything else you need!"
        )
    if category == "referred_applied":
        return f"Thank you so much, {first}! Really appreciate the referral. I'll keep you posted on how it goes."
    if category == "not_hiring":
        return f"Totally understand, {first}, thanks for letting me know! If anything opens up at {co}, I'd be grateful if you keep me in mind."
    return ""


def build_drafts(settings: Settings, threads: list[dict[str, Any]], since: str | None) -> list[dict[str, Any]]:
    outreach = load_outreach(settings)
    contact_cos = load_contact_companies(settings)
    jobs_map = load_jobs(settings)
    sent_keys = load_sent_keys(settings)
    drafts: list[dict[str, Any]] = []
    for t in threads:
        if not t.get("has_reply"):
            continue
        name = t["name"]
        row = outreach.get(name.lower())
        ours = " ".join(m["text"] for m in t["messages"] if m.get("is_me")).lower()
        referral_thread = bool(row) or "refer" in ours
        if not referral_thread:
            continue
        company = ((row or {}).get("company") or "").strip() or contact_cos.get(name.lower(), "")
        use_ask = bool(t.get("ask_unanswered")) and t.get("category") not in {"referred_applied", "not_hiring"}
        if use_ask:
            category = t.get("ask_category")
            their_text, their_date = t.get("ask_text", ""), t.get("ask_date", "")
        else:
            category = t.get("category", "other")
            their_text, their_date = t.get("their_last_text", ""), t.get("their_last_date", "")
        ov = load_overrides(settings).get(name.lower())
        if ov:
            category = ov
        if since and their_date and their_date < since:
            continue
        status = "draft"
        skip_reason = ""
        if t.get("we_replied_after_last") and not use_ask and not (ov and ov != "skip"):
            status, skip_reason = "skip", "we already replied after their last message"
        jobs = jobs_map.get(company.lower(), []) if company else []
        text = build_draft(category, name, company, jobs)
        if category == "asks_for_jd" and not jobs:
            status, skip_reason = "needs_jobs", f"no verified job for company {company or '?'} in followup_jobs.json"
        if category == "other":
            status, skip_reason = "flag_user", "unclear reply"
        if category == "skip":
            status, skip_reason, text = "skip", "manual override: skip", ""
        if not text and status == "draft":
            status, skip_reason = "skip", "no reply needed"
        key = ask_key(t["thread_url"], their_text, their_date)
        if key in sent_keys:
            status, skip_reason = "skip", "follow-up already sent for this ask"
        drafts.append({
            "name": name,
            "company": company,
            "thread_url": t["thread_url"],
            "header_name": t.get("header_name", ""),
            "their_text": their_text,
            "their_date": their_date,
            "category": category,
            "we_replied_after_last": t.get("we_replied_after_last"),
            "ask_unanswered": t.get("ask_unanswered"),
            "jobs": jobs[:2],
            "attach_resume": category in {"asks_for_jd", "asks_for_resume", "ask_to_apply_first"},
            "draft": text,
            "status": status,
            "skip_reason": skip_reason,
            "approved": False,
            "ask_key": key,
        })
    return drafts


# ---------------- sending ----------------
def _fill_multiline(page: Page, message: str, scope=None) -> bool:
    """Type a multi-line message using Shift+Enter (plain Enter may send early)."""
    root = scope if scope is not None else page
    box = root.locator(
        "div.msg-form__contenteditable[contenteditable='true'], div[role='textbox'][contenteditable='true']"
    ).first
    if box.count() == 0:
        return False
    try:
        box.click(timeout=3000)
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        lines = message.split("\n")
        for i, line in enumerate(lines):
            if line:
                page.keyboard.type(line, delay=12)
            if i < len(lines) - 1:
                page.keyboard.press("Shift+Enter")
        page.wait_for_timeout(500)
        typed = box.inner_text(timeout=2000)
        return lines[0][:30] in typed and lines[-1][-20:] in typed
    except Exception as exc:
        print(f"  fill failed: {exc}")
        return False



def _sent_log_path(settings: Settings) -> Path:
    return settings.project_root / "data" / "linkedin_followup_sent.csv"


def load_sent_keys(settings: Settings) -> set[str]:
    p = _sent_log_path(settings)
    if not p.exists():
        return set()
    with open(p, "r", encoding="utf-8") as f:
        return {r["ask_key"] for r in csv.DictReader(f) if r.get("status") == "sent"}


def _log_sent(settings: Settings, d: dict[str, Any], status: str, note: str = "") -> None:
    p = _sent_log_path(settings)
    new = not p.exists()
    with open(p, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sent_at", "name", "company", "thread_url", "ask_key", "category", "status", "attach", "note", "text"])
        if new:
            w.writeheader()
        w.writerow({"sent_at": datetime.now().isoformat(), "name": d["name"], "company": d.get("company", ""),
                    "thread_url": d["thread_url"], "ask_key": d["ask_key"], "category": d["category"],
                    "status": status, "attach": d.get("attach_result", ""), "note": note, "text": d["draft"]})


def _count_today(settings: Settings) -> int:
    p = _sent_log_path(settings)
    if not p.exists():
        return 0
    today = date.today().isoformat()
    with open(p, "r", encoding="utf-8") as f:
        return sum(1 for r in csv.DictReader(f) if r.get("status") == "sent" and r.get("sent_at", "").startswith(today))


def send_followups(page: Page, settings: Settings, drafts: list[dict[str, Any]], daily_limit: int = 20) -> list[dict[str, Any]]:
    sent_keys = load_sent_keys(settings)
    try:
        resume = resolve_resume_path(settings)
    except FileNotFoundError:
        resume = None
    results = []
    for d in drafts:
        if not d.get("approved") or not d.get("draft"):
            continue
        if d["ask_key"] in sent_keys:
            results.append({**d, "result": "dedupe-skip"})
            continue
        if _count_today(settings) >= daily_limit:
            print(f"Daily follow-up limit {daily_limit} reached; stopping.")
            break
        page.goto(d["thread_url"], wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        if should_stop(page):
            print("LinkedIn warning/captcha detected; stopping.")
            results.append({**d, "result": "stopped-warning"})
            break
        header = thread_header_name(page)
        for _ in range(3):
            if header and page.locator("li.msg-s-message-list__event").count() > 0:
                break
            page.wait_for_timeout(4000)
            header = thread_header_name(page)
        others = page.evaluate(
            "() => Array.from(document.querySelectorAll('.msg-s-event-listitem--group-a11y-heading')).map(e=>e.innerText.trim())"
        )
        other_names = {re.sub(r"\s+sent the following.*$", "", o, flags=re.I).strip() for o in others}
        other_names = {n for n in other_names if n and not is_self(n)}
        ok_header = recipient_name_matches(header, d["name"])
        ok_others = len(other_names) == 1 and recipient_name_matches(next(iter(other_names)), d["name"])
        if not (ok_header or ok_others) or len(other_names) > 1:
            print(f"  Recipient not verified for {d['name']!r} (header={header!r}, others={other_names}); skipping.")
            _log_sent(settings, d, "skip", "recipient not verified")
            results.append({**d, "result": "skip-unverified"})
            continue
        form = page.locator("form.msg-form, .msg-form").first
        scope = form if form.count() else None
        before = page.locator("li.msg-s-message-list__event").count()
        d["attach_result"] = ""
        if d.get("attach_resume") and resume and resume.exists():
            d["attach_result"] = "pdf" if attach_resume_to_dm(page, resume, scope) else "failed"
        if d.get("attach_resume") and d["attach_result"] != "pdf":
            from apply_bot.linkedin.messenger import resolve_drive_link
            d["draft"] = d["draft"].replace("Resume attached;", f"Resume: {resolve_drive_link()} ;").replace(
                "I've attached my resume here.", f"Here's my resume: {resolve_drive_link()}")
            d["attach_result"] = "drive_link"
        if not _fill_multiline(page, d["draft"], scope):
            _log_sent(settings, d, "error", "message box not found")
            results.append({**d, "result": "error-no-box"})
            continue
        if not _click_send(page, scope):
            _log_sent(settings, d, "error", "send click failed")
            results.append({**d, "result": "error-send"})
            continue
        page.wait_for_timeout(3000)
        after = page.locator("li.msg-s-message-list__event").count()
        body_texts = page.evaluate(
            "() => Array.from(document.querySelectorAll('.msg-s-event-listitem__body')).slice(-3).map(e=>e.innerText)"
        )
        snippet = d["draft"].splitlines()[0][:40]
        verified = after > before or any(snippet in (b or "") for b in body_texts)
        _log_sent(settings, d, "sent", "verified" if verified else "send clicked, not confirmed")
        sent_keys.add(d["ask_key"])
        results.append({**d, "result": "sent" if verified else "sent-unconfirmed"})
        print(f"  Sent to {d['name']} (verified={verified}, attach={d['attach_result']})")
        gap = random.uniform(55, 70)
        page.wait_for_timeout(int(gap * 1000))
    return results
