import random
from datetime import date

from apply_bot.boards.fit import board_fit
from apply_bot.boards.limits import DailyCounter, next_gap_seconds, run_budget
from apply_bot.boards.note import wellfound_note
from apply_bot.boards.rules import (
    experience_ok,
    is_consultancy,
    mentions_fee_bond_training,
    min_experience_years,
    salary_display,
    size_ok,
    stage_ok,
)
from apply_bot.boards.search import naukri_search_urls, wellfound_search_urls
from apply_bot.boards.apply import log_manual_review, naukri_apply_kind
from apply_bot.config import Profile, Settings
from apply_bot.models import JobPost


def _settings(**kw) -> Settings:
    return Settings(board_cities=["bengaluru", "hyderabad", "chennai"], min_ctc_lpa=6, **kw)


def _post(text, source="naukri", company="Acme", role="Backend Engineer"):
    return JobPost(company=company, role=role, raw_text=text, location=text[:240],
                   source_fingerprint="t", apply_method=source, apply_url="https://x/" + str(abs(hash(text))))


def test_naukri_urls_have_verified_filters_per_city():
    s = _settings(board_queries=["python backend developer", "sde 1"])
    urls = naukri_search_urls(s)
    assert len(urls) == 6
    u = urls[0]
    assert "python-backend-developer-jobs-in-bangalore" in u
    for part in ("experience=1", "jobAge=1", "ctcFilter=6to10", "ctcFilter=25to50", "jobPostType=1", "sort=f"):
        assert part in u
    assert "jobAge=3" in naukri_search_urls(s, job_age=3)[0]
    assert any("hyderabad" in x for x in urls) and any("chennai" in x for x in urls)


def test_wellfound_urls_cities_and_remote():
    urls = wellfound_search_urls(_settings())
    assert "https://wellfound.com/role/l/backend-engineer/bangalore" in urls
    assert "https://wellfound.com/role/r/machine-learning-engineer" in urls
    assert not any("mumbai" in u or "pune" in u for u in urls)


def test_skip_rules():
    assert is_consultancy("Hiring on behalf of our client")
    assert is_consultancy("", company="ABC Staffing Solutions")
    assert not is_consultancy("Build ML systems", company="Tata Consultancy Services")
    assert mentions_fee_bond_training("2 year bond required")
    assert mentions_fee_bond_training("Registration fee of Rs 2000")
    assert not mentions_fee_bond_training("Model training and evaluation with PyTorch")
    assert min_experience_years("2-5 Yrs") == 2
    assert not experience_ok("3+ years of experience in Python")
    assert experience_ok("0-1 Yrs Fresher")
    assert experience_ok("1-3 Yrs")
    assert stage_ok("Series B · 51-200 employees") and not stage_ok("Seed stage startup")
    assert size_ok("51-200 employees") and not size_ok("1-10 employees") and not size_ok("1001-5000 employees")
    assert salary_display("Python dev 3-6 Lacs PA Bengaluru") == "3-6 Lacs PA"
    assert salary_display("Not disclosed") == "Not disclosed"


