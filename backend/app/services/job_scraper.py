from __future__ import annotations

import asyncio
import contextlib
import html
import random
import re
from datetime import date, datetime, timedelta, timezone
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
        tasks: list[asyncio.Future | asyncio.Task | Any] = []
        source_timeout = 18.0
        if "indeed" in sources:
            tasks.append(asyncio.wait_for(self._scrape_indeed_web(keywords, location, filters), timeout=source_timeout))
        if "stepstone" in sources:
            tasks.append(asyncio.wait_for(self._scrape_stepstone(keywords, location, filters), timeout=source_timeout))
        if "linkedin" in sources:
            tasks.append(asyncio.wait_for(self._scrape_linkedin_guest(keywords, location, filters), timeout=source_timeout))
        if "arbeitnow" in sources:
            tasks.append(asyncio.wait_for(self._scrape_arbeitnow(keywords, location, filters), timeout=source_timeout))
        if "berlinstartupjobs" in sources:
            tasks.append(asyncio.wait_for(self._scrape_berlinstartupjobs(keywords, location, filters), timeout=source_timeout))

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
                    if self._looks_like_cloudflare_challenge(response.text):
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

        if jobs:
            return jobs
        # Keep fallback lightweight to avoid long tail latency in multi-source searches.
        return await self._scrape_indeed_search_fallback(keywords, location, filters)

    async def _scrape_indeed_playwright(self, keywords: str, location: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        if async_playwright is None:
            return []

        page_size = 10
        max_jobs = max(10, settings.max_jobs_per_source)
        max_pages = max(1, settings.max_scrape_pages)
        jobs: list[dict[str, Any]] = []
        base_urls = ("https://de.indeed.com", "https://www.indeed.com")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self._get_random_ua(),
                viewport={"width": 1440, "height": 900},
                locale="de-DE",
            )
            page = await context.new_page()
            try:
                for base_url in base_urls:
                    for page_idx, start in enumerate(range(0, max_jobs, page_size)):
                        if page_idx >= max_pages:
                            break
                        url = f"{base_url}/jobs?q={quote_plus(keywords)}&l={quote_plus(location)}&sort=date&start={start}"
                        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                        await page.wait_for_timeout(2500)

                        html_content = await page.content()
                        if self._looks_like_cloudflare_challenge(html_content):
                            await page.wait_for_timeout(4500)
                            html_content = await page.content()
                            if self._looks_like_cloudflare_challenge(html_content):
                                continue

                        soup = BeautifulSoup(html_content, "html.parser")
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
            finally:
                await browser.close()

        return jobs

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
    async def _scrape_indeed_search_fallback(
        self,
        keywords: str,
        location: str,
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        max_jobs = max(10, settings.max_jobs_per_source)
        max_pages = max(1, min(settings.max_scrape_pages, 2))

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            for page in range(max_pages):
                response = await client.get(
                    "https://duckduckgo.com/html/",
                    params={
                        "q": f"site:de.indeed.com/viewjob {keywords} {location}",
                        "s": page * 30,
                    },
                    headers={"User-Agent": self._get_random_ua()},
                )
                if response.status_code >= 400:
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                results = soup.select(".result")
                if not results:
                    break

                for result in results:
                    link_el = result.select_one("a.result__a[href], h2.result__title a[href], a[href]")
                    if not link_el:
                        continue
                    raw_href = link_el.get("href", "").strip()
                    resolved = self._resolve_search_result_url(raw_href)
                    if "indeed." not in resolved.lower():
                        continue

                    job_id = self._indeed_job_id_from_href(resolved)
                    canonical = (
                        f"https://de.indeed.com/viewjob?jk={job_id}"
                        if job_id
                        else resolved
                    )
                    unique_key = job_id or canonical
                    if not unique_key or unique_key in seen:
                        continue
                    seen.add(unique_key)

                    title = html.unescape(link_el.get_text(" ", strip=True))[:500]
                    snippet_el = result.select_one(".result__snippet")
                    snippet = html.unescape(snippet_el.get_text(" ", strip=True)) if snippet_el else ""
                    if not title:
                        continue

                    combined_text = f"{title} {snippet}"
                    keywords_list = self.parser._extract_skills(combined_text) + self.parser._extract_keywords(combined_text)[:10]
                    parsed = {
                        "source": "indeed",
                        "external_job_id": str(job_id or f"indeed-{random.randint(1000, 9999)}")[:255],
                        "title": title,
                        "company": "Unknown",
                        "location": location[:255] if location else "Germany",
                        "description": snippet[:2000],
                        "requirements": snippet[:1000],
                        "url": canonical[:1000],
                        "posted_date": date.today(),
                        "keywords": list(dict.fromkeys(k.lower() for k in keywords_list if k)),
                    }
                    if self._matches_filters(parsed, filters):
                        jobs.append(parsed)
                    if len(jobs) >= max_jobs:
                        break

                if len(jobs) >= max_jobs:
                    break
                await asyncio.sleep(settings.scrape_delay_seconds)

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
        keyword_tokens = [token for token in re.split(r"\W+", keywords.lower()) if token]

        candidate_urls = [
            "https://berlinstartupjobs.com/",
            "https://berlinstartupjobs.com/engineering/",
        ]
        for token in keyword_tokens[:3]:
            if len(token) > 2:
                candidate_urls.append(f"https://berlinstartupjobs.com/skill-areas/{token}/")
        seen_urls: set[str] = set()
        candidate_urls = [url for url in candidate_urls if not (url in seen_urls or seen_urls.add(url))]

        async with httpx.AsyncClient(timeout=20) as client:
            for base_url in candidate_urls:
                for page in range(1, max_pages + 1):
                    page_url = base_url if page == 1 else f"{base_url.rstrip('/')}/page/{page}/"
                    response = await client.get(page_url, headers={"User-Agent": self._get_random_ua()})
                    if response.status_code >= 400:
                        break
                    if "page not found" in response.text.lower():
                        break

                    soup = BeautifulSoup(response.text, "html.parser")
                    cards = soup.select("li.bjs-jlis, li.job_listing, article.job-listing, div.job-listing")
                    if not cards:
                        break

                    for card in cards:
                        parsed = self._parse_berlinstartupjobs_card(card)
                        if not parsed:
                            continue
                        if keyword_tokens:
                            haystack = f"{parsed.get('title', '')} {parsed.get('company', '')} {parsed.get('description', '')}".lower()
                            if not any(token in haystack for token in keyword_tokens):
                                continue
                        if self._matches_filters(parsed, filters):
                            jobs.append(parsed)
                        if len(jobs) >= max_jobs:
                            break

                    if len(jobs) >= max_jobs:
                        break
                    await asyncio.sleep(settings.scrape_delay_seconds)

                if len(jobs) >= max_jobs:
                    break

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
        jobs: list[dict[str, Any]] = []
        max_jobs = max(10, settings.max_jobs_per_source)
        max_pages = max(1, settings.max_scrape_pages)
        keyword_slug = self._slugify_for_path(keywords)

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for page_num in range(1, max_pages + 1):
                urls = [
                    f"https://www.stepstone.de/jobs/{keyword_slug}?where={quote_plus(location)}&page={page_num}&sort=2",
                    f"https://www.stepstone.de/jobs/{quote_plus(keywords)}?where={quote_plus(location)}&page={page_num}&sort=2",
                ]
                response = None
                for search_url in urls:
                    candidate = await client.get(search_url, headers={"User-Agent": self._get_random_ua()})
                    if candidate.status_code < 400:
                        response = candidate
                        break
                if response is None:
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                cards = soup.select("article[data-testid='job-item']") or soup.find_all("article")
                if not cards:
                    break

                parsed_on_page = 0
                for card in cards:
                    parsed = self._parse_stepstone_card(card, default_location=location)
                    if parsed and self._matches_filters(parsed, filters):
                        jobs.append(parsed)
                        parsed_on_page += 1
                    if len(jobs) >= max_jobs:
                        break

                if len(jobs) >= max_jobs:
                    break
                if page_num == 1 and parsed_on_page == 0:
                    break
                await asyncio.sleep(settings.scrape_delay_seconds)

        if jobs:
            return jobs
        return await self._scrape_stepstone_playwright(keywords, location, filters)

    async def _scrape_stepstone_playwright(
        self,
        keywords: str,
        location: str,
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if async_playwright is None:
            return []

        jobs: list[dict[str, Any]] = []
        max_jobs = max(10, settings.max_jobs_per_source)
        max_pages = max(1, settings.max_scrape_pages)
        keyword_slug = self._slugify_for_path(keywords)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=self._get_random_ua(), viewport={"width": 1440, "height": 900})
            page = await context.new_page()
            try:
                for page_num in range(1, max_pages + 1):
                    search_url = (
                        f"https://www.stepstone.de/jobs/{keyword_slug}"
                        f"?where={quote_plus(location)}&page={page_num}&sort=2"
                    )
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                    await page.wait_for_timeout(1500)

                    html_content = await page.content()
                    soup = BeautifulSoup(html_content, "html.parser")
                    cards = soup.select("article[data-testid='job-item']") or soup.find_all("article")
                    if not cards:
                        break

                    for card in cards:
                        parsed = self._parse_stepstone_card(card, default_location=location)
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
            "external_job_id": (str(job_id).strip() if job_id else f"indeed-{random.randint(1000, 9999)}")[:255],
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

    def _parse_stepstone_card(self, card: Any, default_location: str | None = None) -> dict[str, Any] | None:
        if hasattr(card, "find_all"):
            for noisy in card.find_all(["style", "script"]):
                noisy.decompose()

        title_link_el = None
        if hasattr(card, "select_one"):
            title_link_el = card.select_one("a[data-testid='job-item-title'][href]")

        title_el = title_link_el or card.find(["h2", "h3"])
        link_el = title_link_el or self._pick_stepstone_job_link(card)
        company_el = card.find(attrs={"data-at": "job-item-company-name"})
        location_el = card.find(attrs={"data-at": "job-item-location"})
        snippet_el = card.find(attrs={"data-at": re.compile(r"job-item-(teaser|description)", re.I)}) or card.find("p")
        posted_el = card.find("time")

        if not title_el or not link_el:
            return None

        url = self._normalize_url(link_el.get("href", ""), "https://www.stepstone.de")
        if not url:
            return None

        title_text = title_el.get_text(" ", strip=True)
        title_text = html.unescape(re.sub(r"\s+", " ", title_text)).strip()
        if not title_text:
            return None

        description = html.unescape(snippet_el.get_text(" ", strip=True)) if snippet_el else ""
        company_text = company_el.get_text(" ", strip=True) if company_el else "Unknown"
        location_text = location_el.get_text(" ", strip=True) if location_el else (default_location or "Germany")
        posted_raw = posted_el.get("datetime") if posted_el and posted_el.has_attr("datetime") else (posted_el.get_text(" ", strip=True) if posted_el else "today")
        keywords = self.parser._extract_skills(description) + self.parser._extract_keywords(f"{title_text} {description}")[:10]

        return {
            "source": "stepstone",
            "external_job_id": (
                self._stepstone_external_id_from_url(url)
                or link_el.get("data-genesis-element")
                or f"stepstone-{random.randint(1000, 9999)}"
            )[:255],
            "title": title_text[:500],
            "company": company_text[:255],
            "location": location_text[:255],
            "description": description[:2000],
            "requirements": description[:1000],
            "url": url[:1000],
            "posted_date": self._parse_relative_date(posted_raw) or date.today(),
            "keywords": list(dict.fromkeys(k.lower() for k in keywords if k)),
        }

    def _deduplicate_jobs(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        deduplicated: list[dict[str, Any]] = []
        for job in jobs:
            job = self._finalize_job_payload(job)
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
        location_lower = (location or "").lower().strip()
        requested_city = location_lower.split(",")[0].strip() if location_lower else ""
        loc_lower = loc.lower()
        if requested_city and requested_city not in ("germany", "deutschland"):
            if requested_city not in loc_lower and "remote" not in loc_lower:
                # If country-level scope was requested, keep wider Germany opportunities.
                if "germany" not in location_lower and "deutschland" not in location_lower:
                    return None
        description_html = item.get("description") or ""
        description = BeautifulSoup(description_html, "html.parser").get_text(" ", strip=True)
        tags = item.get("tags") or []
        combined = f"{title} {company} {loc} {description} {' '.join(str(tag) for tag in tags)}".lower()
        if keywords:
            keyword_tokens = [token.strip().lower() for token in keywords.split() if token.strip()]
            if keyword_tokens and not any(token in combined for token in keyword_tokens):
                return None

        url = (item.get("url") or item.get("slug") or "").strip()
        if url and not url.startswith("http"):
            url = f"https://www.arbeitnow.com/jobs/{url.strip('/')}"
        if not url:
            return None

        created_at = item.get("created_at")
        posted_date = None
        if isinstance(created_at, (int, float)):
            with contextlib.suppress(ValueError, OSError, OverflowError):
                posted_date = datetime.fromtimestamp(float(created_at), tz=timezone.utc).date()
        elif isinstance(created_at, str) and created_at:
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
        link_el = card.select_one("h4 a[href], h3 a[href], h2 a[href], a[href]")
        title_el = card.select_one("h4, h3, h2, .job_listing-title")
        company_el = card.select_one(".bjs-jlis__b, .company, .job_listing-company, .job_listing-company strong")
        location_el = card.select_one(".location, .job_listing-location")
        date_el = card.select_one("time, .date")
        desc_el = card.select_one(".job_listing-description, .excerpt, .bjs-jlis__featured, p")

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
        self._finalize_job_payload(job)

        posted_date = job.get("posted_date")
        if posted_date and isinstance(posted_date, date):
            oldest_allowed = date.today() - timedelta(days=settings.max_job_age_days)
            if posted_date < oldest_allowed:
                return False

        date_posted_filter = str(filters.get("date_posted") or "").strip().lower()
        if date_posted_filter and not self._passes_date_filter(posted_date, date_posted_filter):
            return False

        salary_min = filters.get("salary_min")
        if salary_min and job.get("salary_min") and job["salary_min"] < salary_min:
            return False

        location_contains = str(filters.get("location_contains") or "").strip().lower()
        if location_contains:
            job_location = str(job.get("location") or "").lower()
            if location_contains not in job_location:
                return False

        remote_values = [str(v).strip().lower() for v in ((filters.get("remote") or []) + (filters.get("work_mode") or [])) if str(v).strip()]
        if remote_values and (job.get("remote_type") or "").lower() not in remote_values:
            return False

        experience_values = [str(v).strip().lower() for v in (filters.get("experience_level") or []) if str(v).strip()]
        if experience_values and (job.get("experience_level") or "").lower() not in experience_values:
            return False

        return True

    def _finalize_job_payload(self, job: dict[str, Any]) -> dict[str, Any]:
        remote_type = self._infer_remote_type(job)
        if remote_type:
            job["remote_type"] = remote_type
        experience_level = self._infer_experience_level(job)
        if experience_level:
            job["experience_level"] = experience_level
        job_type = self._infer_job_type(job)
        if job_type:
            job["job_type"] = job_type
        return job

    def _normalize_remote_mode(self, value: str) -> str:
        token = value.lower().replace("_", " ").replace("-", " ").strip()
        if any(part in token for part in ("hybrid", "hybrid working")):
            return "hybrid"
        if any(part in token for part in ("remote", "home office", "work from home", "wfh", "fully distributed", "distributed")):
            return "remote"
        if any(part in token for part in ("on site", "onsite", "office", "vor ort", "onprem")):
            return "onsite"
        return ""

    def _infer_remote_type(self, job: dict[str, Any]) -> str:
        existing = str(job.get("remote_type") or "").strip()
        normalized_existing = self._normalize_remote_mode(existing)
        if normalized_existing:
            return normalized_existing
        haystack = " ".join(
            str(job.get(part) or "")
            for part in ("title", "location", "description", "requirements")
        ).lower()
        return self._normalize_remote_mode(haystack) or "onsite"

    def _normalize_experience_level(self, value: str) -> str:
        token = value.lower().strip()
        if any(part in token for part in ("intern", "internship", "praktikum", "graduate", "entry level", "entry-level", "trainee")):
            return "entry"
        if any(part in token for part in ("junior", "jr")):
            return "junior"
        if any(part in token for part in ("senior", "sr", "staff", "principal", "lead", "head of", "team lead")):
            if any(part in token for part in ("lead", "principal", "head of", "staff")):
                return "lead"
            return "senior"
        if any(part in token for part in ("mid", "intermediate", "experienced", "professional")):
            return "mid"
        return ""

    def _infer_experience_level(self, job: dict[str, Any]) -> str:
        existing = str(job.get("experience_level") or "").strip()
        normalized_existing = self._normalize_experience_level(existing)
        if normalized_existing:
            return normalized_existing
        haystack = " ".join(
            str(job.get(part) or "")
            for part in ("title", "description", "requirements")
        )
        inferred = self._normalize_experience_level(haystack)
        if inferred:
            return inferred
        return "mid"

    def _infer_job_type(self, job: dict[str, Any]) -> str:
        existing = str(job.get("job_type") or "").strip().lower()
        if existing:
            return existing
        haystack = " ".join(
            str(job.get(part) or "")
            for part in ("title", "description", "requirements")
        ).lower()
        if any(token in haystack for token in ("part-time", "part time", "teilzeit")):
            return "part-time"
        if any(token in haystack for token in ("contract", "contractor", "freelance", "befristet")):
            return "contract"
        if any(token in haystack for token in ("intern", "internship", "praktikum", "trainee")):
            return "internship"
        return "full-time"

    def _passes_date_filter(self, posted_date: date | None, date_posted_filter: str) -> bool:
        if not date_posted_filter:
            return True
        if date_posted_filter in {"last_1h", "last_4h", "last_8h"}:
            # Source pages often expose only day-level recency; treat same-day postings as eligible.
            return posted_date is None or posted_date >= date.today()
        window_map = {
            "last_24h": 1,
            "last_3_days": 3,
            "last_7_days": 7,
            "last_14_days": 14,
            "last_21_days": 21,
            "last_30_days": 30,
        }
        days = window_map.get(date_posted_filter)
        if not days:
            return True
        if not posted_date:
            return True
        return posted_date >= (date.today() - timedelta(days=days))

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

    def _resolve_search_result_url(self, href: str) -> str:
        if not href:
            return ""
        normalized = self._normalize_url(href, "https://duckduckgo.com")
        parsed = urlparse(normalized)
        query = parse_qs(parsed.query)
        target = query.get("uddg", [None])[0]
        if target:
            return target
        return normalized

    def _pick_stepstone_job_link(self, card: Any) -> Any | None:
        if hasattr(card, "select_one"):
            direct = card.select_one("a[data-testid='job-item-title'][href]")
            if direct:
                return direct

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
        if not url:
            return ""
        parsed = urlparse(url)
        path = parsed.path or ""
        if not path:
            return ""
        numeric = re.search(r"/job/(\d+)", path)
        if numeric:
            return numeric.group(1)[:255]
        legacy = re.search(r"--(\d+)(?:-[a-z]+)?(?:\.html)?$", path)
        if legacy:
            return legacy.group(1)[:255]
        slug = path.strip("/").split("/")[-1]
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

    def _looks_like_cloudflare_challenge(self, content: str) -> bool:
        if not content:
            return False
        lowered = content.lower()
        return (
            "cf-chl-opt" in lowered
            or "cdn-cgi/challenge-platform" in lowered
            or "just a moment..." in lowered
            or "enable javascript and cookies to continue" in lowered
        )

    def _slugify_for_path(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip()).strip("-").lower()
        return slug or quote_plus(value or "")
