from __future__ import annotations

import csv
import random
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page

from apply_bot.boards.base import BoardStop, blocked_reason, click_apply, confirmed, page_text, upload_resume
from apply_bot.boards.fit import board_fit, recheck_full_jd
from apply_bot.boards.limits import DailyCounter, next_gap_seconds, run_budget
from apply_bot.boards.note import wellfound_note
from apply_bot.boards.rules import jd_only, salary_display
from apply_bot.boards.search import (
    _cards_from_links,
    card_to_post,
    is_job_url,
    naukri_search_url,
    naukri_search_urls,
    naukri_searches,
    wellfound_search_urls,
    workatastartup_search_urls,
)
from apply_bot.config import Profile, Settings
from apply_bot.models import FilterResult, JobPost, ProcessStatus
from apply_bot.store import db
from apply_bot.telegram.browser import TelegramSession

SOURCES = {
    "naukri": (naukri_search_urls, "naukri.com/job-listings"),
    "wellfound": (wellfound_search_urls, "wellfound.com/jobs"),
    "workatastartup": (workatastartup_search_urls, "workatastartup.com/jobs"),
}

LOGIN_URLS = {
    "naukri": "https://www.naukri.com/nlogin/login",
    "wellfound": "https://wellfound.com/login",
    "workatastartup": "https://account.ycombinator.com/authenticate",
}

MANUAL_FIELDS = ["logged_at", "source", "company", "role", "salary", "reason", "url", "mode"]


def open_board_logins(session: TelegramSession) -> None:
    page = session.page
    assert page is not None
    for url in LOGIN_URLS.values():
        tab = session.context.new_page() if session.context else page
        tab.goto(url, wait_until="domcontentloaded", timeout=45000)
    print(
        "Sign in to Naukri, Wellfound, and Work at a Startup in the Chromium window. "
        "Press Enter here when you are done."
    )
    try:
        input()
    except EOFError:
        page.wait_for_timeout(180_000)


def manual_review_path(settings: Settings) -> Path:
    return settings.project_root / "data" / "manual_review.csv"


def log_manual_review(settings: Settings, source: str, post: JobPost, reason: str, mode: str) -> bool:
    """Append a job the bot will not auto-apply to (e.g. Naukri 'Apply on company site'). Dedupe by URL."""
    path = manual_review_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    if path.exists():
        with path.open(encoding="utf-8", newline="") as fh:
            seen = {row.get("url", "") for row in csv.DictReader(fh)}
    if (post.apply_url or "") in seen:
        return False
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANUAL_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow({
            "logged_at": datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "company": post.company or "",
            "role": post.role or "",
            "salary": salary_display(post.raw_text),
            "reason": reason,
            "url": post.apply_url or "",
            "mode": mode,
        })
    return True


def naukri_apply_kind(text: str, url: str = "") -> str:
    """Classify a Naukri job page: direct | company_site | already_applied | needs_login | captcha."""
    lowered = text.lower()
    if blocked_reason(text):
        return "captcha"
    if "nlogin" in url:
        return "needs_login"
    if "apply on company site" in lowered or "apply on company website" in lowered:
        return "company_site"
    if re.search(r"\balready applied\b|\bapplied\s*\n", lowered):
        return "already_applied"
    if "login to apply" in lowered or "register to apply" in lowered:
        return "needs_login"
    return "direct"


def _open_detail(tab: Page, url: str) -> str:
    tab.goto(url, wait_until="domcontentloaded", timeout=45000)
    tab.wait_for_timeout(2500)
    return page_text(tab)


