from __future__ import annotations

import sys
import typer

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from apply_bot.boards.apply import open_board_logins, run_boards
from apply_bot.config import load_profile, load_settings
from apply_bot.linkedin.browser import LinkedInSession
from apply_bot.linkedin.messenger import (
    check_replies,
    draft_resume_reply,
    generate_message,
    load_sent_profile_urls,
    load_skipped_profile_urls,
    normalize_profile_url,
    send_messages,
)
from apply_bot.linkedin.scraper import (
    get_today_count,
    load_existing_contacts,
    save_contacts,
    scrape_connections,
)
from apply_bot.pipeline import process_messages, run_extract
from apply_bot.store import db
from apply_bot.telegram.browser import TelegramSession
from apply_bot.watch import watch_loop

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command("open-channel")
def open_channel() -> None:
    """Open Telegram Web and land on SDE Premium Group. Log in once if asked."""
    settings = load_settings()
    shots = settings.screenshot_dir
    shots.mkdir(parents=True, exist_ok=True)
    with TelegramSession(settings) as session:
        try:
            session.open_channel()
        except Exception as exc:
            typer.echo(f"Could not open the channel yet: {exc}")
            if session.page:
                fail = shots / "open-channel-fail.png"
                session.page.screenshot(path=str(fail), full_page=True)
                typer.echo(f"Saved screenshot to {fail}")
                typer.echo(
                    "Chromium will stay open 3 minutes. "
                    "Finish Telegram login / open SDE Premium Group there."
                )
                session.page.wait_for_timeout(180_000)
            raise
        typer.echo(
            f"Opened {settings.channel_title}. Session is saved for next runs. "
            "Press Enter to close this window."
        )
        try:
            input()
        except EOFError:
            session.page.wait_for_timeout(120_000) if session.page else None


@app.command("dry-run")
def dry_run(
    limit: int = typer.Option(10, "--limit", "-n"),
    use_llm_email: bool = typer.Option(True, "--llm-email/--no-llm-email", help="Use LLM-generated emails (default: True)")
) -> None:
    """Extract and score posts. Does not create Gmail drafts or fill forms."""
    settings = load_settings()
    conn = db.connect(settings.database_path)
    try:
        with TelegramSession(settings) as session:
            messages = run_extract(session, settings, limit=limit)
            process_messages(messages, settings, conn, session=session, apply=False, use_llm_email=use_llm_email)
    finally:
        conn.close()


@app.command("apply-once")
def apply_once(
    limit: int = typer.Option(10, "--limit", "-n"),
    use_llm_email: bool = typer.Option(True, "--llm-email/--no-llm-email", help="Use LLM-generated emails (default: True)")
) -> None:
    """Extract, score, and create Gmail drafts / filled forms. Does not send or submit."""
    settings = load_settings()
    conn = db.connect(settings.database_path)
    try:
        with TelegramSession(settings) as session:
            messages = run_extract(session, settings, limit=limit)
            process_messages(messages, settings, conn, session=session, apply=True, use_llm_email=use_llm_email)
    finally:
        conn.close()


@app.command("dry-run-emails")
def dry_run_emails(limit: int = typer.Option(20, "--limit", "-n")) -> None:
    """Generate LLM emails for last N jobs without sending (for approval)."""
    settings = load_settings()
    conn = db.connect(settings.database_path)
    try:
        with TelegramSession(settings) as session:
            messages = run_extract(session, settings, limit=limit)
            process_messages(messages, settings, conn, session=session, apply=False, use_llm_email=True)
    finally:
        conn.close()


