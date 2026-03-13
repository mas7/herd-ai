"""
Upwork job and client scraper using Playwright.

Implements the JobScraper and ClientInspector protocols via stealth
browser automation. Supports both full-page scraping and lightweight
RSS feed monitoring.

Anti-bot measures applied:
- Random delays between actions (human typing cadence)
- Incremental scrolling to trigger lazy-load
- Random viewport jitter on each new page
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, AsyncIterator

import httpx

from src.models.client import Client
from src.models.job import Job, JobFilter, JobType
from src.platform.upwork.auth import UpworkAuth
from src.platform.upwork.parsers import (
    parse_client_profile,
    parse_job_from_rss,
    parse_job_listing,
    parse_job_search_results,
)

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.upwork.com"
_SEARCH_URL = f"{_BASE_URL}/nx/search/jobs/"
_RSS_BASE_URL = "https://www.upwork.com/ab/feed/jobs/rss"

# Delay bounds (seconds) for human-like pacing
_DELAY_MIN = 1.2
_DELAY_MAX = 3.5


async def _human_delay() -> None:
    await asyncio.sleep(random.uniform(_DELAY_MIN, _DELAY_MAX))


async def _scroll_page(page: Page) -> None:
    """Gradually scroll to the bottom to trigger lazy-loaded content."""
    scroll_height = await page.evaluate("document.body.scrollHeight")
    step = scroll_height // 6
    for pos in range(0, scroll_height, step):
        await page.evaluate(f"window.scrollTo(0, {pos})")
        await asyncio.sleep(random.uniform(0.15, 0.4))
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(0.5)


def _build_search_url(filters: JobFilter) -> str:
    """Translate a JobFilter into an Upwork search URL."""
    params: list[str] = []

    if filters.keywords:
        query = " ".join(filters.keywords)
        params.append(f"q={httpx.URL('', params={'q': query}).params}")

    if filters.job_type == JobType.HOURLY:
        params.append("job_type=hourly")
    elif filters.job_type == JobType.FIXED:
        params.append("job_type=fixed")

    if filters.budget_min is not None:
        params.append(f"budget={filters.budget_min}")

    if filters.posted_within_hours <= 24:
        params.append("sort=recency")

    if filters.skills:
        # Upwork uses the 'skills' query param with comma-separated slugs
        skills_param = ",".join(s.lower().replace(" ", "-") for s in filters.skills)
        params.append(f"skills={skills_param}")

    query_string = "&".join(params)
    return f"{_SEARCH_URL}?{query_string}" if query_string else _SEARCH_URL


def _build_rss_url(filters: JobFilter) -> str:
    """Build an Upwork RSS feed URL from a JobFilter."""
    parts: list[str] = []
    if filters.keywords:
        parts.append(f"q={'+'.join(filters.keywords)}")
    if filters.job_type == JobType.HOURLY:
        parts.append("job_type=hourly")
    elif filters.job_type == JobType.FIXED:
        parts.append("job_type=fixed")
    query = "&".join(parts)
    return f"{_RSS_BASE_URL}?{query}" if query else _RSS_BASE_URL


class UpworkScraper:
    """
    Playwright-based scraper that satisfies JobScraper and ClientInspector.

    Prefers full-browser scraping for rich data. RSS mode can be enabled
    as a lightweight alternative for high-frequency polling.
    """

    def __init__(
        self,
        browser_context: BrowserContext,
        auth: UpworkAuth,
        base_url: str = _BASE_URL,
    ) -> None:
        self._context = browser_context
        self._auth = auth
        self._base_url = base_url

    async def search_jobs(self, filters: JobFilter) -> AsyncIterator[Job]:
        """
        Yield Job objects from Upwork search results.

        Navigates the search results page, extracts all visible job tiles,
        then yields each parsed Job. Paginates until no more results or
        the recency filter would yield stale data.
        """
        url = _build_search_url(filters)
        page = await self._context.new_page()
        try:
            page_num = 1
            while True:
                paginated_url = url if page_num == 1 else f"{url}&page={page_num}"
                logger.info("Scraping Upwork search page %d: %s", page_num, paginated_url)

                await page.goto(paginated_url, wait_until="networkidle")
                await _scroll_page(page)

                html = await page.content()
                jobs = parse_job_search_results(html)

                if not jobs:
                    logger.debug("No jobs found on page %d — stopping", page_num)
                    break

                for job in jobs:
                    yield job

                # Check for a "next page" link before continuing
                next_btn = await page.query_selector(
                    'button[data-test="pagination-next"]:not([disabled])'
                )
                if next_btn is None:
                    break

                page_num += 1
                await _human_delay()
        finally:
            await page.close()

    async def get_job_details(self, platform_job_id: str) -> Job:
        """Scrape a single job detail page by its Upwork job ID."""
        url = f"{self._base_url}/jobs/~{platform_job_id}"
        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="networkidle")
            await _human_delay()
            html = await page.content()
            return parse_job_listing(html)
        finally:
            await page.close()

    async def get_client_profile(self, platform_client_id: str) -> Client:
        """Scrape a client/company profile page."""
        url = f"{self._base_url}/companies/~{platform_client_id}"
        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="networkidle")
            await _human_delay()
            await _scroll_page(page)
            html = await page.content()
            return parse_client_profile(html)
        finally:
            await page.close()

    async def search_jobs_via_rss(self, filters: JobFilter) -> AsyncIterator[Job]:
        """
        Yield Jobs from Upwork's RSS feed — lightweight and connection-cheap.

        Uses httpx for a direct HTTP fetch rather than a full browser page,
        which avoids most anti-bot friction for feed endpoints.

        Requires feedparser (optional dependency). If feedparser is not
        installed, raises ImportError with an actionable message.
        """
        try:
            import feedparser  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "feedparser is required for RSS mode: pip install feedparser"
            ) from exc

        rss_url = _build_rss_url(filters)
        logger.info("Fetching Upwork RSS: %s", rss_url)

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(rss_url, timeout=30.0)
            response.raise_for_status()

        feed = feedparser.parse(response.text)
        for entry in feed.entries:
            try:
                yield parse_job_from_rss(dict(entry))
            except Exception:
                logger.debug("Skipping malformed RSS entry: %s", entry.get("link"))