def _apply_on_page(page: Page, post: JobPost, profile: Profile, submit: bool, source: str) -> ProcessStatus:
    """Assumes the job page is already open in `page`."""
    clicked = click_apply(page)
    text = page_text(page)
    if blocked_reason(text):
        raise BoardStop("captcha")
    lowered = text.lower()
    if "nlogin" in page.url or ("login" in page.url and "sign in" in lowered):
        raise BoardStop("needs_login")
    if source == "naukri" and re.search(r"answer (?:a few|the following|these) questions|chatbot|recruiter'?s? questions", lowered):
        raise BoardStop("naukri_questionnaire")
    upload_resume(page, profile.resume_path)
    if source == "wellfound":
        try:
            box = page.locator("textarea").first
            if box.is_visible(timeout=1500):
                box.fill(wellfound_note(profile, post))
        except Exception:
            pass
    if not submit:
        return ProcessStatus.FORM_PREPARED
    if source == "wellfound":
        for label in ("Send application", "Submit application", "Apply"):
            try:
                page.get_by_role("button", name=label, exact=False).first.click(timeout=3000)
                break
            except Exception:
                continue
    elif not clicked:
        click_apply(page)
    page.wait_for_timeout(2000)
    if confirmed(page_text(page)):
        return ProcessStatus.FORM_SUBMITTED
    return ProcessStatus.FORM_PREPARED


