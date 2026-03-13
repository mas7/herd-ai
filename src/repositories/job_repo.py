"""
Job repository — raw SQL data-access functions for the jobs table.

Convention: every function takes a Database instance as its first
argument. No class needed; the module is the namespace.

Schema expected (run migration before use):
    CREATE TABLE jobs (
        id              TEXT PRIMARY KEY,
        platform        TEXT NOT NULL,
        platform_job_id TEXT NOT NULL,
        url             TEXT NOT NULL,
        title           TEXT NOT NULL,
        description     TEXT NOT NULL,
        job_type        TEXT NOT NULL,
        experience_level TEXT,
        budget_min      TEXT,
        budget_max      TEXT,
        hourly_rate_min TEXT,
        hourly_rate_max TEXT,
        required_skills TEXT,       -- JSON array
        optional_skills TEXT,       -- JSON array
        estimated_duration TEXT,
        client_name     TEXT,
        client_country  TEXT,
        client_rating   REAL,
        client_total_spent TEXT,
        client_hire_rate   REAL,
        client_jobs_posted INTEGER,
        proposals_count    INTEGER,
        interviewing_count INTEGER,
        posted_at       TEXT NOT NULL,
        discovered_at   TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'discovered',
        UNIQUE (platform, platform_job_id)
    );
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal

from src.core.db import Database
from src.models.job import ExperienceLevel, Job, JobStatus, JobType

logger = logging.getLogger(__name__)


def _job_to_row(job: Job) -> tuple:
    """Serialize a Job model to a flat tuple for INSERT."""
    return (
        job.id,
        job.platform,
        job.platform_job_id,
        job.url,
        job.title,
        job.description,
        job.job_type.value,
        job.experience_level.value if job.experience_level else None,
        str(job.budget_min) if job.budget_min is not None else None,
        str(job.budget_max) if job.budget_max is not None else None,
        str(job.hourly_rate_min) if job.hourly_rate_min is not None else None,
        str(job.hourly_rate_max) if job.hourly_rate_max is not None else None,
        json.dumps(job.required_skills),
        json.dumps(job.optional_skills),
        job.estimated_duration,
        job.client_name,
        job.client_country,
        job.client_rating,
        str(job.client_total_spent) if job.client_total_spent is not None else None,
        job.client_hire_rate,
        job.client_jobs_posted,
        job.proposals_count,
        job.interviewing_count,
        job.posted_at.isoformat(),
        job.discovered_at.isoformat(),
        job.status.value,
    )


def _row_to_job(row: dict) -> Job:
    """Deserialize a DB row dict back into a Job model."""
    from datetime import datetime, timezone

    def _dt(val: str | None) -> datetime:
        if not val:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(val)

    def _dec(val: str | None) -> Decimal | None:
        return Decimal(val) if val is not None else None

    def _float(val) -> float | None:
        return float(val) if val is not None else None

    def _int(val) -> int | None:
        return int(val) if val is not None else None

    return Job(
        id=row["id"],
        platform=row["platform"],
        platform_job_id=row["platform_job_id"],
        url=row["url"],
        title=row["title"],
        description=row["description"],
        job_type=JobType(row["job_type"]),
        experience_level=ExperienceLevel(row["experience_level"]) if row.get("experience_level") else None,
        budget_min=_dec(row.get("budget_min")),
        budget_max=_dec(row.get("budget_max")),
        hourly_rate_min=_dec(row.get("hourly_rate_min")),
        hourly_rate_max=_dec(row.get("hourly_rate_max")),
        required_skills=json.loads(row.get("required_skills") or "[]"),
        optional_skills=json.loads(row.get("optional_skills") or "[]"),
        estimated_duration=row.get("estimated_duration"),
        client_name=row.get("client_name"),
        client_country=row.get("client_country"),
        client_rating=_float(row.get("client_rating")),
        client_total_spent=_dec(row.get("client_total_spent")),
        client_hire_rate=_float(row.get("client_hire_rate")),
        client_jobs_posted=_int(row.get("client_jobs_posted")),
        proposals_count=_int(row.get("proposals_count")),
        interviewing_count=_int(row.get("interviewing_count")),
        posted_at=_dt(row.get("posted_at")),
        discovered_at=_dt(row.get("discovered_at")),
        status=JobStatus(row.get("status", "discovered")),
    )


_INSERT_SQL = """
    INSERT INTO jobs (
        id, platform, platform_job_id, url, title, description,
        job_type, experience_level,
        budget_min, budget_max, hourly_rate_min, hourly_rate_max,
        required_skills, optional_skills, estimated_duration,
        client_name, client_country, client_rating, client_total_spent,
        client_hire_rate, client_jobs_posted,
        proposals_count, interviewing_count,
        posted_at, discovered_at, status
    ) VALUES (
        ?, ?, ?, ?, ?, ?,
        ?, ?,
        ?, ?, ?, ?,
        ?, ?, ?,
        ?, ?, ?, ?,
        ?, ?,
        ?, ?,
        ?, ?, ?
    )
    ON CONFLICT (platform, platform_job_id) DO NOTHING
"""


async def save_job(db: Database, job: Job) -> None:
    """
    Persist a Job to the database.

    Uses INSERT … ON CONFLICT DO NOTHING so that re-discovering the
    same job (same platform + platform_job_id) is silently ignored.
    """
    row = _job_to_row(job)
    await db.execute(_INSERT_SQL, row)
    await db.commit()
    logger.debug("Saved job %s (%s/%s)", job.id, job.platform, job.platform_job_id)


async def get_job(db: Database, job_id: str) -> Job | None:
    """Retrieve a Job by its internal UUID."""
    row = await db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    return _row_to_job(row) if row else None


async def get_job_by_platform_id(
    db: Database, platform: str, platform_job_id: str
) -> Job | None:
    """
    Look up a Job by its platform-native identifier.

    Used by the deduplication agent to check whether a discovered job
    has already been persisted.
    """
    row = await db.fetch_one(
        "SELECT * FROM jobs WHERE platform = ? AND platform_job_id = ?",
        (platform, platform_job_id),
    )
    return _row_to_job(row) if row else None


async def update_job_status(db: Database, job_id: str, status: str) -> None:
    """Update the pipeline status of a single job."""
    await db.execute(
        "UPDATE jobs SET status = ? WHERE id = ?",
        (status, job_id),
    )
    await db.commit()
    logger.debug("Updated job %s status -> %s", job_id, status)


async def list_jobs(
    db: Database,
    status: str | None = None,
    limit: int = 50,
) -> list[Job]:
    """
    Return jobs ordered by discovered_at descending.

    Optionally filtered by pipeline status (e.g., 'discovered', 'scored').
    """
    if status is not None:
        rows = await db.fetch_all(
            "SELECT * FROM jobs WHERE status = ? ORDER BY discovered_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = await db.fetch_all(
            "SELECT * FROM jobs ORDER BY discovered_at DESC LIMIT ?",
            (limit,),
        )
    return [_row_to_job(row) for row in rows]
