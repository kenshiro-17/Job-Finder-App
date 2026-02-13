from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.services.resume_parser import GERMAN_STOP_WORDS


class JobMatcher:
    def __init__(self) -> None:
        self.skill_aliases = {
            "js": "javascript",
            "ts": "typescript",
            "postgres": "postgresql",
            "k8s": "kubernetes",
            "g cloud": "gcp",
            "powerbi": "power bi",
            "apache spark": "spark",
        }
        self.job_skill_patterns = [
            r"\b(python|java|javascript|typescript|sql|scala|go|rust|r)\b",
            r"\b(django|flask|fastapi|react|vue|angular|spring|tensorflow|pytorch|node\.js|nodejs)\b",
            r"\b(aws|azure|gcp|docker|kubernetes|terraform)\b",
            r"\b(spark|hadoop|kafka|airflow|dbt|pandas|numpy|etl|elt|data warehouse)\b",
            r"\b(postgresql|mysql|mongodb|redis|elasticsearch|cassandra)\b",
            r"\b(git|jenkins|jira|tableau|power bi|excel)\b",
        ]

    def calculate_match_score(self, resume_data: dict[str, Any], job_data: dict[str, Any]) -> dict[str, Any]:
        resume_skills = self._normalize_set(resume_data.get("skills", []))
        job_skills = self._extract_job_skills(job_data)

        skill_score = self._skill_overlap_score(list(resume_skills), list(job_skills))
        keyword_score = self._keyword_similarity_score(
            resume_data.get("raw_text", ""),
            f"{job_data.get('title', '')} {job_data.get('description', '')} {job_data.get('requirements', '')}".strip(),
        )
        exp_score = self._experience_level_match(
            resume_data.get("experience", []),
            job_data.get("title", ""),
        )
        loc_score = self._location_match(
            resume_data.get("raw_text", ""),
            job_data.get("location", ""),
        )

        raw_total = skill_score * 0.5 + keyword_score * 0.25 + exp_score * 0.15 + loc_score * 0.1

        # Lift low-end clustering while preserving ranking at the high end.
        calibrated = min(1.0, max(0.03, raw_total)) ** 0.78
        if len(resume_skills & job_skills) >= 3:
            calibrated = min(1.0, calibrated + 0.05)

        return {
            "score": round(float(calibrated), 3),
            "matched_skills": sorted(resume_skills & job_skills),
            "missing_skills": sorted(job_skills - resume_skills),
            "breakdown": {
                "skill_match": round(skill_score, 3),
                "keyword_match": round(keyword_score, 3),
                "experience_match": round(exp_score, 3),
                "location_match": round(loc_score, 3),
                "raw_score": round(raw_total, 3),
            },
        }

    def _skill_overlap_score(self, resume_skills: list[str], job_keywords: list[str]) -> float:
        resume_set = self._normalize_set(resume_skills)
        job_set = self._normalize_set(job_keywords)
        if not resume_set or not job_set:
            return 0.0

        intersection = len(resume_set & job_set)
        coverage = intersection / max(1, len(job_set))
        precision = intersection / max(1, len(resume_set))
        return min(1.0, coverage * 0.8 + precision * 0.2)

    def _keyword_similarity_score(self, resume_text: str, job_text: str) -> float:
        if not resume_text.strip() or not job_text.strip():
            return 0.0

        resume_tokens = self._tokens(resume_text)
        job_tokens = self._tokens(job_text)
        if not resume_tokens or not job_tokens:
            return 0.0

        resume_set = set(resume_tokens)
        job_set = set(job_tokens)
        overlap = len(resume_set & job_set) / max(1, len(job_set))
        cosine = self._cosine_similarity(Counter(resume_tokens), Counter(job_tokens))
        return min(1.0, overlap * 0.65 + cosine * 0.35)

    def _experience_level_match(self, experiences: list[dict[str, str]], job_title: str) -> float:
        total_years = self._estimate_years(experiences)
        title = job_title.lower()

        if any(token in title for token in ("junior", "entry", "graduate", "intern")):
            return 1.0 if total_years <= 3 else 0.65

        if any(token in title for token in ("senior", "staff", "lead", "principal")):
            if total_years >= 6:
                return 1.0
            if total_years >= 4:
                return 0.8
            return 0.45

        if total_years >= 3:
            return 1.0
        if total_years >= 1:
            return 0.75
        return 0.55

    def _location_match(self, resume_text: str, job_location: str) -> float:
        if not job_location:
            return 0.8

        job_location_lower = job_location.lower()
        resume_lower = resume_text.lower()
        city = job_location_lower.split(",")[0].strip()

        if any(token in job_location_lower for token in ("remote", "hybrid", "home office")):
            return 1.0
        if city and city in resume_lower:
            return 1.0
        if "germany" in job_location_lower and any(token in resume_lower for token in ("berlin", "hamburg", "munich", "köln", "cologne", "germany", "deutschland")):
            return 0.85
        return 0.65

    def _extract_job_skills(self, job_data: dict[str, Any]) -> set[str]:
        base = self._normalize_set(job_data.get("keywords", []))
        body = f"{job_data.get('title', '')} {job_data.get('description', '')} {job_data.get('requirements', '')}".lower()
        for pattern in self.job_skill_patterns:
            base.update(self._normalize_token(match) for match in re.findall(pattern, body, flags=re.IGNORECASE))
        return {skill for skill in base if skill}

    def _tokens(self, text: str) -> list[str]:
        tokens = re.findall(r"[A-Za-zäöüÄÖÜß\+\.]{2,}", text.lower())
        normalized = [self._normalize_token(token) for token in tokens]
        return [token for token in normalized if token and token not in GERMAN_STOP_WORDS]

    def _normalize_set(self, values: list[str]) -> set[str]:
        return {self._normalize_token(value) for value in values if self._normalize_token(value)}

    def _normalize_token(self, value: str) -> str:
        token = value.strip().lower()
        token = token.replace("node.js", "nodejs")
        token = re.sub(r"\s+", " ", token)
        token = self.skill_aliases.get(token, token)
        return token

    def _estimate_years(self, experiences: list[dict[str, str]]) -> float:
        years = 0.0
        for experience in experiences:
            duration = str(experience.get("duration", ""))
            years += self._duration_to_years(duration)
        if years <= 0:
            years = len(experiences) * 1.8
        return years

    def _duration_to_years(self, duration: str) -> float:
        current_year = datetime.now(timezone.utc).year
        duration = duration.lower().replace("present", str(current_year)).replace("heute", str(current_year))
        match = re.search(r"(20\d{2})\s*[-–]\s*(20\d{2})", duration)
        if match:
            start = int(match.group(1))
            end = int(match.group(2))
            if end >= start:
                return float(end - start + 1)
        single = re.search(r"(\d+)\s*\+?\s*(?:years|year|jahre|jahr)", duration)
        if single:
            return float(single.group(1))
        return 0.0

    def _cosine_similarity(self, a: Counter, b: Counter) -> float:
        if not a or not b:
            return 0.0
        keys = set(a) | set(b)
        dot = sum(a[k] * b[k] for k in keys)
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
