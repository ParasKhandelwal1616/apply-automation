from apply_bot.boards.fit import board_fit, location_ok, salary_ok
from apply_bot.config import Settings
from apply_bot.models import JobPost


def _settings() -> Settings:
    return Settings(
        min_ctc_lpa=6,
        min_salary_usd=7000,
        board_cities=["bengaluru", "hyderabad", "chennai"],
    )


def _post(**kwargs) -> JobPost:
    base = dict(
        company="Acme",
        role="Backend Engineer",
        location="Bengaluru",
        raw_text="Full time Python FastAPI Bengaluru 8-12 LPA",
        source_fingerprint="t",
        apply_method="naukri",
    )
    base.update(kwargs)
    return JobPost(**base)


def test_naukri_full_time_city_and_ctc():
    ok, why = board_fit(_post(), _settings(), source="naukri")
    assert ok, why


def test_skips_intern_and_low_ctc_and_wrong_city():
    settings = _settings()
    assert board_fit(_post(role="Python Intern", raw_text="Bengaluru 8 LPA python"), settings, source="naukri")[0] is False
    assert board_fit(
        _post(raw_text="Full time software engineer Bengaluru 3-4 LPA"),
        settings,
        source="naukri",
    ) == (False, "ctc_below_min")
    assert board_fit(
        _post(location="Pune", raw_text="Full time software engineer Pune 10 LPA"),
        settings,
        source="naukri",
    ) == (False, "location")


def test_ai_role_and_remote_india_on_wellfound():
    post = _post(
        role="AI Engineer",
        raw_text="Full time AI engineer Remote India $90k Python",
        apply_method="wellfound",
    )
    ok, why = board_fit(post, _settings(), source="wellfound")
    assert ok, why


def test_usd_floor_and_unlisted_salary():
    settings = _settings()
    assert salary_ok("salary $5,000", settings, usd=True) == (False, "usd_below_min")
    assert salary_ok("salary not disclosed Bengaluru", settings, usd=False)[0] is True


def test_monthly_inr_floor_and_any_remote():
    settings = Settings(min_ctc_lpa=6, min_salary_usd=7000, min_monthly_inr=40000,
                        board_cities=["bengaluru", "hyderabad", "chennai"])
    assert salary_ok("stipend 25000/month Python", settings, usd=False) == (False, "monthly_below_min")
    assert salary_ok("stipend 45,000 per month", settings, usd=False)[0] is True
    assert salary_ok("CTC 8 LPA Bengaluru", settings, usd=False)[0] is True
    assert location_ok("Remote Python backend", settings, allow_remote_india=True) is True
    assert location_ok("WFH software engineer", settings, allow_remote_india=True) is True
    gurgaon = Settings(board_cities=["bengaluru", "hyderabad", "chennai", "gurugram", "mumbai", "pune", "noida"])
    assert location_ok("Gurgaon software engineer", gurgaon, allow_remote_india=False) is True
    assert location_ok("Noida Python backend", gurgaon, allow_remote_india=False) is True


def test_yc_skips_us_only():
    post = _post(
        raw_text="Full time backend Bengaluru must be a US citizen Python",
        apply_method="workatastartup",
    )
    assert board_fit(post, _settings(), source="workatastartup") == (False, "us_only")
