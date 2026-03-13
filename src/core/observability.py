"""
Observability bootstrap — Arize Phoenix (LiteLLM + CrewAI tracing).

Call init_observability() once at process startup (API lifespan or CLI entry
point). After that every LiteLLM call is automatically traced to Phoenix and
every CrewAI agent run is automatically traced to Phoenix.

Environment variables (all optional — observability degrades gracefully):
    PHOENIX_COLLECTOR_ENDPOINT  OTLP HTTP endpoint (default: http://localhost:6006/v1/traces)
    PHOENIX_PROJECT_NAME        Project name in Phoenix UI (default: herd-ai)
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def init_observability() -> None:
    """Initialise Arize Phoenix tracing for LiteLLM and CrewAI."""
    _init_phoenix()


def _init_phoenix() -> None:
    """
    Register Phoenix as the OpenTelemetry trace collector.

    Instruments both LiteLLM (all acompletion calls) and CrewAI (all agent
    and task runs) via OpenInference instrumentors. Both are traced to the
    same Phoenix project for unified visibility.

    Phoenix reads PHOENIX_COLLECTOR_ENDPOINT and PHOENIX_PROJECT_NAME
    automatically from the environment.
    """
    endpoint = os.environ.get(
        "PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces"
    )
    project = os.environ.get("PHOENIX_PROJECT_NAME", "herd-ai")

    try:
        from arize.otel import register
        from openinference.instrumentation.crewai import CrewAIInstrumentor
        from openinference.instrumentation.litellm import LiteLLMInstrumentor

        tracer_provider = register(
            project_name=project,
            endpoint=endpoint,
        )

        LiteLLMInstrumentor().instrument(tracer_provider=tracer_provider)
        CrewAIInstrumentor().instrument(
            skip_dep_check=True,
            tracer_provider=tracer_provider,
        )

        logger.info(
            "Phoenix tracing enabled — project=%s endpoint=%s", project, endpoint
        )
    except Exception:
        logger.exception("Failed to initialise Phoenix tracing")
