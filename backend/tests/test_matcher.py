from app.services.matcher import JobMatcher


def test_skill_overlap_score():
    matcher = JobMatcher()

    score = matcher._skill_overlap_score(
        ["python", "sql", "docker"],
        ["python", "sql", "kubernetes", "aws"],
    )

    assert round(score, 3) == 0.533


def test_calculate_match_score_has_expected_fields():
    matcher = JobMatcher()
    resume = {
        "raw_text": "Python SQL Spark Docker Berlin",
        "skills": ["Python", "SQL", "Spark", "Docker"],
        "experience": [{"title": "Data Engineer", "company": "A", "duration": "2021-2023"}],
    }
    job = {
        "title": "Senior Data Engineer",
        "description": "Need Python SQL Spark and cloud skills",
        "requirements": "Experience with Spark",
        "keywords": ["python", "sql", "spark", "aws"],
        "location": "Berlin, Germany",
    }

    result = matcher.calculate_match_score(resume, job)

    assert 0.0 <= result["score"] <= 1.0
    assert "matched_skills" in result
    assert "missing_skills" in result
    assert "breakdown" in result
