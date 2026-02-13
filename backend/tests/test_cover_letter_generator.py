from app.services.cover_letter_generator import CoverLetterGenerator


def test_cover_letter_contains_job_and_company():
    generator = CoverLetterGenerator()

    resume = {
        "skills": ["Python", "SQL"],
        "experience": [{"title": "Data Engineer", "company": "TechCorp", "duration": "2021-2023"}],
        "raw_text": "Jane Doe",
    }
    job = {
        "title": "Data Engineer",
        "company": "Example GmbH",
        "description": "Build ETL pipelines",
        "requirements": "Python and SQL",
    }

    letter = generator.generate(resume, job, tone="professional")

    assert "Data Engineer" in letter
    assert "Example GmbH" in letter
    assert "Jane Doe" in letter
