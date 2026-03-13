"""
Seed the ChromaDB proposal store with past proposals from the SQLite database.

Run once (or re-run to refresh) after the database has some proposal outcomes:
    python scripts/seed_proposals.py

This loads all proposals with a non-drafted status (won/lost/no_response/submitted)
from the proposals table and adds them to the ChromaDB collection so the
Content department can use them for RAG retrieval.

Usage:
    python scripts/seed_proposals.py [--chroma-path PATH] [--db-path PATH]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.db import Database
from src.departments.content.rag import ProposalStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = ("won", "lost", "no_response", "submitted")


async def _fetch_proposals(db: Database) -> list[dict]:
    placeholders = ", ".join("?" * len(_TERMINAL_STATUSES))
    rows = await db.fetch_all(
        f"""
        SELECT p.id, p.cover_letter, p.status, j.title, j.required_skills
        FROM proposals p
        JOIN jobs j ON j.id = p.job_id
        WHERE p.status IN ({placeholders})
          AND p.cover_letter IS NOT NULL
          AND p.cover_letter != ''
        ORDER BY p.created_at DESC
        """,
        _TERMINAL_STATUSES,
    )
    return rows


async def seed(chroma_path: str, db_path: str) -> None:
    db = Database(db_path)
    await db.connect()

    rows = await _fetch_proposals(db)
    await db.close()

    if not rows:
        logger.info("No terminal proposals found in DB — nothing to seed.")
        return

    store = ProposalStore(chroma_path=chroma_path, embedding_model="")

    added = 0
    for row in rows:
        skills_raw = row.get("required_skills") or ""
        skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
        outcome = row.get("status", "unknown")
        # Map submitted → no_response for simplicity (no confirmed win/loss yet)
        if outcome == "submitted":
            outcome = "no_response"
        store.add_proposal(
            proposal_id=row["id"],
            cover_letter=row["cover_letter"],
            job_title=row.get("title", ""),
            job_skills=skills,
            outcome=outcome,
        )
        added += 1

    logger.info("Seeded %d proposals into ChromaDB at %s", added, chroma_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed ChromaDB with past proposals")
    parser.add_argument(
        "--chroma-path",
        default="./data/chromadb",
        help="Path to ChromaDB persistent storage (default: ./data/chromadb)",
    )
    parser.add_argument(
        "--db-path",
        default="./data/herd.db",
        help="Path to SQLite database (default: ./data/herd.db)",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.chroma_path, args.db_path))


if __name__ == "__main__":
    main()
