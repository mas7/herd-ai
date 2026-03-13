"""
RAG retrieval for the Content department.

Stores past proposals in a ChromaDB collection and retrieves the most
relevant ones for a given job. Used by the writer to match tone and
structure to proven past proposals.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import chromadb
from chromadb.utils import embedding_functions

if TYPE_CHECKING:
    from src.models.job import Job

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "past_proposals"
_N_RESULTS = 5


class ProposalStore:
    """
    ChromaDB-backed store for past proposals.

    Supports adding proposals (for seeding) and querying for similar ones
    given a job description.
    """

    def __init__(self, chroma_path: str, embedding_model: str) -> None:
        self._client = chromadb.PersistentClient(path=chroma_path)
        self._ef = embedding_functions.DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=self._ef,
        )
        self._embedding_model = embedding_model
        logger.info(
            "ProposalStore initialised — %d documents in collection",
            self._collection.count(),
        )

    def add_proposal(
        self,
        proposal_id: str,
        cover_letter: str,
        job_title: str,
        job_skills: list[str],
        outcome: str,
    ) -> None:
        """
        Persist a past proposal for future retrieval.

        outcome should be one of: "won", "lost", "no_response".
        """
        document = f"Job: {job_title}\nSkills: {', '.join(job_skills)}\n\n{cover_letter}"
        self._collection.upsert(
            ids=[proposal_id],
            documents=[document],
            metadatas=[
                {
                    "proposal_id": proposal_id,
                    "job_title": job_title,
                    "skills": ", ".join(job_skills),
                    "outcome": outcome,
                }
            ],
        )

    def query(self, job: "Job", n_results: int = _N_RESULTS) -> list[dict]:
        """
        Return the n most similar past proposals to the given job.

        Each result dict contains: document, metadata, distance.
        Prioritises won proposals by querying twice as many then filtering.
        """
        total = self._collection.count()
        if total == 0:
            return []

        fetch = min(n_results * 2, total)
        query_text = (
            f"{job.title}\n"
            f"Skills: {', '.join(job.required_skills or [])}\n"
            f"{job.description[:500]}"
        )

        results = self._collection.query(
            query_texts=[query_text],
            n_results=fetch,
            include=["documents", "metadatas", "distances"],
        )

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]

        combined = [
            {"document": d, "metadata": m, "distance": dist}
            for d, m, dist in zip(docs, metas, dists)
        ]

        # Sort: wins first, then by distance
        won = [r for r in combined if r["metadata"].get("outcome") == "won"]
        rest = [r for r in combined if r["metadata"].get("outcome") != "won"]
        ordered = (won + rest)[:n_results]

        logger.debug(
            "RAG query for job '%s' → %d results (%d won)",
            job.title,
            len(ordered),
            len(won),
        )
        return ordered
