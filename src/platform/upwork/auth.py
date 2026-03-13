"""
Upwork session and cookie management.

Persists browser cookies to a JSON file so the session survives
process restarts. Uses Playwright browser context for all cookie I/O.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext

logger = logging.getLogger(__name__)

_LOGIN_URL = "https://www.upwork.com/ab/account-security/login"
_VERIFY_URL = "https://www.upwork.com/nx/find-work/"
_COOKIE_DOMAIN = ".upwork.com"


class UpworkAuth:
    """
    Manages Upwork authentication via browser cookies.

    Stores the session in a local JSON file and restores it on each run,
    avoiding repeated logins. Browser-level cookie injection is used so
    that every subsequent Playwright request is authenticated.
    """

    def __init__(
        self,
        browser_context: BrowserContext,
        session_file: Path = Path("./data/upwork_session.json"),
    ) -> None:
        self._context = browser_context
        self._session_file = session_file
        self._session_file.parent.mkdir(parents=True, exist_ok=True)

    async def login(self, email: str, password: str) -> bool:
        """
        Perform a fresh login via the Upwork login page.

        Returns True on success. On success, persists the resulting
        session cookies to disk.
        """
        page = await self._context.new_page()
        try:
            await page.goto(_LOGIN_URL, wait_until="networkidle")

            # Fill username step
            await page.fill('input[name="login[username]"]', email)
            await page.click('button[data-test="submit"]')
            await page.wait_for_load_state("networkidle")

            # Fill password step
            await page.fill('input[name="login[password]"]', password)
            await page.click('button[data-test="submit"]')
            await page.wait_for_load_state("networkidle")

            current_url = page.url
            if "find-work" in current_url or "home" in current_url:
                logger.info("Upwork login successful for %s", email)
                await self.save_session()
                return True

            logger.warning("Login may have failed — landed on %s", current_url)
            return False
        except Exception:
            logger.exception("Login failed for %s", email)
            return False
        finally:
            await page.close()

    async def load_session(self) -> bool:
        """
        Load persisted cookies into the browser context.

        Returns True if cookies were loaded from disk. Validity must
        still be confirmed with `is_session_valid()`.
        """
        if not self._session_file.exists():
            logger.debug("No session file found at %s", self._session_file)
            return False

        try:
            raw = self._session_file.read_text(encoding="utf-8")
            cookies: list[dict] = json.loads(raw)
            await self._context.add_cookies(cookies)
            logger.info("Loaded %d cookies from %s", len(cookies), self._session_file)
            return True
        except (json.JSONDecodeError, KeyError, OSError):
            logger.exception("Failed to load session from %s", self._session_file)
            return False

    async def save_session(self) -> None:
        """Persist current browser cookies to disk."""
        cookies = await self._context.cookies()
        self._session_file.write_text(
            json.dumps(cookies, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("Saved %d cookies to %s", len(cookies), self._session_file)

    async def is_session_valid(self) -> bool:
        """
        Probe the Upwork find-work page to verify the session is active.

        A redirect to the login page or a 401/403 response indicates
        the session has expired.
        """
        page = await self._context.new_page()
        try:
            response = await page.goto(_VERIFY_URL, wait_until="networkidle")
            if response is None:
                return False

            is_login_page = "login" in page.url or "account-security" in page.url
            if is_login_page or response.status in (401, 403):
                logger.info("Upwork session is invalid or expired")
                return False

            logger.debug("Upwork session is valid (url=%s)", page.url)
            return True
        except Exception:
            logger.exception("Session validation check failed")
            return False
        finally:
            await page.close()
