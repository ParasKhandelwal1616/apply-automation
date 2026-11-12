from apply_bot.boards.search import is_job_url
from apply_bot.boards.rules import experience_ok


def test_wellfound_menu_pages_rejected():
    for href in ["https://wellfound.com/jobs", "https://wellfound.com/jobs/home",
                 "https://wellfound.com/jobs/applications", "https://wellfound.com/jobs/messages",
                 "https://wellfound.com/role/l/backend-engineer/bangalore"]:
        assert not is_job_url("wellfound", href), href


def test_wellfound_job_pages_accepted():
    assert is_job_url("wellfound", "https://wellfound.com/jobs/3123456-backend-engineer")
    assert is_job_url("wellfound", "https://wellfound.com/company/acme/jobs/987654-ml-engineer")
    assert not is_job_url("wellfound", "https://evil.example.com/jobs/3123456-backend-engineer")


def test_naukri_job_pages():
    assert is_job_url("naukri", "https://www.naukri.com/job-listings-python-developer-acme-bengaluru-1-to-4-years-201026000123")
    assert not is_job_url("naukri", "https://www.naukri.com/python-jobs-in-bangalore")


def test_experience_up_to_four_years():
    assert experience_ok("Experience: 1-4 years", 4)
    assert experience_ok("0-3 Yrs", 4)
    assert experience_ok("2+ years of experience in Python", 4)
    assert experience_ok("4+ years experience", 4)
    assert not experience_ok("5+ years of experience", 4)
    assert not experience_ok("5-8 Yrs", 4)
