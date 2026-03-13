"""
Pure-function HTML/RSS parsers for Upwork.

Each function takes raw text and returns a domain model. No I/O,
no side effects — purely a transformation layer.

Parsing strategy:
- Job search results pages use JSON embedded in <script id="__NEXT_DATA__">
- Individual job pages fall back to meta-tag + DOM extraction
- RSS entries come pre-parsed as dicts from feedparser
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from src.models.client import Client, ClientSignals
from src.models.job import ExperienceLevel, Job, JobType

logger = logging.getLogger(__name__)

_PLATFORM = "upwork"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_tags(html: str) -> str:
    """Remove HTML tags from a string using the stdlib HTMLParser."""

    class _Stripper(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self._parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self._parts.append(data)

        def get_text(self) -> str:
            return " ".join(self._parts)

    s = _Stripper()
    s.feed(html)
    return s.get_text().strip()


def _parse_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = re.sub(r"[^\d.]", "", value)
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_float(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = re.sub(r"[^\d.]", "", value)
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = re.sub(r"[^\d]", "", value)
    try:
        return int(cleaned)
    except ValueError:
        return None


def _extract_job_id_from_url(url: str) -> str:
    """Extract the Upwork job ID from a job URL."""
    # Match the canonical ~<id> pattern anywhere in the URL path
    match = re.search(r"~(\w+)", url)
    if match:
        return match.group(1)
    # Fall back to last path segment, stripping any leading ~
    segment = url.rstrip("/").split("/")[-1]
    return segment.lstrip("~")


def _detect_job_type(text: str) -> JobType:
    lower = text.lower()
    if "hourly" in lower:
        return JobType.HOURLY
    return JobType.FIXED


def _detect_experience_level(text: str) -> ExperienceLevel | None:
    lower = text.lower()
    if "expert" in lower:
        return ExperienceLevel.EXPERT
    if "intermediate" in lower:
        return ExperienceLevel.INTERMEDIATE
    if "entry" in lower or "beginner" in lower:
        return ExperienceLevel.ENTRY
    return None


def _parse_budget_range(text: str) -> tuple[Decimal | None, Decimal | None]:
    """Extract min/max from strings like '$500 - $1,000' or '$25.00/hr'."""
    numbers = re.findall(r"[\d,]+(?:\.\d+)?", text.replace(",", ""))
    decimals = [Decimal(n) for n in numbers if n]
    if len(decimals) == 0:
        return None, None
    if len(decimals) == 1:
        return decimals[0], decimals[0]
    return decimals[0], decimals[1]


def _parse_posted_at(text: str) -> datetime:
    """Best-effort parse of 'X hours ago', 'X days ago', or ISO strings."""
    now = datetime.now(timezone.utc)
    lower = text.lower().strip()

    match = re.search(r"(\d+)\s+hour", lower)
    if match:
        from datetime import timedelta
        return now - timedelta(hours=int(match.group(1)))

    match = re.search(r"(\d+)\s+day", lower)
    if match:
        from datetime import timedelta
        return now - timedelta(days=int(match.group(1)))

    match = re.search(r"(\d+)\s+minute", lower)
    if match:
        from datetime import timedelta
        return now - timedelta(minutes=int(match.group(1)))

    # Attempt RFC 822 (common in RSS feeds, e.g. "Fri, 13 Mar 2026 08:30:00 +0000")
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(text)
    except (ValueError, TypeError):
        pass

    # Attempt ISO parse
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return now


# ---------------------------------------------------------------------------
# Public parsing functions
# ---------------------------------------------------------------------------


def parse_job_listing(raw_html: str, platform: str = _PLATFORM) -> Job:
    """
    Parse a single Upwork job listing page into a Job model.

    Extracts from <meta> tags and structured text patterns when
    the full Next.js data blob is not available.
    """
    # Extract URL / canonical link
    url_match = re.search(r'<link rel="canonical" href="([^"]+)"', raw_html)
    url = url_match.group(1) if url_match else ""
    platform_job_id = _extract_job_id_from_url(url)

    # Title
    title_match = re.search(r"<title>([^<]+)</title>", raw_html, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else "Unknown"
    # Strip site suffix
    title = re.sub(r"\s*[-|].*Upwork.*$", "", title, flags=re.IGNORECASE).strip()

    # Description — usually in og:description
    desc_match = re.search(
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
        raw_html,
        re.IGNORECASE,
    )
    if not desc_match:
        desc_match = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
            raw_html,
            re.IGNORECASE,
        )
    description = desc_match.group(1).strip() if desc_match else ""

    # Budget/rate
    budget_match = re.search(
        r"(Fixed[- ]Price|Hourly)[^$]*(\$[\d,]+(?:\.\d+)?(?:\s*-\s*\$[\d,]+(?:\.\d+)?)?)",
        raw_html,
        re.IGNORECASE,
    )
    job_type = JobType.FIXED
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    hourly_rate_min: Decimal | None = None
    hourly_rate_max: Decimal | None = None

    if budget_match:
        job_type = _detect_job_type(budget_match.group(1))
        b_min, b_max = _parse_budget_range(budget_match.group(2))
        if job_type == JobType.HOURLY:
            hourly_rate_min, hourly_rate_max = b_min, b_max
        else:
            budget_min, budget_max = b_min, b_max

    # Experience level
    exp_match = re.search(
        r"(Entry Level|Intermediate|Expert)",
        raw_html,
        re.IGNORECASE,
    )
    experience_level = (
        _detect_experience_level(exp_match.group(1)) if exp_match else None
    )

    # Skills — look for common skill tag patterns
    skills: list[str] = re.findall(
        r'data-test="[^"]*skill[^"]*"[^>]*>([^<]+)<',
        raw_html,
        re.IGNORECASE,
    )
    if not skills:
        skills_section = re.search(
            r"Skills and Expertise(.{0,2000})", raw_html, re.DOTALL | re.IGNORECASE
        )
        if skills_section:
            skills = re.findall(r"<[^>]+>([A-Za-z][A-Za-z0-9 +#.]+)</[^>]+>",
                                skills_section.group(1))
            skills = [s.strip() for s in skills if 2 < len(s.strip()) < 50][:15]

    # Posted date
    posted_match = re.search(
        r"Posted\s+(?:on\s+)?([^<\n]+)",
        raw_html,
        re.IGNORECASE,
    )
    posted_at = _parse_posted_at(posted_match.group(1)) if posted_match else datetime.now(timezone.utc)

    # Proposals count
    proposals_match = re.search(r"(\d+)\s+proposal", raw_html, re.IGNORECASE)
    proposals_count = int(proposals_match.group(1)) if proposals_match else None

    return Job(
        platform=platform,
        platform_job_id=platform_job_id,
        url=url,
        title=title,
        description=description,
        job_type=job_type,
        experience_level=experience_level,
        budget_min=budget_min,
        budget_max=budget_max,
        hourly_rate_min=hourly_rate_min,
        hourly_rate_max=hourly_rate_max,
        required_skills=skills,
        posted_at=posted_at,
        proposals_count=proposals_count,
    )


def parse_job_from_rss(entry: dict) -> Job:
    """
    Convert a feedparser RSS entry dict into a Job model.

    Upwork RSS feeds embed structured data in the <description> field
    as human-readable text blocks we parse with regexes.
    """
    url = entry.get("link", "")
    platform_job_id = _extract_job_id_from_url(url)
    title = _strip_tags(entry.get("title", "Unknown"))

    raw_description = entry.get("description", "") or entry.get("summary", "")
    description = _strip_tags(raw_description)

    # Use the tag-stripped text for all field extraction so that HTML markup
    # (e.g. <b>Skills:</b>) does not break label-based regex patterns.
    plain = description

    # Budget / job type — detect from raw text (tags don't affect keyword search)
    job_type = _detect_job_type(plain)
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    hourly_rate_min: Decimal | None = None
    hourly_rate_max: Decimal | None = None

    # Budget range: "$40.00/hr - $60.00/hr" or "$500 - $1,000"
    # Allow optional /hr suffix between the two dollar amounts.
    budget_match = re.search(
        r"\$\s*([\d,]+(?:\.\d+)?)(?:/hr)?"
        r"(?:\s*-\s*\$\s*([\d,]+(?:\.\d+)?)(?:/hr)?)?",
        plain,
    )
    if budget_match:
        lo = _parse_decimal(budget_match.group(1))
        hi = _parse_decimal(budget_match.group(2)) if budget_match.group(2) else lo
        if job_type == JobType.HOURLY:
            hourly_rate_min, hourly_rate_max = lo, hi
        else:
            budget_min, budget_max = lo, hi

    # Experience level
    exp_match = re.search(r"(Entry Level|Intermediate|Expert)", plain, re.IGNORECASE)
    experience_level = _detect_experience_level(exp_match.group(1)) if exp_match else None

    # Skills — listed after "Skills:" label, stop at the next known field label
    skills: list[str] = []
    skills_match = re.search(
        r"Skills?:\s*(.+?)(?:\s+(?:Country|Budget|Category|Posted On|Hourly Range)\s*:|$)",
        plain,
        re.IGNORECASE,
    )
    if skills_match:
        skills = [s.strip() for s in skills_match.group(1).split(",") if s.strip()]

    # Country — listed after "Country:" label in plain text
    country_match = re.search(r"Country:\s*([^\n]+)", plain, re.IGNORECASE)
    client_country = country_match.group(1).strip() if country_match else None

    # Posted date from RSS
    published = entry.get("published") or entry.get("updated") or ""
    posted_at = _parse_posted_at(published) if published else datetime.now(timezone.utc)

    return Job(
        platform=_PLATFORM,
        platform_job_id=platform_job_id,
        url=url,
        title=title,
        description=description,
        job_type=job_type,
        experience_level=experience_level,
        budget_min=budget_min,
        budget_max=budget_max,
        hourly_rate_min=hourly_rate_min,
        hourly_rate_max=hourly_rate_max,
        required_skills=skills,
        client_country=client_country,
        posted_at=posted_at,
        raw_data=dict(entry),
    )


def parse_client_profile(raw_html: str) -> Client:
    """
    Parse a client/company profile page into a Client model.

    Upwork client profile pages expose most signals in structured
    text blocks; we parse via targeted regex patterns.
    """
    # Client ID from canonical URL
    url_match = re.search(r'href="([^"]+/companies/[^"]+)"', raw_html)
    if not url_match:
        url_match = re.search(r'/companies/(~\w+)', raw_html)
    platform_client_id = (
        _extract_job_id_from_url(url_match.group(1)) if url_match else "unknown"
    )

    # Name
    name_match = re.search(r"<h1[^>]*>([^<]+)</h1>", raw_html)
    name = name_match.group(1).strip() if name_match else None

    # Country
    country_match = re.search(
        r'data-test="client-country"[^>]*>([^<]+)<',
        raw_html,
        re.IGNORECASE,
    )
    if not country_match:
        country_match = re.search(r"Location\s*</[^>]+>\s*<[^>]+>([^<]+)", raw_html)
    country = country_match.group(1).strip() if country_match else None

    # Member since
    since_match = re.search(
        r"Member\s+Since\s*</[^>]+>\s*<[^>]+>([^<]+)",
        raw_html,
        re.IGNORECASE,
    )
    member_since: datetime | None = None
    if since_match:
        try:
            member_since = datetime.strptime(
                since_match.group(1).strip(), "%B %Y"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Total spent
    spent_match = re.search(
        r"\$([\d,]+(?:\.\d+)?[KkMm]?)\s+(?:total spent|spent)",
        raw_html,
        re.IGNORECASE,
    )
    total_spent: Decimal | None = None
    if spent_match:
        raw_spent = spent_match.group(1).upper().replace(",", "")
        if raw_spent.endswith("K"):
            total_spent = Decimal(raw_spent[:-1]) * 1000
        elif raw_spent.endswith("M"):
            total_spent = Decimal(raw_spent[:-1]) * 1_000_000
        else:
            total_spent = _parse_decimal(raw_spent)

    # Jobs posted
    jobs_match = re.search(r"(\d+)\s+(?:jobs? posted|job postings)", raw_html, re.IGNORECASE)
    total_jobs_posted = _parse_int(jobs_match.group(1)) if jobs_match else None

    # Hire rate
    hire_match = re.search(r"(\d+)%\s+hire\s+rate", raw_html, re.IGNORECASE)
    hire_rate = _parse_float(hire_match.group(1)) if hire_match else None
    if hire_rate is not None:
        hire_rate = hire_rate / 100.0

    # Rating (out of 5)
    rating_match = re.search(
        r'rating["\s][^>]*>([\d.]+)\s*out\s*of\s*5', raw_html, re.IGNORECASE
    )
    if not rating_match:
        rating_match = re.search(r"([\d.]+)\s*/\s*5", raw_html)
    rating = _parse_float(rating_match.group(1)) if rating_match else None

    # Payment verified
    payment_verified = bool(
        re.search(r"Payment\s+Verified", raw_html, re.IGNORECASE)
    )

    # Response rate
    resp_match = re.search(r"(\d+)%\s+response\s+rate", raw_html, re.IGNORECASE)
    response_rate = None
    if resp_match:
        response_rate = float(resp_match.group(1)) / 100.0

    signals = ClientSignals(
        is_verified_payment=payment_verified,
        avg_review_score=rating,
        response_rate=response_rate,
    )

    return Client(
        platform=_PLATFORM,
        platform_client_id=platform_client_id,
        name=name,
        country=country,
        member_since=member_since,
        total_spent=total_spent,
        total_jobs_posted=total_jobs_posted,
        hire_rate=hire_rate,
        rating=rating,
        signals=signals,
    )


def parse_job_search_results(html: str) -> list[Job]:
    """
    Parse a search results page and return all visible job listings.

    Upwork embeds results as JSON inside a <script id="__NEXT_DATA__"> block.
    Falls back to HTML-level extraction when the embedded JSON is absent.
    """
    import json as _json

    # Primary: Next.js embedded JSON
    next_data_match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>([^<]+)</script>',
        html,
        re.DOTALL,
    )
    if next_data_match:
        try:
            data = _json.loads(next_data_match.group(1))
            results = (
                data.get("props", {})
                .get("pageProps", {})
                .get("initialData", {})
                .get("searchResults", {})
                .get("job_postings", [])
            )
            jobs = []
            for item in results:
                try:
                    jobs.append(_job_from_next_data(item))
                except Exception:
                    logger.debug("Skipping malformed job item: %s", item.get("id"))
            return jobs
        except (_json.JSONDecodeError, KeyError):
            logger.debug("__NEXT_DATA__ parse failed, falling back to HTML")

    # Fallback: locate individual job tile blocks in raw HTML
    # Job tiles are wrapped in <article> or elements with data-test="job-tile"
    tile_pattern = re.compile(
        r'data-test=["\']job-tile["\'][^>]*>(.*?)</article>',
        re.DOTALL | re.IGNORECASE,
    )
    tiles = tile_pattern.findall(html)
    jobs = []
    for tile_html in tiles:
        try:
            jobs.append(parse_job_listing(tile_html))
        except Exception:
            logger.debug("Skipping unparseable job tile")
    return jobs


def _job_from_next_data(item: dict) -> Job:
    """Convert a single Next.js pageProps job_posting dict into a Job."""
    url = f"https://www.upwork.com/jobs/{item.get('ciphertext', '')}"
    platform_job_id = item.get("ciphertext", item.get("id", ""))

    engagement = item.get("engagement", "")
    job_type = _detect_job_type(engagement)

    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    hourly_rate_min: Decimal | None = None
    hourly_rate_max: Decimal | None = None

    if job_type == JobType.FIXED:
        budget = item.get("budget", {})
        if isinstance(budget, dict):
            budget_min = _parse_decimal(str(budget.get("rawValue", "") or ""))
        else:
            budget_min = _parse_decimal(str(budget or ""))
        budget_max = budget_min
    else:
        rate_min = item.get("hourlyBudgetMin")
        rate_max = item.get("hourlyBudgetMax")
        hourly_rate_min = _parse_decimal(str(rate_min or ""))
        hourly_rate_max = _parse_decimal(str(rate_max or ""))

    skills = [s.get("prettyName", s.get("skill", "")) for s in item.get("skills", [])]
    skills = [s for s in skills if s]

    exp_label = item.get("experienceLevel", "")
    experience_level = _detect_experience_level(exp_label) if exp_label else None

    client_info = item.get("client", {})
    client_country = client_info.get("location", {}).get("country") if client_info else None
    client_rating_raw = client_info.get("feedbackScore") if client_info else None
    client_rating = float(client_rating_raw) if client_rating_raw is not None else None
    client_total_spent_raw = client_info.get("totalSpent") if client_info else None
    client_total_spent = _parse_decimal(str(client_total_spent_raw or ""))

    proposals_raw = item.get("proposalsTier", "")
    proposals_count: int | None = None
    if proposals_raw:
        first_num = re.search(r"\d+", str(proposals_raw))
        proposals_count = int(first_num.group()) if first_num else None

    posted_at_raw = item.get("publishedOn", item.get("createdOn", ""))
    posted_at = _parse_posted_at(str(posted_at_raw)) if posted_at_raw else datetime.now(timezone.utc)

    return Job(
        platform=_PLATFORM,
        platform_job_id=str(platform_job_id),
        url=url,
        title=item.get("title", "Unknown"),
        description=item.get("description", ""),
        job_type=job_type,
        experience_level=experience_level,
        budget_min=budget_min,
        budget_max=budget_max,
        hourly_rate_min=hourly_rate_min,
        hourly_rate_max=hourly_rate_max,
        required_skills=skills,
        client_country=client_country,
        client_rating=client_rating,
        client_total_spent=client_total_spent,
        estimated_duration=item.get("duration", {}).get("label") if isinstance(item.get("duration"), dict) else None,
        proposals_count=proposals_count,
        posted_at=posted_at,
        raw_data=item,
    )
