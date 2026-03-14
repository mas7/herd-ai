"""
Mission Control client — sends periodic heartbeats and ad-hoc events to the
herd-specific Mission Control fork so departments appear live in the UI.

Usage (called once from FastAPI lifespan):
    client = MissionControlClient(base_url, api_key, "recon")
    await client.start()
    ...
    await client.stop()

Degrades gracefully: if base_url or api_key are not set, all calls are
no-ops and a warning is logged.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 30  # seconds
_TIMEOUT = httpx.Timeout(10.0)


class HeartbeatPayload(BaseModel, frozen=True):
    department: str
    status: str
    metrics: dict[str, float]


class EventPayload(BaseModel, frozen=True):
    event_type: str
    source: str
    target: str | None
    data: dict[str, str | int | float | bool | None]


class MissionControlClient:
    """
    Thin async client for the herd-fork Mission Control REST API.

    Sends a heartbeat on the first call (which auto-creates the department)
    and repeats every 30 seconds. Supports fire-and-forget event emission.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        dept_name: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._dept_name = dept_name
        self._heartbeat_task: asyncio.Task[None] | None = None

    @property
    def _enabled(self) -> bool:
        return bool(self._base_url and self._api_key)

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key, "Content-Type": "application/json"}

    async def start(self) -> None:
        """Start the heartbeat loop. No-op if credentials are missing."""
        if not self._enabled:
            logger.warning(
                "MissionControlClient: MC_BASE_URL or MC_API_KEY not set"
                " — skipping department '%s'",
                self._dept_name,
            )
            return
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name=f"mc-heartbeat-{self._dept_name}",
        )

    async def stop(self) -> None:
        """Cancel the heartbeat task and wait for it to finish."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        self._heartbeat_task = None

    async def send_event(
        self,
        event_type: str,
        source: str,
        data: dict[str, str | int | float | bool | None],
        target: str | None = None,
    ) -> None:
        """
        Fire-and-forget POST /api/herd/events.

        Schedules the HTTP call as a background task so the caller is never
        blocked. No-op if credentials are missing.
        """
        if not self._enabled:
            return
        payload = EventPayload(
            event_type=event_type,
            source=source,
            target=target,
            data=data,
        )
        asyncio.create_task(
            self._post_event(payload),
            name=f"mc-event-{event_type}-{source}",
        )

    async def _heartbeat_loop(self) -> None:
        """Send heartbeats every 30 seconds until cancelled."""
        url = f"{self._base_url}/api/herd/heartbeat"
        payload = HeartbeatPayload(
            department=self._dept_name,
            status="idle",
            metrics={},
        )
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.post(
                        url,
                        content=payload.model_dump_json(),
                        headers=self._headers,
                    )
                    resp.raise_for_status()
                    logger.debug(
                        "Mission Control: heartbeat sent for department '%s'",
                        self._dept_name,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug(
                    "Mission Control: heartbeat failed for department '%s'",
                    self._dept_name,
                    exc_info=True,
                )

    async def _post_event(self, payload: EventPayload) -> None:
        """POST /api/herd/events — called as a background task."""
        url = f"{self._base_url}/api/herd/events"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    url,
                    content=payload.model_dump_json(),
                    headers=self._headers,
                )
                resp.raise_for_status()
                logger.debug(
                    "Mission Control: event '%s' from '%s' delivered",
                    payload.event_type,
                    payload.source,
                )
        except Exception:
            logger.debug(
                "Mission Control: event '%s' from '%s' failed",
                payload.event_type,
                payload.source,
                exc_info=True,
            )


def make_department_clients() -> list[MissionControlClient]:
    """
    Build one MissionControlClient per herd-ai department.

    Reads MC_BASE_URL and MC_API_KEY from the environment.
    Returns an empty list if either is not set.
    """
    base_url = os.environ.get("MC_BASE_URL", "")
    api_key = os.environ.get("MC_API_KEY", "")
    if not base_url or not api_key:
        logger.info(
            "Mission Control: MC_BASE_URL/MC_API_KEY not configured"
            " — department heartbeats disabled"
        )
        return []

    departments = [
        "recon",
        "analyst",
        "bizdev",
        "content",
        "execution",
    ]
    return [MissionControlClient(base_url, api_key, name) for name in departments]
