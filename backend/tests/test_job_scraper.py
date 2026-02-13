from bs4 import BeautifulSoup

from app.api.jobs import _canonical_job_url, _unique_ids
from app.services.job_scraper import JobScraper


def test_unique_ids_preserves_order_and_removes_duplicates():
    assert _unique_ids([1, 1, 2, 3, 2, 4, 4]) == [1, 2, 3, 4]


def test_indeed_relative_link_is_normalized():
    scraper = JobScraper()
    html = '''
    <div class="job_seen_beacon" data-jk="abc123">
      <h2 class="jobTitle"><a href="rc/clk?jk=abc123">Data Engineer</a></h2>
      <span class="companyName">Example GmbH</span>
      <div class="companyLocation">Berlin</div>
      <div class="job-snippet">Python SQL Spark</div>
    </div>
    '''
    card = BeautifulSoup(html, "html.parser").find("div")
    job = scraper._parse_indeed_card(card)
    assert job is not None
    assert job["url"].startswith("https://de.indeed.com/")


def test_indeed_anchor_template_extracts_job_id_and_link():
    scraper = JobScraper()
    html = """
    <a class="jcs-JobTitle" href="/viewjob?jk=xyz987123abc">Data Engineer</a>
    """
    anchor = BeautifulSoup(html, "html.parser").find("a")
    job = scraper._parse_indeed_card(anchor)
    assert job is not None
    assert job["external_job_id"] == "xyz987123abc"
    assert job["url"] == "https://de.indeed.com/viewjob?jk=xyz987123abc"


def test_stepstone_prefers_job_link_over_company_link():
    scraper = JobScraper()
    html = '''
    <article>
      <a href="/cmp/de/some-company">Company</a>
      <a href="/stellenangebote--data-engineer-berlin-12345-inline.html">Job</a>
      <h2>Data Engineer</h2>
      <p>Python SQL</p>
    </article>
    '''
    card = BeautifulSoup(html, "html.parser").find("article")
    job = scraper._parse_stepstone_card(card)
    assert job is not None
    assert "/stellenangebote" in job["url"]


def test_canonical_stepstone_numeric_external_id_maps_to_job_detail():
    link = _canonical_job_url(
        source="stepstone",
        url="https://www.stepstone.de/jobs/data%20engineer?where=berlin",
        external_job_id="13610749",
        title="Data Engineer",
        location="Berlin",
    )
    assert link == "https://www.stepstone.de/job/13610749"


def test_canonical_stepstone_invalid_external_id_preserves_raw_url():
    link = _canonical_job_url(
        source="stepstone",
        url="https://www.stepstone.de/jobs/data%20engineer?where=berlin",
        external_job_id="COMPANY_LOGO_LINK",
        title="Data Engineer",
        location="Berlin",
    )
    assert link == "https://www.stepstone.de/jobs/data%20engineer?where=berlin"


def test_linkedin_card_parsing_uses_job_view_link():
    scraper = JobScraper()
    html = """
    <li>
      <div>
        <h3 class="base-search-card__title">Data Engineer</h3>
        <h4 class="base-search-card__subtitle">Example AG</h4>
        <span class="job-search-card__location">Berlin, Germany</span>
        <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/4188123456/?refId=test">Open</a>
        <time datetime="2026-02-10">2 days ago</time>
      </div>
    </li>
    """
    card = BeautifulSoup(html, "html.parser").find("li")
    job = scraper._parse_linkedin_card(card)
    assert job is not None
    assert job["source"] == "linkedin"
    assert job["external_job_id"] == "4188123456"
    assert job["url"] == "https://www.linkedin.com/jobs/view/4188123456/"


def test_canonical_linkedin_url_from_numeric_external_id():
    link = _canonical_job_url(
        source="linkedin",
        url="https://www.linkedin.com/jobs/search/?keywords=data",
        external_job_id="4188123456",
        title="Data Engineer",
        location="Berlin",
    )
    assert link == "https://www.linkedin.com/jobs/view/4188123456/"


def test_linkedin_slug_url_is_canonicalized_to_numeric_view_link():
    link = _canonical_job_url(
        source="linkedin",
        url="https://de.linkedin.com/jobs/view/data-engineer-at-example-company-4188123456?trackingId=abc",
        external_job_id="linkedin-1234",
        title="Data Engineer",
        location="Berlin",
    )
    assert link == "https://www.linkedin.com/jobs/view/4188123456/"


def test_indeed_id_from_vjk_query_is_extracted():
    scraper = JobScraper()
    job_id = scraper._indeed_job_id_from_href("/rc/clk?cmp=Acme&vjk=123abc456def")
    assert job_id == "123abc456def"


def test_parse_relative_date_handles_iso_dates():
    scraper = JobScraper()
    parsed = scraper._parse_relative_date("2026-02-10")
    assert parsed is not None
    assert parsed.isoformat() == "2026-02-10"