@app.command("list")
def list_jobs(
    applied_only: bool = typer.Option(False, "--applied", help="Only drafts/forms/careers"),
) -> None:
    """Print the saved job tracker (company, role, stipend, email/link)."""
    settings = load_settings()
    conn = db.connect(settings.database_path)
    try:
        xlsx_path = db.export_tracker(conn, db.tracker_path(settings.project_root))
        rows = conn.execute(
            """
            SELECT created_at, company, role, stipend, apply_email, apply_url, verdict, status, apply_status
            FROM applications
            WHERE (? = 0) OR status IN ('draft_created', 'form_prepared', 'careers_opened', 'email_sent', 'form_submitted')
            ORDER BY created_at DESC, id DESC
            """,
            (1 if applied_only else 0,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        typer.echo("No jobs logged yet.")
        return
    for row in rows:
        contact = row["apply_email"] or row["apply_url"] or "-"
        typer.echo(
            f"{(row['apply_status'] or row['status'] or '-'):28} | {row['company'] or '?'} | "
            f"{row['role'] or '?'} | {row['stipend'] or '-'} | {contact}"
        )
    typer.echo(f"\nExcel file: {xlsx_path}")


@app.command("mark-status")
def mark_status(
    company: str = typer.Argument(..., help="Company name as stored"),
    status: str = typer.Argument(..., help="Sent | Form submitted | Draft (not sent) | ..."),
    role: str = typer.Option("", "--role", help="Role if the company has more than one"),
) -> None:
    """Update Apply status after you send mail or submit a form."""
    settings = load_settings()
    conn = db.connect(settings.database_path)
    try:
        changed = db.mark_apply_status(conn, company, status, role or None)
        xlsx_path = db.export_tracker(conn, db.tracker_path(settings.project_root))
    finally:
        conn.close()
    if not changed:
        typer.echo(f"No rows matched company={company!r} role={role or 'any'}")
        raise typer.Exit(1)
    typer.echo(f"Updated {changed} row(s) to {status!r}. Excel: {xlsx_path}")


def _board_sources(source: str) -> list[str]:
    if source == "all":
        return ["naukri", "wellfound", "workatastartup"]
    return [source]


@app.command("login-boards")
def login_boards() -> None:
    """Open Naukri, Wellfound, and Work at a Startup so you can sign in once."""
    settings = load_settings()
    with TelegramSession(settings) as session:
        open_board_logins(session)


@app.command("apply-boards")
def apply_boards(
    source: str = typer.Option(
        "all",
        "--source",
        help="naukri, wellfound, workatastartup, or all",
    ),
    limit: int = typer.Option(8, "--limit", "-n"),
    apply: bool = typer.Option(False, "--apply/--dry-run", help="Default is --dry-run (search and score only)."),
) -> None:
    """Search full-time AI, backend, and software roles. Applies only with --apply."""
    settings = load_settings()
    profile = load_profile()
    conn = db.connect(settings.database_path)
    try:
        with TelegramSession(settings) as session:
            run_boards(
                session,
                settings,
                profile,
                conn,
                _board_sources(source),
                limit,
                apply,
            )
    finally:
        conn.close()


@app.command("naukri-touch")
def naukri_touch(save: bool = typer.Option(False, "--save/--dry-run")) -> None:
    """Re-save the Naukri resume headline (needs naukri_profile_touch: true). Default: fill only, no save."""
    from apply_bot.boards.touch import naukri_profile_touch

    settings = load_settings()
    profile = load_profile()
    with TelegramSession(settings) as session:
        assert session.page is not None
        print(naukri_profile_touch(session.page, profile.naukri_headline,
                                   enabled=settings.naukri_profile_touch, dry_run=not save))


@app.command("watch")
def watch(
    once: bool = typer.Option(False, "--once", help="Run a single poll cycle"),
    apply: bool = typer.Option(True, "--apply/--no-apply"),
    limit: int = typer.Option(15, "--limit", "-n"),
) -> None:
    """Poll the channel and create drafts for new matching posts."""
    watch_loop(once=once, apply=apply, limit=limit)


@app.command("linkedin-dm")
def linkedin_dm(
    send: bool = typer.Option(False, "--send", help="Actually send messages (default is dry-run)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max messages per day (default: 20)"),
) -> None:
    """Send LinkedIn referral messages to 1st-degree connections."""
    settings = load_settings()
    contacts_csv = settings.project_root / "data" / "linkedin_contacts.csv"
    outreach_csv = settings.project_root / "data" / "linkedin_outreach.csv"
    daily_counts_json = settings.project_root / "data" / "linkedin_daily_counts.json"

    with LinkedInSession(settings) as session:
        page = session.open_connections()

        typer.echo("Scraping LinkedIn connections...")
        typer.echo("Waiting 10 seconds for page to load and for you to log in if needed...")
        page.wait_for_timeout(10000)

        contacts = scrape_connections(page, settings)
        typer.echo(f"Found {len(contacts)} eligible contacts")

        # Contacts CSV = contact cache only (never treat as already-sent).
        save_contacts(contacts, contacts_csv)

        if not contacts:
            typer.echo("No contacts found to message.")
            return

        # Outreach CSV sent rows = already messaged.
        sent_urls = load_sent_profile_urls(outreach_csv)
        skipped_urls = load_skipped_profile_urls(outreach_csv) - sent_urls
        new_contacts = [
            c for c in contacts
            if normalize_profile_url(c.get("profile_url", "")) not in sent_urls
            and normalize_profile_url(c.get("profile_url", "")) not in skipped_urls
        ]
        typer.echo(f"Permanently skipped (3+ safety skips): {len(skipped_urls)}")
        typer.echo(f"Already messaged (outreach log): {len(sent_urls)}")
        typer.echo(f"Eligible to message (not yet sent): {len(new_contacts)}")

        if not new_contacts:
            typer.echo("No new contacts to message.")
            return

        if not send:
            typer.echo("\n=== DRY RUN (no messages sent) ===")
            for i, contact in enumerate(new_contacts[:limit]):
                first_name = contact["name"].split()[0] if contact.get("name") else "there"
                company = contact.get("company") or ""
                message = generate_message(first_name, company, settings)
                typer.echo(f"\n{i+1}. {contact.get('name')} ({company or 'no company'})")
                typer.echo(f"   Profile: {contact.get('profile_url')}")
                typer.echo(f"   Headline: {contact.get('headline')}")
                typer.echo(f"   Message ({len(message)} chars): {message}")
            typer.echo(f"\nTotal previewed: {min(len(new_contacts), limit)} contacts")
            typer.echo("Use --send flag to actually send messages.")
            return

        current_count = get_today_count(daily_counts_json)
        remaining = limit - current_count
        if remaining <= 0:
            typer.echo(f"Daily limit of {limit} already reached ({current_count} sent today).")
            return

        contacts_to_message = new_contacts[:remaining]
        typer.echo(f"Sending messages to {len(contacts_to_message)} contacts (limit: {remaining})")

        results = send_messages(page, contacts_to_message, settings, daily_limit=limit, dry_run=False)

        typer.echo(f"\n=== Results ===")
        typer.echo(f"Sent: {results['sent']}")
        typer.echo(f"Skipped: {results['skipped']}")
        typer.echo(f"Errors: {results['errors']}")
        if results["stopped_early"]:
            typer.echo(f"Stopped early: {results['reason']}")


@app.command("linkedin-inbox")
def linkedin_inbox() -> None:
    """Check LinkedIn inbox for replies to sent messages."""
    settings = load_settings()

    with LinkedInSession(settings) as session:
        page = session.open_inbox()

        typer.echo("Waiting 10 seconds for page to load and for you to log in if needed...")
        page.wait_for_timeout(10000)

        typer.echo("Checking for replies...")
        replies = check_replies(page, settings)

        if not replies:
            typer.echo("No new replies found.")
            return

        typer.echo(f"\nFound {len(replies)} reply(ies) requesting resume:\n")
        for i, reply in enumerate(replies):
            typer.echo(f"{i+1}. {reply['name']} ({reply['company']})")
            typer.echo(f"   Message: {reply['message'][:100]}...")
            typer.echo(f"   Profile: {reply['profile_url']}")

            draft = draft_resume_reply(reply["name"], reply["message"])
            typer.echo(f"\n   Draft reply:")
            typer.echo(f"   {draft}")
            typer.echo(f"\n   Resume link: {reply.get('resume_link', 'N/A')}")

        typer.echo("\nPlease review and send manually, or ask me to confirm.")


@app.command("linkedin-followup")
def linkedin_followup(
    send: bool = typer.Option(False, "--send", help="Send drafts marked approved in the drafts JSON (default: dry run)"),
    since: str = typer.Option("", "--since", help="Only asks/replies on or after YYYY-MM-DD (default: all unanswered)"),
    max_threads: int = typer.Option(120, "--max-threads", help="How many inbox threads to read"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max follow-ups sent per day"),
    drafts_path: str = typer.Option("", "--drafts", help="Drafts JSON to send from (default: today's)"),
) -> None:
    """Read LinkedIn replies to referral outreach, classify, draft follow-ups; --send sends approved drafts."""
    import json as _json
    from datetime import date as _date
    from pathlib import Path as _Path
    from apply_bot.linkedin.followup import build_drafts, collect_threads, send_followups

    settings = load_settings()
    data_dir = settings.project_root / "data"
    stamp = _date.today().strftime("%Y%m%d")
    dpath = _Path(drafts_path) if drafts_path else data_dir / f"linkedin_followup_drafts_{stamp}.json"

    with LinkedInSession(settings) as session:
        page = session.open_inbox()
        page.wait_for_timeout(5000)
        if any(m in (page.url or "") for m in ("/login", "/authwall", "/checkpoint", "/uas/")):
            typer.echo(f"LinkedIn needs login: {page.url}")
            raise typer.Exit(2)
        if send:
            if not dpath.exists():
                typer.echo(f"No drafts file: {dpath}")
                raise typer.Exit(1)
            drafts = _json.loads(dpath.read_text(encoding="utf-8"))
            results = send_followups(page, settings, drafts, daily_limit=limit)
            out = data_dir / f"linkedin_followup_send_{stamp}.json"
            out.write_text(_json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
            for r in results:
                typer.echo(f"{r['result']:18} | {r['name']} | {r.get('company', '')}")
            typer.echo(f"Send results: {out}")
            return
        threads = collect_threads(page, max_threads=max_threads)
        (data_dir / f"linkedin_followup_threads_{stamp}.json").write_text(
            _json.dumps(threads, indent=2, ensure_ascii=False), encoding="utf-8")
        drafts = build_drafts(settings, threads, since or None)
        dpath.write_text(_json.dumps(drafts, indent=2, ensure_ascii=False), encoding="utf-8")
        typer.echo(f"\nThreads read: {len(threads)}; referral replies: {len(drafts)}")
        for d in drafts:
            typer.echo(f"\n[{d['status']}] {d['name']} ({d['company'] or '?'}) {d['their_date']} cat={d['category']}")
            typer.echo(f"   They: {d['their_text'][:200]!r}")
            if d["skip_reason"]:
                typer.echo(f"   Reason: {d['skip_reason']}")
            if d["draft"]:
                typer.echo(f"   Draft: {d['draft']}")
        typer.echo(f"\nDrafts: {dpath}  (set \"approved\": true, then run with --send)")



def main() -> None:
    app()