def _gather_cards(page: Page, source: str, settings: Settings, limit: int) -> list[dict[str, str]]:
    """Visit each search URL and take a few cards from each so every query/city gets a turn.
    Naukri: if the strict jobAge window returns nothing for a query/city, retry with the fallback window."""
    url_fn, host = SOURCES[source]
    per = max(1, settings.board_cards_per_search)
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    if source == "naukri":
        searches = [
            (q, c, naukri_search_url(settings, q, c, settings.naukri_job_age_days),
             naukri_search_url(settings, q, c, settings.naukri_job_age_fallback_days))
            for q, c in naukri_searches(settings)
        ]
    else:
        searches = [("", "", u, None) for u in url_fn(settings)]
    for query, city, url, alt in searches:  # strictly one search at a time
        if len(found) >= limit:
            break
        cards: list[dict[str, str]] = []
        age_used = ""
        for attempt, age in ((url, settings.naukri_job_age_days), (alt, settings.naukri_job_age_fallback_days)):
            if not attempt:
                continue
            page.goto(attempt, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            reason = blocked_reason(page_text(page))
            if reason:
                raise RuntimeError(reason)
            cards = [c for c in _cards_from_links(page, host, 40)
                     if c["href"] not in seen and is_job_url(source, c["href"])][: per * 3]
            age_used = f"{age}d"
            if cards:
                break
        if query:
            print(f"    search: '{query}' in {city} (jobAge {age_used}) -> {len(cards)} cards")
        for card in cards[:per]:
            seen.add(card["href"])
            card["query"], card["city"] = query, city
            found.append(card)
            if len(found) >= limit:
                break
    return found


def print_query_summary(report: list[dict[str, str]]) -> None:
    rows: dict[tuple[str, str], list[dict[str, str]]] = {}
    for r in report:
        if r.get("query"):
            rows.setdefault((r["query"], r["city"]), []).append(r)
    if not rows:
        return
    print("\n    Per-query summary (query | city | cards | real matches | would apply)")
    for (q, c), items in rows.items():
        yes = [i for i in items if i["would_apply"] == "yes"]
        names = "; ".join(f"{i['company']} - {i['role']}" for i in yes) or "-"
        print(f"    {q} | {c} | {len(items)} | {len(yes)} | {names}")


def run_boards(
    session: TelegramSession,
    settings: Settings,
    profile: Profile,
    conn,
    sources: list[str],
    limit: int,
    apply: bool,
    sleep=time.sleep,
) -> list[dict[str, str]]:
    page = session.page
    assert page is not None
    counter = DailyCounter(settings.project_root / "data" / "board_daily_counts.json")
    rng = random.Random()
    report: list[dict[str, str]] = []
    mode = "apply" if apply else "dry-run"
    for source in sources:
        if source not in SOURCES:
            print(f"Unknown board {source}")
            continue
        daily = {
            "naukri": settings.naukri_daily_limit,
            "wellfound": settings.wellfound_daily_limit,
        }.get(source, settings.board_batch_size)
        budget = run_budget(counter, source, daily, settings.board_batch_size) if apply else 0
        print(
            f"\nSearching {source} ({mode}; today {counter.count(source)}/{daily} applied"
            + (f"; this run may apply to {budget})" if apply else ")")
        )
        try:
            cards = _gather_cards(page, source, settings, limit)
        except RuntimeError as exc:
            print(f"    stopped: {exc}. Finish the check in the Chromium window and rerun.")
            continue
        print(f"    {len(cards)} cards")
        applied_now = 0
        applying = apply
        detail_tab = session.context.new_page() if session.context else page
        for card in cards:
            post = card_to_post(card, source)
            salary = (card.get("salary") or "").strip() or salary_display(post.raw_text)
            if db.already_applied(conn, post.company, post.role):
                print(f"    SKIP   duplicate                | {post.company} | {post.role} | {salary}")
                report.append({"source": source, "company": post.company or "", "role": post.role or "", "salary": salary, "would_apply": "no", "why": "duplicate",
                               "query": card.get("query", ""), "city": card.get("city", ""), "url": post.apply_url or ""})
                continue
            ok, why = board_fit(post, settings, source=source)
            kind = ""
            if ok:
                try:
                    full = jd_only(_open_detail(detail_tab, post.apply_url or ""))
                except Exception as exc:
                    full, why, ok = "", f"detail_error:{exc.__class__.__name__}", False
                if ok:
                    ok2, why2 = recheck_full_jd(full, post, settings, source)
                    if not ok2:
                        ok, why = False, why2
                if ok and source == "naukri":
                    kind = naukri_apply_kind(full, detail_tab.url)
                    if kind == "company_site":
                        log_manual_review(settings, source, post, "apply_on_company_site", mode)
                        ok, why = False, "manual_review(company_site)"
                    elif kind in {"already_applied", "needs_login", "captcha"}:
                        ok, why = False, kind
            verdict = "SEND" if ok else "SKIP"
            print(f"    {verdict:6} {why:28} | {post.company or '?'} | {post.role or '?'} | {salary} | {post.location[:40] if post.location else ''}" + (f" | apply={kind}" if kind else ""))
            if ok or why.startswith("manual"):
                print(f"           url: {post.apply_url}")
            if ok and source == "wellfound" and not applying:
                print(f"           note: {wellfound_note(profile, post)}")
            report.append({"source": source, "company": post.company or "", "role": post.role or "", "salary": salary,
                           "would_apply": "yes" if ok else ("manual" if why.startswith("manual") else "no"), "why": why,
                           "query": card.get("query", ""), "city": card.get("city", ""), "url": post.apply_url or ""})
            result = FilterResult(verdict=verdict, reason=why, relevant=ok)
            status = ProcessStatus.SKIPPED if not ok else ProcessStatus.SEEN
            if applying and ok:
                if applied_now >= budget:
                    print("    batch/daily limit reached; leaving the rest for the next run")
                    applying = False  # keep scoring, stop applying
                else:
                    if applied_now:
                        gap = next_gap_seconds(settings.board_gap_seconds_min, settings.board_gap_seconds_max, rng)
                        print(f"    waiting {gap:.0f}s")
                        sleep(gap)
                    try:
                        status = _apply_on_page(detail_tab, post, profile, submit=settings.auto_submit_boards, source=source)
                        if status == ProcessStatus.FORM_SUBMITTED:
                            applied_now += 1
                            counter.increment(source)
                        else:
                            log_manual_review(settings, source, post, "not_confirmed", mode)
                    except BoardStop as exc:
                        print(f"    stopped on {post.apply_url}: {exc.reason}")
                        log_manual_review(settings, source, post, exc.reason, mode)
                        status = ProcessStatus.SEEN
                        result.reason = exc.reason
                    except Exception as exc:
                        print(f"    apply failed: {exc}")
                        status = ProcessStatus.SEEN
            db.record(conn, post, result, status.value)
        if detail_tab is not page:
            try:
                detail_tab.close()
            except Exception:
                pass
        db.export_tracker(conn, db.tracker_path(settings.project_root))
        print_query_summary([r for r in report if r["source"] == source])
    return report
