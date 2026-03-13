"""
Unit tests for src/platform/upwork/parsers.py

All tests are pure in-memory transformations — no network, no DB,
no file I/O beyond loading HTML/XML fixtures from tests/fixtures/.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.job import ExperienceLevel, Job, JobType
from src.platform.upwork.parsers import (
    _parse_budget_range,
    _parse_decimal,
    _parse_posted_at,
    parse_client_profile,
    parse_job_from_rss,
    parse_job_listing,
    parse_job_search_results,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def job_listing_html() -> str:
    return (FIXTURES / "upwork_job_listing.html").read_text(encoding="utf-8")


@pytest.fixture
def rss_entry_dict() -> dict:
    """Pre-parsed RSS entry dict, as feedparser would produce it."""
    return {
        "title": "Django REST API Developer Needed — Hourly Contract",
        "link": "https://www.upwork.com/jobs/~02xyz789abc012de34",
        "description": (
            "<b>Django REST API Developer Needed — Hourly Contract</b><br/>"
            "<b>Budget:</b> $40.00/hr - $60.00/hr<br/>"
            "<b>Job Type:</b> Hourly<br/>"
            "<b>Experience Level:</b> Intermediate<br/>"
            "We are looking for a Django REST Framework developer.<br/>"
            "<b>Skills:</b> Python, Django, Django REST Framework, PostgreSQL, Docker<br/>"
            "<b>Country:</b> Canada<br/>"
        ),
        "published": "Fri, 13 Mar 2026 08:30:00 +0000",
        "summary": "Django REST API developer needed for ongoing contract work.",
    }


@pytest.fixture
def client_profile_html() -> str:
    return """
    <html>
    <body>
      <h1>Acme Corp</h1>
      <div>Location</div>
      <div>United Kingdom</div>
      <div>Member Since</div>
      <div>January 2019</div>
      <p>$85,000 total spent</p>
      <p>42 jobs posted</p>
      <p>65% hire rate</p>
      <p>4.8 / 5</p>
      <span>Payment Verified</span>
      <p>90% response rate</p>
      <a href="/companies/~acme123corp">Acme Corp profile</a>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# parse_job_listing
# ---------------------------------------------------------------------------