def test_board_fit_new_skips():
    s = _settings()
    assert board_fit(_post("Full time Python backend Bengaluru 8-12 LPA 0-1 Yrs"), s, source="naukri") == (True, "ok")
    assert board_fit(_post("Python developer Bengaluru 8-12 LPA 3-6 Yrs"), s, source="naukri") == (True, "ok")  # 1-4 yrs rule
    assert board_fit(_post("Python developer Bengaluru 8-12 LPA 5-8 Yrs"), s, source="naukri")[1] == "experience_gt_4y"
    assert board_fit(_post("Python backend Bengaluru 8-12 LPA 1-3 Yrs"), s, source="naukri")[0]
    assert board_fit(_post("Python developer Bengaluru 3-5 Lacs PA 0-1 Yrs"), s, source="naukri")[1] == "ctc_below_min"
    assert board_fit(_post("Python developer Bengaluru 8 LPA, training fee applicable"), s, source="naukri")[1] == "fee_bond_training"
    assert board_fit(_post("Python developer Bengaluru 8 LPA", company="XYZ Placement Consultants"), s, source="naukri")[1] == "consultancy"
    assert board_fit(_post("Python Bengaluru stipend", role="Python Intern"), s, source="naukri")[1].startswith("not_full_time")
    # description mentioning internships must NOT trigger the internship skip
    assert board_fit(_post("Python backend Bengaluru 8 LPA 0-1 Yrs. Internship or project experience with FastAPI preferred.",
                           role="Associate AI Engineer (Fresher)"), s, source="naukri") == (True, "ok")
    assert board_fit(_post("Python backend Bengaluru 8 LPA. Employment Type: Internship"), s, source="naukri")[1] == "not_full_time(internship)"
    assert board_fit(_post("Backend Engineer Internship Bengaluru Python", "wellfound"), s, source="wellfound")[1] == "not_full_time(internship)"
    assert board_fit(_post("Python backend Bengaluru 8 LPA", role="Backend Developer (Contract)"), s, source="naukri")[1] == "not_full_time(contract)"
    assert board_fit(_post("Backend engineer Pune 10 LPA"), s, source="naukri")[1] == "location"


def test_wellfound_floor_stage_size():
    s = _settings()
    good = "Backend Engineer Bangalore ₹10L – ₹18L Series B 51-200 employees Python"
    assert board_fit(_post(good, "wellfound"), s, source="wellfound") == (True, "ok")
    assert board_fit(_post("Backend Engineer Bangalore Python Series A"), s, source="wellfound")[0]  # no salary listed is ok
    assert board_fit(_post("Backend Engineer Bangalore ₹5L – ₹7L Python"), s, source="wellfound")[1] == "ctc_below_min"
    assert board_fit(_post("Backend Engineer Bangalore Seed Python"), s, source="wellfound")[1] == "stage_below_series_a"
    assert board_fit(_post("Backend Engineer Bangalore 1-10 employees Python"), s, source="wellfound")[1] == "company_size"
    assert board_fit(_post("Backend Engineer Remote India Python"), s, source="wellfound")[0]
    assert board_fit(_post("Backend Engineer Full-time Bangalore Python 2 years of experience", "wellfound"), s, source="wellfound")[0]
    assert board_fit(_post("Backend Engineer Full-time Bangalore Python 3+ years of experience", "wellfound"), s, source="wellfound")[0]  # 3+ ok under the 4-year rule
    assert board_fit(_post("Backend Engineer Full-time Bangalore Python 5+ years of experience", "wellfound"), s, source="wellfound")[1] == "experience_gt_4y"


def test_daily_counter_persists_and_budget(tmp_path):
    path = tmp_path / "counts.json"
    c = DailyCounter(path, today=date(2026, 10, 17))
    for _ in range(28):
        c.increment("naukri")
    again = DailyCounter(path, today=date(2026, 10, 17))
    assert again.count("naukri") == 28
    assert run_budget(again, "naukri", 30, 5) == 2
    assert run_budget(DailyCounter(path, today=date(2026, 10, 18)), "naukri", 30, 5) == 5
    gaps = [next_gap_seconds(30, 120, random.Random(i)) for i in range(50)]
    assert all(30 <= g <= 120 for g in gaps)


def test_wellfound_note_is_short_and_grounded():
    profile = Profile(proof_points=["LogiXair: WebSocket telemetry at 50 Hz with under 5 ms latency."])
    post = _post("Acme builds real-time fraud detection for Indian fintechs. Series B. Bangalore ₹12L", "wellfound",
                 company="Acme", role="Backend Engineer")
    note = wellfound_note(profile, post)
    assert note.count(".") <= 4 and len(note) < 500
    assert "50 Hz" in note and "fraud detection" in note and "Backend Engineer" in note


def test_naukri_apply_kind_and_manual_log(tmp_path):
    assert naukri_apply_kind("Save  Apply on company site") == "company_site"
    assert naukri_apply_kind("Save  Apply") == "direct"
    assert naukri_apply_kind("Already Applied") == "already_applied"
    s = _settings(project_root=tmp_path)
    post = _post("x")
    assert log_manual_review(s, "naukri", post, "apply_on_company_site", "dry-run") is True
    assert log_manual_review(s, "naukri", post, "apply_on_company_site", "dry-run") is False
    assert "apply_on_company_site" in (tmp_path / "data" / "manual_review.csv").read_text(encoding="utf-8")


