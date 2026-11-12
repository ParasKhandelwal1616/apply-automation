from datetime import datetime, timedelta

from apply_bot.config import load_settings
from apply_bot.telegram.age import is_recent, label_to_date, post_age_hours

NOW = datetime(2026, 10, 17, 21, 0)


def test_timestamp_inside_and_outside_48h():
    fresh = (NOW - timedelta(hours=47)).timestamp()
    old = (NOW - timedelta(hours=49)).timestamp()
    assert is_recent(fresh, None, 48, now=NOW)[0] is True
    assert is_recent(old, None, 48, now=NOW)[0] is False


def test_date_labels():
    assert label_to_date("Today", NOW) == NOW.date()
    assert label_to_date("Yesterday", NOW) == NOW.date() - timedelta(days=1)
    assert label_to_date("October 15", NOW).day == 15
    assert label_to_date("15 Oct 2026", NOW).month == 10
    assert is_recent(None, "Today", 48, now=NOW)[0]
    assert is_recent(None, "Yesterday", 48, now=NOW)[0]
    assert is_recent(None, "October 16", 48, now=NOW)[0]
    assert not is_recent(None, "October 14", 48, now=NOW)[0]
    assert not is_recent(None, "September 30", 48, now=NOW)[0]


def test_undated_and_disabled():
    assert post_age_hours(None, None, NOW) is None
    assert is_recent(None, None, 48, now=NOW, keep_undated=True)[0]
    assert not is_recent(None, None, 48, now=NOW, keep_undated=False)[0]
    old = (NOW - timedelta(days=30)).timestamp()
    assert is_recent(old, None, 0, now=NOW)[0]


def test_settings_window_24h():
    settings = load_settings()
    assert settings.max_post_age_hours == 336  # 14-day window
    assert "SDE Premium Referrals" in settings.channel_title


def test_channel_title_variants():
    from apply_bot.telegram.browser import title_variants

    v = title_variants("SDE Premium Referrals 2.0")
    assert v[0] == "SDE Premium Referrals 2.0"
    assert "SDE Premium Referrals 2.O" in v
    assert "SDE Premium Referrals" in v


def test_scroll_stops_past_window():
    from apply_bot.models import ExtractedMessage
    from apply_bot.telegram.extract import reached_age_limit
    mk = lambda h: ExtractedMessage(fingerprint=str(h), posted_at=(NOW - timedelta(hours=h)).timestamp())
    assert not reached_age_limit([mk(1), mk(100), mk(160)], 168, now=NOW)
    assert reached_age_limit([mk(1), mk(100), mk(170)], 168, now=NOW)
    assert not reached_age_limit([mk(500)], 0, now=NOW)
