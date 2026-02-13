from __future__ import annotations

from typing import Any

from jinja2 import Template


class CoverLetterGenerator:
    def __init__(self) -> None:
        self.templates = {
            "professional": Template(
                """
Dear Hiring Manager,

I am writing to express my interest in the {{ job_title }} position at {{ company_name }}.
With {{ years_experience }} years of relevant experience in {{ primary_skill_area }},
I believe my background is a strong fit for your role.

{% if custom_intro %}{{ custom_intro }}

{% endif %}In my recent role as {{ last_job_title }}, I worked with:
{% for skill in top_skills %}- {{ skill }}
{% endfor %}

Your posting highlights {{ key_job_requirement }}.
My experience with {{ relevant_experience }} prepares me to contribute from day one.

Thank you for your time and consideration.

Best regards,
{{ candidate_name }}
                """.strip()
            ),
            "enthusiastic": Template(
                """
Dear {{ company_name }} Team,

I am excited to apply for the {{ job_title }} role. I enjoy solving real problems in {{ primary_skill_area }},
and I am motivated by the opportunity to contribute to your team.

{% if custom_intro %}{{ custom_intro }}

{% endif %}My core strengths include:
{% for skill in top_skills %}- {{ skill }}
{% endfor %}

I would value the chance to discuss how I can help {{ company_name }}.

Kind regards,
{{ candidate_name }}
                """.strip()
            ),
            "concise": Template(
                """
Dear Hiring Manager,

I am applying for the {{ job_title }} position at {{ company_name }}. I bring {{ years_experience }} years of experience and strong skills in {% for skill in top_skills %}{{ skill }}{% if not loop.last %}, {% endif %}{% endfor %}.

Thank you for your consideration.

Best,
{{ candidate_name }}
                """.strip()
            ),
        }

    def generate(
        self,
        resume_data: dict[str, Any],
        job_data: dict[str, Any],
        tone: str = "professional",
        custom_intro: str = "",
    ) -> str:
        template = self.templates.get(tone, self.templates["professional"])
        experiences = resume_data.get("experience", []) or []
        first_exp = experiences[0] if experiences and isinstance(experiences[0], dict) else {}
        context = {
            "job_title": job_data.get("title", "the role"),
            "company_name": job_data.get("company", "the company"),
            "years_experience": self._estimate_years(experiences),
            "primary_skill_area": self._get_primary_skill_area(resume_data),
            "top_skills": resume_data.get("skills", [])[:5],
            "last_job_title": first_exp.get("title", "my recent role"),
            "key_job_requirement": self._extract_key_requirement(job_data),
            "relevant_experience": self._find_relevant_experience(resume_data, job_data),
            "candidate_name": self._extract_name(resume_data),
            "custom_intro": custom_intro,
        }
        return template.render(**context)

    def _estimate_years(self, experiences: list[dict[str, str]]) -> int:
        return max(len(experiences) * 2, 1)

    def _get_primary_skill_area(self, resume_data: dict[str, Any]) -> str:
        skills = [s.lower() for s in resume_data.get("skills", [])]
        data_skills = {"python", "sql", "spark", "airflow", "dbt", "pandas"}
        web_skills = {"react", "javascript", "typescript", "html", "css", "node"}
        data_count = len(data_skills & set(skills))
        web_count = len(web_skills & set(skills))
        if data_count > web_count:
            return "data engineering"
        if web_count > data_count:
            return "web engineering"
        return "software engineering"

    def _extract_key_requirement(self, job_data: dict[str, Any]) -> str:
        text = (job_data.get("requirements") or job_data.get("description") or "").strip()
        if not text:
            return "strong technical and collaboration skills"
        return text[:120]

    def _find_relevant_experience(self, resume_data: dict[str, Any], job_data: dict[str, Any]) -> str:
        experiences = resume_data.get("experience", [])
        if not experiences:
            return "my technical background"
        return experiences[0].get("title", "my recent role")

    def _extract_name(self, resume_data: dict[str, Any]) -> str:
        raw_text = (resume_data.get("raw_text") or "").strip()
        if raw_text:
            first_line = raw_text.splitlines()[0].strip()
            if first_line:
                return first_line
        return "Candidate"
