from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from collections import Counter

try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

try:
    import PyPDF2
except Exception:  # pragma: no cover
    PyPDF2 = None

try:
    import docx
except Exception:  # pragma: no cover
    docx = None

try:
    import spacy
except Exception:  # pragma: no cover
    spacy = None


GERMAN_STOP_WORDS = {
    "und",
    "oder",
    "die",
    "der",
    "das",
    "ein",
    "eine",
    "mit",
    "auf",
    "im",
    "in",
    "zu",
    "von",
    "für",
}


class ResumeParser:
    def __init__(self, load_nlp: bool = True):
        self.nlp = None
        if load_nlp and spacy is not None:
            try:
                self.nlp = spacy.load("de_core_news_sm")
            except Exception:
                self.nlp = spacy.blank("de")

        self.skill_patterns = [
            r"\b(python|java|javascript|typescript|c\+\+|sql|scala|go|rust)\b",
            r"\b(django|flask|fastapi|react|vue|angular|spring|tensorflow|pytorch)\b",
            r"\b(aws|azure|gcp|docker|kubernetes|terraform)\b",
            r"\b(pandas|numpy|spark|hadoop|kafka|airflow|dbt)\b",
            r"\b(postgresql|mysql|mongodb|redis|elasticsearch|cassandra)\b",
            r"\b(git|jenkins|jira|tableau|power bi|excel)\b",
        ]

    def parse_file(self, file_path: str) -> dict[str, Any]:
        suffix = Path(file_path).suffix.lower()
        if suffix == ".pdf":
            raw_text = self._read_pdf(file_path)
        elif suffix == ".docx":
            raw_text = self._read_docx(file_path)
        else:
            raw_text = Path(file_path).read_text(encoding="utf-8", errors="ignore")

        return {
            "raw_text": raw_text,
            "skills": self._extract_skills(raw_text),
            "experience": self._extract_experience(raw_text),
            "education": self._extract_education(raw_text),
            "keywords": self._extract_keywords(raw_text),
        }

    def _read_pdf(self, file_path: str) -> str:
        texts: list[str] = []
        if pdfplumber is not None:
            try:
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        texts.append(page.extract_text() or "")
                if any(t.strip() for t in texts):
                    return "\n".join(texts)
            except Exception:
                texts = []

        if PdfReader is not None:
            with open(file_path, "rb") as handle:
                pdf = PdfReader(handle)
                for page in pdf.pages:
                    texts.append(page.extract_text() or "")
            return "\n".join(texts)

        if PyPDF2 is not None:
            with open(file_path, "rb") as handle:
                pdf = PyPDF2.PdfReader(handle)
                for page in pdf.pages:
                    texts.append(page.extract_text() or "")
        return "\n".join(texts)

    def _read_docx(self, file_path: str) -> str:
        if docx is None:
            return ""
        document = docx.Document(file_path)
        return "\n".join(paragraph.text for paragraph in document.paragraphs)

    def _extract_skills(self, text: str) -> list[str]:
        text_lower = text.lower()
        skills: set[str] = set()

        for pattern in self.skill_patterns:
            skills.update(re.findall(pattern, text_lower, flags=re.IGNORECASE))

        if self.nlp is not None and text.strip():
            doc = self.nlp(text)
            for ent in getattr(doc, "ents", []):
                if ent.label_ in {"ORG", "PRODUCT"} and len(ent.text) <= 40:
                    skills.add(ent.text.lower().strip())

        return sorted(s for s in skills if s)

    def _extract_experience(self, text: str) -> list[dict[str, str]]:
        exp_pattern = re.compile(
            r"([A-Z][A-Za-zäöüÄÖÜß\s]+(?:Engineer|Developer|Analyst|Manager))\s+(?:bei|at)\s+([^\n\(]+)\s*\((\d{4}\s*[-–]\s*(?:\d{4}|present|heute))\)",
            re.IGNORECASE,
        )
        experiences = []
        for title, company, duration in exp_pattern.findall(text):
            experiences.append(
                {
                    "title": title.strip(),
                    "company": company.strip(),
                    "duration": duration.strip(),
                }
            )
        return experiences

    def _extract_education(self, text: str) -> list[dict[str, str]]:
        edu_pattern = re.compile(
            r"(Bachelor|Master|PhD|B\.Sc|M\.Sc|Dr\.)[^\n]*?([A-Z][A-Za-zäöüÄÖÜß\s]+(?:University|Universität|Institut|College))[^\n]*?(\d{4}\s*[-–]\s*\d{4})",
            re.IGNORECASE,
        )
        education = []
        for degree, institution, year in edu_pattern.findall(text):
            education.append(
                {
                    "degree": degree.strip(),
                    "institution": institution.strip(),
                    "year": year.strip(),
                }
            )
        return education

    def _extract_keywords(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        tokens = re.findall(r"[A-Za-zäöüÄÖÜß]{3,}", text.lower())
        filtered = [t for t in tokens if t not in GERMAN_STOP_WORDS]
        freq = Counter(filtered)
        return [token for token, _ in freq.most_common(50)]
