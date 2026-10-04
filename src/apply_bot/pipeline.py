from __future__ import annotations

from apply_bot.apply.deliver_policy import should_auto_send_email
from apply_bot.apply.forms import prepare_form, try_submit_careers
from apply_bot.apply.generator import generate_draft
from apply_bot.apply.gmail_draft import create_gmail_draft
from apply_bot.config import Profile, Settings, load_profile
from apply_bot.filter.legitimacy import verdict_for
from apply_bot.filter.relevance import is_relevant
from apply_bot.models import ExtractedMessage, FilterResult, JobPost, ProcessStatus
from apply_bot.parse.gemini import parse_job
from apply_bot.parse.regex import classify_method
from apply_bot.store import db
from apply_bot.stuck import opening_is_stuck
from apply_bot.telegram.browser import TelegramSession
from apply_bot.telegram.extract import extract_messages


def parse_extracted(msg: ExtractedMessage, settings: Settings) -> JobPost:
    return parse_job(
        text=msg.text,
        fingerprint=msg.fingerprint,
        settings=settings,
        hrefs=msg.hrefs,
        screenshot_path=msg.screenshot_path,
        needs_vision=msg.needs_vision,
    )


def decide(
    post: JobPost,
    settings: Settings,
    conn,
    profile: Profile | None = None,
) -> tuple[bool, str, FilterResult | None]:
    stuck = opening_is_stuck(post)
    if stuck:
        return False, stuck, FilterResult(verdict="SKIP", reason=stuck, relevant=False)
    applied = db.already_applied(conn, post.company, post.role)
    ok, reason = is_relevant(post, settings, already_applied=applied, profile=profile)
    if not ok:
        return False, reason, FilterResult(verdict="SKIP", reason=reason, relevant=False)
    return True, reason, verdict_for(post, settings)


def format_extract_line(index: int, msg: ExtractedMessage) -> str:
    links = " | ".join(msg.hrefs) if msg.hrefs else "(none)"
    return (
        f"#{index}  fingerprint={msg.fingerprint}\n"
        f"    text_len={len(msg.text)}  hrefs={len(msg.hrefs)}  vision={str(msg.needs_vision).lower()}\n"
        f"    preview={msg.preview}\n"
        f"    links= {links}"
    )


def format_verdict_line(post: JobPost, relevant: bool, reason: str, result: FilterResult | None) -> str:
    verdict = result.verdict if result and relevant else "SKIP"
    why = result.reason if result else reason
    return (
        f"{verdict:6} {why:24} | {post.company or '?'} | {post.role or '?'} | "
        f"{post.apply_email or post.apply_url or '-'}"
    )


def deliver(
    session: TelegramSession,
    post: JobPost,
    result: FilterResult,
    settings: Settings,
    profile: Profile,
) -> ProcessStatus:
    if result.verdict == "SKIP":
        return ProcessStatus.SKIPPED

    draft = generate_draft(post, profile, result, settings)
    page = session.page
    assert page is not None

    prefer_email = post.apply_method in {"email", "email_and_form"} and post.apply_email
    if prefer_email:
        send = should_auto_send_email(post, result, settings.auto_send_email)
        sent = create_gmail_draft(page, post, draft, profile, send=send)
        return ProcessStatus.EMAIL_SENT if sent else ProcessStatus.DRAFT_CREATED

    if post.apply_method == "google_form" and post.apply_url:
        form_page = session.context.new_page() if session.context else page
        attempt = prepare_form(
            form_page,
            post,
            draft,
            profile,
            submit=settings.auto_submit_forms,
            settings=settings,
        )
        if attempt.fail_reason:
            result.reason = attempt.fail_reason
        if attempt.fail_reason in {"form_closed", "job_closed", "needs_login", "extra_step"}:
            return ProcessStatus.SKIPPED
        if attempt.fail_reason and "video" in attempt.fail_reason.lower():
            return ProcessStatus.SKIPPED
        return ProcessStatus.FORM_SUBMITTED if attempt.submitted else ProcessStatus.FORM_PREPARED

    if post.apply_url:
        attempt = try_submit_careers(
            page,
            post,
            draft,
            profile,
            submit=settings.auto_submit_careers,
            settings=settings,
        )
        if attempt.fail_reason:
            result.reason = attempt.fail_reason
        if attempt.fail_reason in {"form_closed", "job_closed", "needs_login", "extra_step"}:
            return ProcessStatus.SKIPPED
        return ProcessStatus.FORM_SUBMITTED if attempt.submitted else ProcessStatus.CAREERS_OPENED

    return ProcessStatus.SKIPPED


