from __future__ import annotations

import time

from apply_bot.config import Settings, load_profile, load_settings
from apply_bot.notify import notify
from apply_bot.pipeline import process_messages, run_extract
from apply_bot.store import db
from apply_bot.telegram.browser import TelegramSession


def watch_loop(once: bool = False, apply: bool = True, limit: int = 15) -> None:
    settings = load_settings()
    profile = load_profile()
    conn = db.connect(settings.database_path)
    try:
        with TelegramSession(settings) as session:
            while True:
                try:
                    messages = run_extract(session, settings, limit=limit)
                    process_messages(
                        messages,
                        settings,
                        conn,
                        session=session,
                        apply=apply,
                        profile=profile,
                    )
                except Exception as exc:
                    notify("Apply bot", f"watch error: {exc}")
                if once:
                    break
                time.sleep(settings.poll_interval_seconds)
    finally:
        conn.close()
