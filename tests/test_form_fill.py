from apply_bot.apply.form_fill import answer_for_question, fact_bank, heading_score
from apply_bot.config import load_profile
from apply_bot.models import ApplicationDraft, JobPost


def test_fact_bank_answers_common_form_questions():
    profile = load_profile()
    post = JobPost(
        company="RoadVision AI",
        role="SDE Intern",
        location="New Delhi",
        stipend="25000",
        source_fingerprint="f",
    )
    draft = ApplicationDraft(subject="x", body="I built FastAPI APIs and React dashboards.")
    facts = fact_bank(profile, post, draft)

    assert "Sumanth" in answer_for_question("Full Name *", facts)
    assert "sumanthponugupati" in answer_for_question("Email ID", facts).lower()
    assert "9110368779" in answer_for_question("WhatsApp / Mobile Number", facts)
    assert "linkedin.com" in answer_for_question("LinkedIn profile", facts)
    assert "github.com" in answer_for_question("GitHub link", facts)
    assert "github.io" in answer_for_question("Portfolio website", facts)
    assert "drive.google.com" in answer_for_question("Resume link", facts)
    assert answer_for_question("Current CGPA", facts) == "6.89"
    assert "2026" in answer_for_question("Graduation year / Batch", facts)
    assert "Amrita" in answer_for_question("College / University name", facts)
    assert "Yes" in answer_for_question("Are you available to join immediately?", facts)
    assert answer_for_question("Are you willing to relocate?", facts)
    assert "SDE Intern" in answer_for_question("Role you are applying for", facts)
    assert answer_for_question("Any FinTech Experience?", facts) == "No"
    assert "Sumanth" in answer_for_question("Name", facts)
    assert "Sumanth" in answer_for_question("Name\xa0", facts)
    monday = answer_for_question("Nearest Monday / joining date", facts)
    assert monday
    assert "/" in monday or "-" in monday
    assert "6 months" in answer_for_question("Internship duration", facts)
    assert answer_for_question("Year of Graduation?", facts) == "2026"
    assert answer_for_question("Expected Date of Joining?", facts) == facts["join_date"]
    assert "Immediate" in answer_for_question("How soon will you be able to join the team", facts)
    assert answer_for_question("Have you written any technical blogs or tutorials?", facts) == "No"
    assert answer_for_question("Graduated?", facts) == "Yes"
    assert answer_for_question("Please list your 10th grade score", facts) == "100%"
    assert "90.5%" in answer_for_question("Please list your 12th grade score", facts)
    assert "omniXM" in answer_for_question("Experience - Full Time & Internship Exp Separately", facts)
    assert answer_for_question("Current CTC / Stipend", facts) == "0"
    ans = answer_for_question("Expected CTC (LPA)", facts)
    assert "8" in ans or "6" in ans, ans  # floor 6 LPA, prefer ~8
    assert answer_for_question("Briefly mention one best project (MERN Stack)", facts)
    assert "drive.google.com" in answer_for_question("Link to resume Anyone can view", facts)
    assert answer_for_question("Are you willing to work from Noida?", facts) != "Yes"
    assert answer_for_question("Which programming languages are you comfortable with?", facts) == "Other"
    from apply_bot.apply.form_fill import align_to_options
    assert align_to_options("No", ["Yes", "No"]) == "No"
    assert align_to_options("Immediate", ["1 week", "Immediate Joiner", "2 weeks"]) == "Immediate Joiner"
    phone = answer_for_question("Phone Number", facts)
    assert phone.isdigit()
    assert len(phone) == 10
    assert "drive.google.com" in answer_for_question("Share your resume / CV link.", facts)
    assert answer_for_question("Location", facts) == facts["city"]
    assert answer_for_question("Graduation marks till pre-final year.", facts) == "6.89"
    assert answer_for_question("Any prior Internship experience?", facts) == "Yes"
    assert (
        answer_for_question(
            "Have you completed an internship (min. of 3 months) in Data Analytics involving hands-on use of SQL and Python?",
            facts,
        )
        == "No"
    )
    assert "LogiXair" in answer_for_question(
        "What’s the craziest or most interesting thing you’ve built so far, and which AI tools did you use to build it?",
        facts,
    )
    assert answer_for_question("Leet code Profile (Write NA if not available)", facts) == "NA"
    post.raw_text = "Job ID: 26014274 Apply now"
    facts_id = fact_bank(profile, post, draft)
    assert answer_for_question("Job ID", facts_id) == "26014274"


def test_identity_fields_do_not_swap():
    profile = load_profile()
    post = JobPost(company="CiteWorks", role="Full Stack Intern", source_fingerprint="f")
    draft = ApplicationDraft(subject="x", body="why text about FastAPI")
    facts = fact_bank(profile, post, draft)

    name = answer_for_question("Name", facts)
    assert name == "Ponugupati Sumanth"
    assert "omniXM" not in name
    assert answer_for_question("Full Name *", facts) == "Ponugupati Sumanth"
    assert "omniXM" not in answer_for_question("Your name", facts)

    company = answer_for_question("Current company", facts)
    assert company == "omniXM"
    assert "Sumanth" not in company

    college = answer_for_question("College / University name", facts)
    assert "Amrita" in college
    assert college != facts["name"]
    assert "omniXM" not in college

    email = answer_for_question("Email", facts)
    assert "sumanthponugupati" in email.lower()
    assert email != facts["name"]
    assert "omniXM" not in email

    assert answer_for_question("Please list your 10th grade score", facts) == "100%"
    assert answer_for_question("10th", facts) == "100%"
    assert answer_for_question("Current CGPA", facts) == "6.89"

    assert heading_score("Name", "Name") == 100
    assert heading_score("Current company", "Name") == 0
    assert heading_score("College / University name", "Name") == 0
    assert heading_score("Email ID", "Name") == 0
    assert answer_for_question("Are you available in-office in Gurgaon?", facts) != "Yes"
    assert "Backend" in answer_for_question("Describe you in three words", facts)
    assert answer_for_question("Rate yourself 0–5 on Python", facts) == "4"
    assert answer_for_question("Rate yourself 0–5 on SQL", facts) == "3"
    assert "SDE Premium" in answer_for_question("Name of the premium group", facts)
    assert "LogiXair" in answer_for_question("What makes you good for this role?", facts) or answer_for_question(
        "What makes you good for this role?", facts
    )
    why_amex = answer_for_question("What makes you good for this role?", facts)
    assert why_amex
    from apply_bot.apply.form_fill import stack_option_ticks
    ticks = stack_option_ticks(["React.js", "Spring Boot", "TypeScript", "Kubernetes"])
    assert "React.js" in ticks and "TypeScript" in ticks
    assert "Spring Boot" not in ticks
