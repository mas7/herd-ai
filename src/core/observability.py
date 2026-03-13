"""
Observability bootstrap — Langfuse + AgentOps.

Call init_observability() once at process startup (API lifespan or CLI entry
point). After that every LiteLLM call is automatically traced to Langfuse and
every CrewAI agent run is automatically traced to AgentOps.

Environment variables (all optional — observability degrades gracefully):
    LANGFUSE_PUBLIC_KEY   Langfuse project public key
    LANGFUSE_SECRET_KEY   Langfuse project secret key
    LANGFUSE_HOST         Self-hosted URL (default: https://cloud.langfuse.com)
    AGENTOPS_API_KEY      AgentOps project API key
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def init_observability() -> None:
    """Initialise Langfuse (via LiteLLM callback) and AgentOps."""
    _init_langfuse()
    _init_agentops()


def _init_langfuse() -> None:
    """
    Register Langfuse as a LiteLLM success/failure callback.

    LiteLLM reads LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and
    LANGFUSE_HOST automatically — no further config needed here.
    All acompletion() calls across every department will be traced.
    """
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    if not public_key:
        logger.info("Langfuse disabled — set LANGFUSE_PUBLIC_KEY to enable")
        return

    try:
        import litellm

        if "langfuse" not in litellm.success_callback:
            litellm.success_callback.append("langfuse")
        if "langfuse" not in litellm.failure_callback:
            litellm.failure_callback.append("langfuse")

        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        logger.info("Langfuse enabled — tracing all LLM calls → %s", host)
    except Exception:
        logger.exception("Failed to initialise Langfuse")


def _init_agentops() -> None:
    """
    Initialise AgentOps for CrewAI agent tracing.

    AgentOps auto-instruments CrewAI once init() is called — no changes
    needed in individual crew files.
    """
    api_key = os.environ.get("AGENTOPS_API_KEY")
    if not api_key:
        logger.info("AgentOps disabled — set AGENTOPS_API_KEY to enable")
        return

    try:
        import agentops

        agentops.init(
            api_key=api_key,
            default_tags=["herd-ai", "crewai"],
            auto_start_session=True,
        )
        logger.info("AgentOps enabled — tracing CrewAI agent runs")
    except Exception:
        logger.exception("Failed to initialise AgentOps")