def test_settings_yaml_board_defaults():
    from apply_bot.config import load_profile, load_settings
    s = load_settings()
    assert s.naukri_daily_limit == 30 and s.board_batch_size == 5
    assert s.naukri_profile_touch is False
    assert {"bengaluru", "hyderabad", "chennai"}.issubset(set(s.board_cities))
    assert set(s.board_cities) >= {"bengaluru", "hyderabad", "chennai", "gurugram", "mumbai", "pune", "noida"}
    assert "agentic ai engineer" in s.board_queries
    assert load_profile().naukri_headline


def test_local_boolean_filter():
    from apply_bot.boards.rules import keyword_filter
    groups = [["python", "fastapi"], ["backend", "ai engineer"]]
    ex = ["intern", "senior", "java"]
    assert keyword_filter("Python Backend Developer", "FastAPI APIs", groups, ex) == (True, "ok")
    assert keyword_filter("AI Engineer", "Python, LLMs", groups, ex)[0]
    assert keyword_filter("Backend Developer", "Go and Rust", groups, ex)[1] == "keywords_missing_group1"
    assert keyword_filter("Python Intern", "backend", groups, ex)[1] == "title_excludes:intern"
    assert keyword_filter("Senior Python Backend Engineer", "", groups, ex)[1] == "title_excludes:senior"
    assert keyword_filter("Java Backend Developer", "python", groups, ex)[1] == "title_excludes:java"
    assert not keyword_filter("Mail Engineer", "email", [["ai"]], [])[0]  # whole-word: 'ai' not in 'email'/'mail'
    s = _settings()
    assert board_fit(_post("Python backend Bengaluru 8-12 LPA 0-1 Yrs", role="Senior Backend Engineer"), s, source="naukri")[1].startswith("title_excludes")


def test_naukri_searches_one_query_one_city():
    from apply_bot.boards.search import naukri_search_url, naukri_searches
    s = _settings(board_queries=["fastapi developer", "sde 1"])
    pairs = naukri_searches(s)
    assert pairs[:3] == [("fastapi developer", "bengaluru"), ("fastapi developer", "hyderabad"), ("fastapi developer", "chennai")]
    assert len(pairs) == 6
    u = naukri_search_url(s, "sde 1", "bengaluru", 3)
    assert "k=sde+1" in u and "l=bangalore" in u and "jobAge=3" in u and " OR " not in u and "fastapi" not in u


def test_jd_only_drops_footer_and_similar_jobs():
    from apply_bot.boards.rules import jd_only
    page = ("Python AI Engineer Techolution 8-15 Lacs PA Job description " + "Build FastAPI services. " * 20 +
            "Beware of imposters! Fraudsters may ask you to pay registration fee. Similar jobs Posted by Staffing Services")
    jd = jd_only(page)
    assert "FastAPI" in jd and not mentions_fee_bond_training(jd) and not is_consultancy(jd)
    assert mentions_fee_bond_training(page)


def test_note_without_company():
    note = wellfound_note(Profile(proof_points=["X: 50 Hz"]), _post("Voice AI for clinics in India.", "wellfound", company=""))
    assert note.startswith("Hi team,") and "team team" not in note


def test_blocked_product_manager_and_service_desk():
    from apply_bot.config import load_settings
    from apply_bot.filter.relevance import is_relevant
    s = load_settings()
    assert "product manager" in s.deny_titles and "service desk" in s.deny_titles
    for role in ("Product Manager", "SERVICE DESK ANALYST – L1"):
        post = JobPost(company="X", role=role, raw_text=f"Role - {role} Batch - 2026 Location - Bengaluru Full time 10 LPA", source_fingerprint="f")
        assert is_relevant(post, s, False, profile=None)[0] is False
        assert board_fit(_post("Python Bengaluru 10 LPA", role=role), s, source="naukri")[0] is False
