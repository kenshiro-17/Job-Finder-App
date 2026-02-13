from __future__ import annotations

import asyncio
import contextlib
import random
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except Exception:  # pragma: no cover
    def retry(*_args, **_kwargs):  # type: ignore
        def decorator(func):
            return func

        return decorator

    def stop_after_attempt(_attempts):  # type: ignore
        return None

    def wait_exponential(**_kwargs):  # type: ignore
        return None

from app.config import settings
from app.services.resume_parser import ResumeParser

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None


class JobScraper:
    def __init__(self) -> None:
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        ]
        self.parser = ResumeParser(load_nlp=False)

    async def search(self, keywords: str, location: str, filters: dict[str, Any], sources: list[str]) -> list[dict[str, Any]]:
        tasks = []
        if "indeed" in sources:
            tasks.append(self._scrape_indeed_web(keywords, location, filters))
        if "stepstone" in sources:
            tasks.append(self._scrape_stepstone(keywords, location, filters))
        if "linkedin" in sources:
            tasks.append(self._scrape_linkedin_guest(keywords, location, filters))
        if "arbeitnow" in sources:
            tasks.append(self._scrape_arbeitnow(keywords, location, filters))
        if "berlinstartupjobs" in sources:
            tasks.append(self._scrape_berlinstartupjobs(keywords, location, filters))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        jobs: list[dict[str, Any]] = []
        for result in results:
            if isinstance(result, list):
                jobs.extend(result)

        return self._deduplicate_jobs(jobs)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _scrape_indeed_web(self, keywords: str, location: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        query = quote_plus(keywords)
        city = quote_plus(location)
        jobs: list[dict[str, Any]] = []
        page_size = 10
        max_jobs = max(10, settings.max_jobs_per_source)
        max_pages = max(1, settings.max_scrape_pages)
        base_urls = ("https://de.indeed.com", "https://www.indeed.com")

        async with httpx.AsyncClient(timeout=15) as client:
            for base_url in base_urls:
                for page_idx, start in enumerate(range(0, max_jobs, page_size)):
                    if page_idx >= max_pages:
                        break
                    url = f"{base_url}/jobs?q={query}&l={city}&sort=date&start={start}"
                    response = await client.get(url, headers={"User-Agent": self._get_random_ua()})
                    if response.status_code >= 400:
                        break

                    soup = BeautifulSoup(response.text, "html.parser")
                    cards = self._collect_indeed_cards(soup)
                    if not cards:
                        break

                    for card in cards:
                        parsed = self._parse_indeed_card(card, base_url)
                        if parsed and self._matches_filters(parsed, filters):
                            jobs.append(parsed)
                        if len(jobs) >= max_jobs:
                            break

                    if len(jobs) >= max_jobs:
                        break
                    await asyncio.sleep(settings.scrape_delay_seconds)

                if jobs:
                    break

        return jobs

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _scrape_arbeitnow(self, keywords: str, location: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        max_jobs = max(20, settings.max_jobs_per_source)
        max_pages = max(1, settings.max_scrape_pages)

        async with httpx.AsyncClient(timeout=20) as client:
            for page in range(1, max_pages + 1):
                response = await client.get(
                    "https://www.arbeitnow.com/api/job-board-api",
                    params={"page": page},
                    headers={"User-Agent": self._get_random_ua()},
                )
                if response.status_code >= 400:
                    break
                payload = response.json()
                items = payload.get("data", [])
                if not items:
                    break

                for item in items:
                    parsed = self._parse_arbeitnow_item(item, keywords, location)
                    if parsed and self._matches_filters(parsed, filters):
                        jobs.append(parsed)
                    if len(jobs) >= max_jobs:
                        break

                if len(jobs) >= max_jobs:
                    break
                await asyncio.sleep(settings.scrape_delay_seconds)

        return jobs

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _scrape_berlinstartupjobs(self, keywords: str, location: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        max_jobs = max(15, settings.max_jobs_per_source)
        max_pages = max(1, settings.max_scrape_pages)

        async with httpx.AsyncClient(timeout=20) as client:
            for page in range(1, max_pages + 1):
                response = await client.get(
                    "https://berlinstartupjobs.com/jobs/",
                    params={
                        "search_keywords": keywords,
                        "search_location": location,
                        "paged": page,
                    },
                    headers={"User-Agent": self._get_random_ua()},
                )
                if response.status_code >= 400:
                    break
                soup = BeautifulSoup(response.text, "html.parser")
                cards = soup.select("li.job_listing, article.job-listing, div.job-listing")
                if not cards:
                    break

                for card in cards:
                    parsed = self._parse_berlinstartupjobs_card(card)
                    if parsed and self._matches_filters(parsed, filters):
                        jobs.append(parsed)
                    if len(jobs) >= max_jobs:
                        break

                if len(jobs) >= max_jobs:
                    break
                await asyncio.sleep(settings.scrape_delay_seconds)

        return jobs

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _scrape_linkedin_guest(self, keywords: str, location: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        page_size = 25
        max_jobs = max(15, settings.max_jobs_per_source)
        max_pages = max(1, settings.max_scrape_pages)

        async with httpx.AsyncClient(timeout=20) as client:
            for page_idx, start in enumerate(range(0, max_jobs, page_size)):
                if page_idx >= max_pages:
                    break
                url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                params = {
                    "keywords": keywords,
                    "location": location,
                    "start": start,
                }
                response = await client.get(url, params=params, headers={"User-Agent": self._get_random_ua()})
                if response.status_code >= 400:
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                cards = soup.find_all("li")
                if not cards:
                    break

                for card in cards:
                    parsed = self._parse_linkedin_card(card)
                    if parsed and self._matches_filters(parsed, filters):
                        jobs.append(parsed)
                    if len(jobs) >= max_jobs:
                        break

                if len(jobs) >= max_jobs:
                    break
                await asyncio.sleep(settings.scrape_delay_seconds)

        return jobs

    async def _scrape_stepstone(self, keywords: str, location: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        if async_playwright is None:
            return []

        jobs: list[dict[str, Any]] = []
        max_jobs = max(10, settings.max_jobs_per_source)
        max_pages = max(1, settings.max_scrape_pages)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=self._get_random_ua(), viewport={"width": 1440, "height": 900})
            page = await context.new_page()
            try:
                for page_num in range(1, max_pages + 1):
                    search_url = (
                        f"https://www.stepstone.de/jobs/{quote_plus(keywords)}"
                        f"?where={quote_plus(location)}&page={page_num}&sort=2"
                    )
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(1200)

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    cards = soup.find_all("article")
                    if not cards:
                        break

                    for card in cards:
                        parsed = self._parse_stepstone_card(card)
                        if parsed and self._matches_filters(parsed, filters):
                            jobs.append(parsed)
                        if len(jobs) >= max_jobs:
                            break

                    if len(jobs) >= max_jobs:
                        break
                    await asyncio.sleep(settings.scrape_delay_seconds)
            finally:
                await browser.close()

        return jobs

    def _collect_indeed_cards(self, soup: BeautifulSoup) -> list[Any]:
        cards = soup.find_all("div", class_=re.compile("job_seen_beacon|cardOutline|jobsearch-SerpJobCard"))
        if cards:
            return cards
        cards = soup.select("a.tapItem[href], a.jcs-JobTitle[href], h2.jobTitle a[href], a[data-jk][href]")
        # Deduplicate nodes from overlapping selectors.
        unique_cards: list[Any] = []
        seen: set[int] = set()
        for node in cards:
            node_id = id(node)
            if node_id in seen:
                continue
            seen.add(node_id)
            unique_cards.append(node)
        return unique_cards

    def _parse_indeed_card(self, card: Any, base_url: str = "https://de.indeed.com") -> dict[str, Any] | None:
        container = card
        link_el = None
        if getattr(card, "name", "") == "a":
            link_el = card
            container = (
                card.find_parent("div", class_=re.compile("job_seen_beacon|cardOutline|jobsearch-SerpJobCard"))
                or card.find_parent("li")
                or card
            )

        title_el = (
            container.find("h2", class_=re.compile("jobTitle"))
            if hasattr(container, "find")
            else None
        )
        link_el = link_el or (
            container.find("a", href=True, attrs={"data-jk": True})
            or container.find("a", href=True, class_=re.compile("jcs-JobTitle|tapItem"))
            or (title_el.find("a", href=True) if title_el else None)
            or container.find("a", href=True)
        )
        company_el = (
            container.find("span", attrs={"data-testid": "company-name"})
            or container.find("span", class_=re.compile("companyName"))
            or container.find("span", attrs={"data-testid": re.compile("company", re.I)})
        )
        location_el = (
            container.find("div", attrs={"data-testid": "text-location"})
            or container.find("div", class_=re.compile("companyLocation"))
            or container.find("div", attrs={"data-testid": re.compile("location", re.I)})
            or container.find("span", class_=re.compile("location", re.I))
        )
        description_el = (
            container.find("div", class_=re.compile("job-snippet"))
            or container.find("div", attrs={"data-testid": re.compile("snippet", re.I)})
            or container.find("ul")
        )
        posted_el = container.find("span", class_=re.compile("date")) or container.find("time")
        if not title_el or not link_el:
            # Some new Indeed templates only expose title text directly on the anchor.
            if not link_el:
                return None

        title_text = (
            title_el.get_text(" ", strip=True)[:500]
            if title_el
            else link_el.get_text(" ", strip=True)[:500]
        )
        if not title_text:
            return None

        job_id = (
            container.get("data-jk")
            or link_el.get("data-jk")
            or self._indeed_job_id_from_href(link_el.get("href", ""))
        )
        url = self._normalize_url(link_el.get("href", ""), base_url)
        if not url and job_id:
            url = f"https://de.indeed.com/viewjob?jk={job_id}"
        if "viewjob" not in url and "rc/clk" not in url and "pagead/clk" not in url and job_id:
            url = f"https://de.indeed.com/viewjob?jk={job_id}"

        description = " ".join(description_el.stripped_strings) if description_el else ""
        keywords = self.parser._extract_skills(description) + self.parser._extract_keywords(description)[:10]

        return {
            "source": "indeed",
            "external_job_id": str(job_id)[:255] or f"indeed-{random.randint(1000, 9999)}",
            "title": title_text,
            "company": (company_el.get_text(" ", strip=True) if company_el else "Unknown")[:255],
            "location": (location_el.get_text(" ", strip=True) if location_el else "Unknown")[:255],
            "description": description[:2000],
            "requirements": description[:1000],
            "url": url[:1000],
            "posted_date": self._parse_relative_date(
                posted_el.get("datetime") if posted_el and posted_el.has_attr("datetime") else (
                    posted_el.get_text(" ", strip=True) if posted_el else "heute"
                )
            ),
            "keywords": list(dict.fromkeys(k.lower() for k in keywords if k)),
        }

    def _parse_stepstone_card(self, card: Any) -> dict[str, Any] | None:
        title_el = card.find(["h2", "h3"])
        link_el = self._pick_stepstone_job_link(card)
        company_el = card.find(attrs={"data-at": "job-item-company-name"})
        location_el = card.find(attrs={"data-at": "job-item-location"})
        snippet_el = card.find("p")

        if not title_el or not link_el:
            return None

        url = self._normalize_url(link_el.get("href", ""), "https://www.stepstone.de")
        if not url:
            return None

        description = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        keywords = self.parser._extract_skills(description) + self.parser._extract_keywords(description)[:10]

        return {
            "source": "stepstone",
            "external_job_id": (self._stepstone_external_id_from_url(url) or link_el.get("data-genesis-element") or f"stepstone-{random.randint(1000, 9999)}")[:255],
            "title": title_el.get_text(" ", strip=True)[:500],
            "company": (company_el.get_text(" ", strip=True) if company_el else "Unknown")[:255],
            "location": (location_el.get_text(" ", strip=True) if location_el else "Unknown")[:255],
            "description": description[:2000],
            "requirements": description[:1000],
            "url": url[:1000],
            "posted_date": date.today(),
            "keywords": list(dict.fromkeys(k.lower() for k in keywords if k)),
        }

    def _deduplicate_jobs(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        deduplicated: list[dict[str, Any]] = []
        for job in jobs:
            key = (
                f"{job.get('title', '').lower()}::"
                f"{job.get('company', '').lower()}::"
                f"{job.get('location', '').lower()}"
            )
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(job)
        return deduplicated

    def _parse_linkedin_card(self, card: Any) -> dict[str, Any] | None:
        title_el = card.find("h3", class_=re.compile("base-search-card__title|base-card__title")) or card.find("h3")
        company_el = card.find("h4", class_=re.compile("base-search-card__subtitle|base-card__subtitle")) or card.find("h4")
        location_el = card.find("span", class_=re.compile("job-search-card__location|job-search-card__location"))
        link_el = card.find("a", href=True, class_=re.compile("base-card__full-link|base-card__link")) or card.find("a", href=True)
        time_el = card.find("time")

        if not title_el or not link_el:
            return None

        url = self._normalize_url(link_el.get("href", ""), "https://www.linkedin.com")
        job_id = self._linkedin_job_id_from_url(url)
        if job_id:
            url = f"https://www.linkedin.com/jobs/view/{job_id}/"

        title = title_el.get_text(" ", strip=True)
        company = company_el.get_text(" ", strip=True) if company_el else "Unknown"
        location = location_el.get_text(" ", strip=True) if location_el else "Unknown"
        posted_raw = time_el.get("datetime") if time_el and time_el.has_attr("datetime") else (time_el.get_text(" ", strip=True) if time_el else "")

        base_text = f"{title} {company} {location}"
        keywords = self.parser._extract_skills(base_text) + self.parser._extract_keywords(base_text)[:10]

        return {
            "source": "linkedin",
            "external_job_id": (job_id or f"linkedin-{random.randint(1000, 9999)}")[:255],
            "title": title[:500],
            "company": company[:255],
            "location": location[:255],
            "description": "",
            "requirements": "",
            "url": url[:1000],
            "posted_date": self._parse_relative_date(posted_raw),
            "keywords": list(dict.fromkeys(k.lower() for k in keywords if k)),
        }

    def _parse_arbeitnow_item(self, item: dict[str, Any], keywords: str, location: str) -> dict[str, Any] | None:
        title = (item.get("title") or "").strip()
        if not title:
            return None
        company = (item.get("company_name") or "Unknown").strip()
        loc = (item.get("location") or "").strip()
        if location and location.lower().find("germany") >= 0:
            if loc and "germany" not in loc.lower() and "berlin" not in loc.lower() and "remote" not in loc.lower():
                return None
        combined = f"{title} {company} {loc}".lower()
        if keywords:
            keyword_tokens = [token.strip().lower() for token in keywords.split() if token.strip()]
            if keyword_tokens and not any(token in combined for token in keyword_tokens):
                return None

        description_html = item.get("description") or ""
        description = BeautifulSoup(description_html, "html.parser").get_text(" ", strip=True)
        tags = item.get("tags") or []
        url = (item.get("url") or item.get("slug") or "").strip()
        if url and not url.startswith("http"):
            url = f"https://www.arbeitnow.com/jobs/{url.strip('/')}"
        if not url:
            return None

        created_at = item.get("created_at") or ""
        posted_date = None
        if created_at:
            with contextlib.suppress(ValueError):
                posted_date = datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()

        keywords_list = tags + self.parser._extract_skills(description) + self.parser._extract_keywords(description)[:12]

        return {
            "source": "arbeitnow",
            "external_job_id": str(item.get("slug") or item.get("id") or f"arbeitnow-{random.randint(1000, 9999)}")[:255],
            "title": title[:500],
            "company": company[:255],
            "location": (loc or "Germany")[:255],
            "description": description[:2000],
            "requirements": description[:1000],
            "url": url[:1000],
            "posted_date": posted_date,
            "keywords": list(dict.fromkeys(str(k).lower() for k in keywords_list if k)),
        }

    def _parse_berlinstartupjobs_card(self, card: Any) -> dict[str, Any] | None:
        link_el = card.select_one("a[href]")
        title_el = card.select_one("h3, h2, .job_listing-title")
        company_el = card.select_one(".company, .job_listing-company, .job_listing-company strong")
        location_el = card.select_one(".location, .job_listing-location")
        date_el = card.select_one("time, .date")
        desc_el = card.select_one(".job_listing-description, .excerpt, p")

        if not link_el:
            return None
        title = (title_el.get_text(" ", strip=True) if title_el else link_el.get_text(" ", strip=True)).strip()
        if not title:
            return None

        url = self._normalize_url(link_el.get("href", ""), "https://berlinstartupjobs.com")
        if not url:
            return None
        external = urlparse(url).path.strip("/").split("/")[-1]
        company = company_el.get_text(" ", strip=True) if company_el else "Unknown"
        location = location_el.get_text(" ", strip=True) if location_el else "Berlin, Germany"
        description = desc_el.get_text(" ", strip=True) if desc_el else ""
        posted_raw = date_el.get("datetime") if date_el and date_el.has_attr("datetime") else (date_el.get_text(" ", strip=True) if date_el else "")
        keywords = self.parser._extract_skills(description) + self.parser._extract_keywords(f"{title} {description}")[:12]

        return {
            "source": "berlinstartupjobs",
            "external_job_id": str(external or f"berlinstartupjobs-{random.randint(1000, 9999)}")[:255],
            "title": title[:500],
            "company": company[:255],
            "location": location[:255],
            "description": description[:2000],
            "requirements": description[:1000],
            "url": url[:1000],
            "posted_date": self._parse_relative_date(posted_raw),
            "keywords": list(dict.fromkeys(k.lower() for k in keywords if k)),
        }

    def _matches_filters(self, job: dict[str, Any], filters: dict[str, Any]) -> bool:
        posted_date = job.get("posted_date")
        if posted_date and isinstance(posted_date, date):
            oldest_allowed = date.today() - timedelta(days=settings.max_job_age_days)
            if posted_date < oldest_allowed:
                return False

        salary_min = filters.get("salary_min")
        if salary_min and job.get("salary_min") and job["salary_min"] < salary_min:
            return False

        remote_values = filters.get("remote") or []
        if remote_values and job.get("remote_type") and job["remote_type"] not in remote_values:
            return False

        return True

    def _parse_relative_date(self, value: str | None) -> date | None:
        if not value:
            return None
        v = value.lower().strip()
        iso_match = re.search(r"(20\d{2}-\d{2}-\d{2})", v)
        if iso_match:
            with contextlib.suppress(ValueError):
                return date.fromisoformat(iso_match.group(1))
        if "heute" in v or "today" in v:
            return date.today()
        if "gestern" in v or "yesterday" in v:
            return date.today() - timedelta(days=1)
        if any(part in v for part in ("hour", "stunden", "minute", "minuten", "just now")):
            return date.today()
        days_match = re.search(r"(\d+)\s*(tag|tage|day|days)", v)
        if days_match:
            return date.today() - timedelta(days=int(days_match.group(1)))
        weeks_match = re.search(r"(\d+)\s*(woche|wochen|week|weeks)", v)
        if weeks_match:
            return date.today() - timedelta(days=int(weeks_match.group(1)) * 7)
        return None

    def _get_random_ua(self) -> str:
        return random.choice(self.user_agents)

    def _normalize_url(self, href: str, base_url: str) -> str:
        if not href:
            return ""
        href = href.strip()
        if href.startswith("//"):
            return f"https:{href}"
        if href.startswith("http://") or href.startswith("https://"):
            return href
        if href.startswith("?"):
            return f"{base_url}{href}"
        return urljoin(f"{base_url}/", href)

    def _pick_stepstone_job_link(self, card: Any) -> Any | None:
        anchors = card.find_all("a", href=True)
        if not anchors:
            return None

        preferred_patterns = (
            "/stellenangebote",
            "/job/",
        )
        for anchor in anchors:
            href = (anchor.get("href") or "").lower()
            if any(pattern in href for pattern in preferred_patterns):
                return anchor
        return anchors[0]

    def _stepstone_external_id_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        if not parsed.path:
            return ""
        slug = parsed.path.strip("/").split("/")[-1]
        return slug[:255]

    def _linkedin_job_id_from_url(self, url: str) -> str:
        if not url:
            return ""
        match = re.search(r"/jobs/view/(\d+)", url)
        if match:
            return match.group(1)
        slug_match = re.search(r"/jobs/view/[^/?#]*-(\d+)", url)
        if slug_match:
            return slug_match.group(1)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        for key in ("currentJobId", "jobId", "trkJobId"):
            values = query.get(key)
            if values and values[0].isdigit():
                return values[0]
        return ""

    def _indeed_job_id_from_href(self, href: str) -> str:
        if not href:
            return ""
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        for key in ("jk", "vjk"):
            values = query.get(key)
            if values and values[0]:
                return values[0]
        direct = re.search(r"[?&](?:jk|vjk)=([A-Za-z0-9_-]+)", href)
        if direct:
            return direct.group(1)
        return ""