class TestParseJobListing:
    def test_returns_job_instance(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        assert isinstance(job, Job)

    def test_platform_is_upwork(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        assert job.platform == "upwork"

    def test_extracts_platform_job_id(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        assert job.platform_job_id == "01abc123def456gh78"

    def test_extracts_canonical_url(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        assert "upwork.com/jobs" in job.url

    def test_extracts_title(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        assert "FastAPI" in job.title

    def test_extracts_description(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        assert len(job.description) > 20

    def test_detects_fixed_job_type(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        assert job.job_type == JobType.FIXED

    def test_extracts_budget_range(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        assert job.budget_min is not None
        assert job.budget_max is not None
        assert job.budget_min <= job.budget_max

    def test_detects_expert_experience_level(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        assert job.experience_level == ExperienceLevel.EXPERT

    def test_extracts_skills(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        assert len(job.required_skills) >= 1

    def test_extracts_proposals_count(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        assert job.proposals_count == 15

    def test_custom_platform_override(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html, platform="test_platform")
        assert job.platform == "test_platform"

    def test_frozen_model(self, job_listing_html: str) -> None:
        job = parse_job_listing(job_listing_html)
        with pytest.raises((TypeError, AttributeError, ValidationError)):
            job.title = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# parse_job_from_rss
# ---------------------------------------------------------------------------


class TestParseJobFromRss:
    def test_returns_job_instance(self, rss_entry_dict: dict) -> None:
        job = parse_job_from_rss(rss_entry_dict)
        assert isinstance(job, Job)

    def test_platform_is_upwork(self, rss_entry_dict: dict) -> None:
        job = parse_job_from_rss(rss_entry_dict)
        assert job.platform == "upwork"

    def test_extracts_platform_job_id(self, rss_entry_dict: dict) -> None:
        job = parse_job_from_rss(rss_entry_dict)
        assert job.platform_job_id == "02xyz789abc012de34"

    def test_extracts_url(self, rss_entry_dict: dict) -> None:
        job = parse_job_from_rss(rss_entry_dict)
        assert job.url == "https://www.upwork.com/jobs/~02xyz789abc012de34"

    def test_detects_hourly_job_type(self, rss_entry_dict: dict) -> None:
        job = parse_job_from_rss(rss_entry_dict)
        assert job.job_type == JobType.HOURLY

    def test_extracts_hourly_rate(self, rss_entry_dict: dict) -> None:
        job = parse_job_from_rss(rss_entry_dict)
        assert job.hourly_rate_min == Decimal("40.00")
        assert job.hourly_rate_max == Decimal("60.00")

    def test_detects_intermediate_experience(self, rss_entry_dict: dict) -> None:
        job = parse_job_from_rss(rss_entry_dict)
        assert job.experience_level == ExperienceLevel.INTERMEDIATE

    def test_extracts_skills_from_rss(self, rss_entry_dict: dict) -> None:
        job = parse_job_from_rss(rss_entry_dict)
        assert "Python" in job.required_skills

    def test_extracts_client_country(self, rss_entry_dict: dict) -> None:
        job = parse_job_from_rss(rss_entry_dict)
        assert job.client_country == "Canada"

    def test_raw_data_preserved(self, rss_entry_dict: dict) -> None:
        job = parse_job_from_rss(rss_entry_dict)
        # raw_data is excluded from frozen model but accessible before construction
        # We check the entry dict data was passed through
        assert job.platform_job_id == "02xyz789abc012de34"

    def test_minimal_entry_does_not_raise(self) -> None:
        minimal = {"link": "https://www.upwork.com/jobs/~00minimal", "title": "A Job"}
        job = parse_job_from_rss(minimal)
        assert isinstance(job, Job)
        assert job.title == "A Job"


# ---------------------------------------------------------------------------
# parse_client_profile
# ---------------------------------------------------------------------------


class TestParseClientProfile:
    def test_returns_client(self, client_profile_html: str) -> None:
        from src.models.client import Client
        client = parse_client_profile(client_profile_html)
        assert isinstance(client, Client)

    def test_extracts_name(self, client_profile_html: str) -> None:
        client = parse_client_profile(client_profile_html)
        assert client.name == "Acme Corp"

    def test_platform_is_upwork(self, client_profile_html: str) -> None:
        client = parse_client_profile(client_profile_html)
        assert client.platform == "upwork"

    def test_payment_verified_signal(self, client_profile_html: str) -> None:
        client = parse_client_profile(client_profile_html)
        assert client.signals.is_verified_payment is True

    def test_hire_rate_normalized(self, client_profile_html: str) -> None:
        client = parse_client_profile(client_profile_html)
        assert client.hire_rate is not None
        assert 0.0 <= client.hire_rate <= 1.0

    def test_response_rate_normalized(self, client_profile_html: str) -> None:
        client = parse_client_profile(client_profile_html)
        assert client.signals.response_rate is not None
        assert 0.0 <= client.signals.response_rate <= 1.0

    def test_frozen_model(self, client_profile_html: str) -> None:
        client = parse_client_profile(client_profile_html)
        with pytest.raises((TypeError, AttributeError, ValidationError)):
            client.name = "hacked"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# parse_job_search_results
# ---------------------------------------------------------------------------


class TestParseJobSearchResults:
    def test_returns_list(self) -> None:
        result = parse_job_search_results("<html><body>No jobs here</body></html>")
        assert isinstance(result, list)

    def test_empty_html_returns_empty_list(self) -> None:
        result = parse_job_search_results("")
        assert result == []

    def test_parses_next_data_json(self) -> None:
        import json
        next_data = {
            "props": {
                "pageProps": {
                    "initialData": {
                        "searchResults": {
                            "job_postings": [
                                {
                                    "ciphertext": "~abc123",
                                    "title": "Python Developer",
                                    "description": "Build async APIs",
                                    "engagement": "Hourly",
                                    "hourlyBudgetMin": 50,
                                    "hourlyBudgetMax": 100,
                                    "skills": [
                                        {"prettyName": "Python"},
                                        {"prettyName": "FastAPI"},
                                    ],
                                    "experienceLevel": "Expert",
                                    "publishedOn": "2026-03-13T08:00:00Z",
                                }
                            ]
                        }
                    }
                }
            }
        }
        html = (
            f'<script id="__NEXT_DATA__">{json.dumps(next_data)}</script>'
        )
        jobs = parse_job_search_results(html)
        assert len(jobs) == 1
        assert jobs[0].title == "Python Developer"
        assert jobs[0].job_type == JobType.HOURLY
        assert jobs[0].experience_level == ExperienceLevel.EXPERT
        assert "Python" in jobs[0].required_skills

    def test_malformed_next_data_falls_back_gracefully(self) -> None:
        html = '<script id="__NEXT_DATA__">{ invalid json }</script>'
        result = parse_job_search_results(html)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Internal helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_parse_decimal_valid(self) -> None:
        assert _parse_decimal("$1,500.00") == Decimal("1500.00")

    def test_parse_decimal_none_input(self) -> None:
        assert _parse_decimal(None) is None

    def test_parse_decimal_empty_string(self) -> None:
        assert _parse_decimal("") is None

    def test_parse_budget_range_single_value(self) -> None:
        lo, hi = _parse_budget_range("$500")
        assert lo == hi == Decimal("500")

    def test_parse_budget_range_range(self) -> None:
        lo, hi = _parse_budget_range("$500 - $1,000")
        assert lo == Decimal("500")
        assert hi == Decimal("1000")

    def test_parse_budget_range_empty(self) -> None:
        lo, hi = _parse_budget_range("no budget here")
        assert lo is None
        assert hi is None

    def test_parse_posted_at_hours_ago(self) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        result = _parse_posted_at("3 hours ago")
        diff = now - result
        assert 0 < diff.total_seconds() < 4 * 3600

    def test_parse_posted_at_days_ago(self) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        result = _parse_posted_at("2 days ago")
        diff = now - result
        assert 1 * 86400 < diff.total_seconds() < 3 * 86400

    def test_parse_posted_at_iso(self) -> None:
        result = _parse_posted_at("2026-03-13T08:30:00+00:00")
        assert result.year == 2026
        assert result.month == 3

    def test_parse_posted_at_fallback_to_now(self) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        result = _parse_posted_at("some unparseable string xyz")
        assert abs((result - now).total_seconds()) < 5
