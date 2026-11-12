from __future__ import annotations

import csv
from pathlib import Path

from apply_bot.linkedin.messenger import (
    build_referral_message,
    clean_company,
    load_sent_profile_urls,
    normalize_profile_url,
)


def test_build_referral_message_with_company():
    msg = build_referral_message("Alice", "Google")
    assert "Hi Alice" in msg
    assert "Google" in msg
    assert "referring" in msg.lower()
    assert "resume" in msg.lower()
    assert len(msg) <= 300


def test_build_referral_message_without_company():
    msg = build_referral_message("Bob", "")
    assert "Hi Bob" in msg
    assert " if " not in msg.lower() or "if bob" not in msg.lower()
    assert "your company" not in msg.lower()
    assert "referring me?" in msg
    assert len(msg) <= 300


def test_clean_company_drops_url_junk():
    assert clean_company("https://www.linkedin.com/in/foo") == ""
    assert clean_company("your company") == ""
    assert clean_company("Acme Corp") == "Acme Corp"


def test_normalize_profile_url():
    a = normalize_profile_url("https://www.linkedin.com/in/alice-smith/?trk=foo")
    b = normalize_profile_url("/in/alice-smith/")
    assert a == b == "https://www.linkedin.com/in/alice-smith"


def test_load_sent_profile_urls_only_sent_rows(tmp_path: Path):
    path = tmp_path / "outreach.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["name", "company", "profile_url", "sent_at", "error"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "name": "Alice",
                "company": "Google",
                "profile_url": "https://www.linkedin.com/in/alice/",
                "sent_at": "2026-11-06T10:00:00",
                "error": "",
            }
        )
        writer.writerow(
            {
                "name": "Bob",
                "company": "Meta",
                "profile_url": "https://www.linkedin.com/in/bob/",
                "sent_at": "",
                "error": "Failed to send",
            }
        )
    sent = load_sent_profile_urls(path)
    assert normalize_profile_url("https://www.linkedin.com/in/alice/") in sent
    assert normalize_profile_url("https://www.linkedin.com/in/bob/") not in sent

def test_recipient_name_matches_full_and_first():
    from apply_bot.linkedin.messenger import recipient_name_matches

    assert recipient_name_matches("Remove Mayank Kumar", "Mayank Kumar")
    assert recipient_name_matches("Mayank Kumar", "Mayank Kumar")
    # Long name: first-name token match on truncated header/pill
    assert recipient_name_matches("Mayank K.", "Mayank Kumar")
    assert recipient_name_matches("Remove Mayank", "Mayank Kumar")
    assert not recipient_name_matches("Remove Adhip Jadhav", "Mayank Kumar")
    assert not recipient_name_matches("", "Mayank Kumar")
    assert not recipient_name_matches("Remove Anand", "Vishal Anand")  # last-name only should fail


def test_is_transient_nav_error():
    from apply_bot.linkedin.messenger import is_transient_nav_error

    assert is_transient_nav_error(Exception("Page.goto: net::ERR_INTERNET_DISCONNECTED"))
    assert is_transient_nav_error(Exception("net::ERR_CONNECTION_RESET at https://x"))
    assert is_transient_nav_error(Exception("Target closed"))
    assert not is_transient_nav_error(Exception("Timeout 30000ms exceeded"))
    assert not is_transient_nav_error(Exception("Recipient bubble not verified"))


def test_thread_label_participants_excludes_self_any_order():
    from apply_bot.linkedin.messenger import thread_label_participants
    lab = "Close your conversation with Mayank Kumar and Sumanth Ponugupati"
    assert thread_label_participants(lab, "Ponugupati Sumanth") == ["Mayank Kumar"]
    assert thread_label_participants("Close your conversation with A B, C D and Sumanth Ponugupati", "Sumanth Ponugupati") == ["A B", "C D"]
    assert thread_label_participants("random", "x") == []
