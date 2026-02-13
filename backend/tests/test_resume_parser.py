from app.services.resume_parser import ResumeParser


def test_extract_skills_and_experience():
    parser = ResumeParser(load_nlp=False)
    text = """
    John Doe
    Skills: Python, SQL, Apache Spark, Docker, AWS

    Experience:
    Data Engineer at TechCorp (2021-2023)
    """

    skills = parser._extract_skills(text)
    experiences = parser._extract_experience(text)

    assert "python" in skills
    assert "sql" in skills
    assert "spark" in skills
    assert len(experiences) >= 1
    assert "data engineer" in experiences[0]["title"].lower()


def test_extract_keywords_returns_values_for_non_empty_text():
    parser = ResumeParser(load_nlp=False)
    text = "Python data pipelines SQL Spark Airflow analytics engineering"
    keywords = parser._extract_keywords(text)
    assert isinstance(keywords, list)
    assert len(keywords) > 0
