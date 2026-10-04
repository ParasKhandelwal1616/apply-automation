from __future__ import annotations

import typer

from apply_bot.config import load_settings
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
def dry_run(limit: int = typer.Option(10, "--limit", "-n")) -> None:
    """Extract and score posts. Does not create Gmail drafts or fill forms."""
    settings = load_settings()
    conn = db.connect(settings.database_path)
    try:
        with TelegramSession(settings) as session:
            messages = run_extract(session, settings, limit=limit)
            process_messages(messages, settings, conn, session=session, apply=False)
    finally:
        conn.close()


@app.command("apply-once")
def apply_once(limit: int = typer.Option(10, "--limit", "-n")) -> None:
    """Extract, score, and create Gmail drafts / filled forms. Does not send or submit."""
    settings = load_settings()
    conn = db.connect(settings.database_path)
    try:
        with TelegramSession(settings) as session:
            messages = run_extract(session, settings, limit=limit)
            process_messages(messages, settings, conn, session=session, apply=True)
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


@app.command("watch")
def watch(
    once: bool = typer.Option(False, "--once", help="Run a single poll cycle"),
    apply: bool = typer.Option(True, "--apply/--no-apply"),
    limit: int = typer.Option(15, "--limit", "-n"),
) -> None:
    """Poll the channel and create drafts for new matching posts."""
    watch_loop(once=once, apply=apply, limit=limit)


def main() -> None:
    app()