def job_from_row(row) -> JobPost:
    email = row["apply_email"] or None
    url = row["apply_url"] or None
    method = row["apply_method"] or classify_method(email, url, False)
    if method not in {"email", "google_form", "careers", "email_and_form", "unknown"}:
        method = classify_method(email, url, False)
    stored = ""
    try:
        stored = (row["raw_text"] or "").strip()
    except (IndexError, KeyError):
        stored = ""
    raw = stored or (
        f"Company - {row['company'] or ''}\n"
        f"Role - {row['role'] or ''}\n"
        f"Batch - {row['batch'] or '2027'}\n"
    )
    if not stored:
        if email:
            raw += f"Apply - {email}\n"
        if url:
            raw += f"{url}\n"
    return JobPost(
        company=row["company"],
        role=row["role"],
        stipend=row["stipend"],
        location=row["location"],
        batch_raw=row["batch"],
        batch_includes_2027=True,
        apply_method=method,
        apply_email=email,
        apply_url=url,
        raw_text=raw,
        source_fingerprint=row["fingerprint"],
    )


def retry_incomplete(
    session: TelegramSession,
    settings: Settings,
    conn,
    profile: Profile,
) -> None:
    parked = db.mark_stuck_skipped(conn)
    if parked:
        print(f"\nSkipped {len(parked)} stuck openings (login / ATS / RagaAI / picker)")
        for company, role, why in parked:
            print(f"    SKIP   {why:24} | {company} | {role}")
        db.export_tracker(conn, db.tracker_path(settings.project_root))
    rows = db.incomplete_rows(conn)
    if not rows:
        return
    print(f"\nRetrying {len(rows)} incomplete applications with current API / fill logic")
    for row in rows:
        post = job_from_row(row)
        relevant, reason, result = decide(post, settings, conn, profile=profile)
        print("   ", format_verdict_line(post, relevant, reason, result))
        if result is None:
            result = FilterResult(verdict="SKIP", reason=reason, relevant=False)
        status = (
            ProcessStatus.SKIPPED
            if (not relevant or result.verdict == "SKIP")
            else ProcessStatus.SEEN
        )
        if relevant and result.verdict != "SKIP":
            try:
                status = deliver(session, post, result, settings, profile)
                from apply_bot.notify import notify

                notify("Apply bot", f"retry {result.verdict} {status.value}: {post.company} {post.role}")
            except Exception as exc:
                print(f"    retry deliver failed: {exc}")
                status = ProcessStatus.SEEN
        db.record(conn, post, result, status.value)
        db.export_tracker(conn, db.tracker_path(settings.project_root))


def run_extract(session: TelegramSession, settings: Settings, limit: int) -> list[ExtractedMessage]:
    page = session.open_channel()
    return extract_messages(page, settings, limit=limit)


def process_messages(
    messages: list[ExtractedMessage],
    settings: Settings,
    conn,
    session: TelegramSession | None = None,
    apply: bool = False,
    profile: Profile | None = None,
) -> None:
    profile = profile or load_profile()
    for i, msg in enumerate(messages, start=1):
        print(format_extract_line(i, msg))
        if apply and db.fingerprint_seen(conn, msg.fingerprint):
            print("    already seen, skip")
            continue
        post = parse_extracted(msg, settings)
        relevant, reason, result = decide(post, settings, conn, profile=profile)
        print("   ", format_verdict_line(post, relevant, reason, result))
        if result is None:
            result = FilterResult(verdict="SKIP", reason=reason, relevant=False)
        status = (
            ProcessStatus.SKIPPED
            if (not relevant or result.verdict == "SKIP")
            else ProcessStatus.SEEN
        )
        if apply and relevant and result.verdict != "SKIP" and session is not None:
            if db.done_count(conn) >= 100:
                print("    reached 100 applications, stop applying")
                break
            try:
                status = deliver(session, post, result, settings, profile)
                from apply_bot.notify import notify

                notify("Apply bot", f"{result.verdict} {status.value}: {post.company} {post.role}")
            except Exception as exc:
                print(f"    deliver failed: {exc}")
                status = ProcessStatus.SEEN
        db.record(conn, post, result, status.value, msg.screenshot_path)
        db.export_tracker(conn, db.tracker_path(settings.project_root))
    if apply and session is not None:
        retry_incomplete(session, settings, conn, profile)
