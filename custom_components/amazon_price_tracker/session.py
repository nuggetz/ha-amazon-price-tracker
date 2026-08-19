"""One shared browsing session per Amazon marketplace.

Before 0.4.0 every tracked product owned its own `httpx.AsyncClient`, so an
installation with twenty products looked to Amazon like twenty unrelated
visitors from a single IP, each landing cold on a product page having never
loaded a homepage. That is a strong bot signal and it is what this module
exists to remove.

An `AmazonSession` owns, per marketplace:

- one client and one cookie jar, so every product shares a coherent session;
- a lock, so requests are serialised and spaced instead of bursting;
- a warm-up, so the first product request arrives with session cookies and a
  plausible `Referer`;
- a circuit breaker, so one block silences the whole marketplace rather than
  letting the other products collect a wall each.
"""

from __future__ import annotations

import asyncio
import logging
import random
from functools import partial

import httpx

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant

from .const import (
    BLOCK_COOLDOWN_JITTER,
    BLOCK_COOLDOWN_SECONDS,
    DEFAULT_MARKETPLACE,
    DOMAIN,
    DOMAIN_CONFIG,
    HEADERS,
    MAX_REQUEST_SPACING,
    MAX_WARMUP_PAUSE,
    MIN_REQUEST_SPACING,
    MIN_WARMUP_PAUSE,
    REQUEST_TIMEOUT,
    SESSIONS,
)
from .exceptions import AmazonBlockedError

_LOGGER = logging.getLogger(__name__)


def build_headers(marketplace: str) -> dict[str, str]:
    """Return the base headers with the marketplace's Accept-Language."""
    config = DOMAIN_CONFIG.get(marketplace, DOMAIN_CONFIG[DEFAULT_MARKETPLACE])
    return {**HEADERS, "Accept-Language": config["language"]}


class AmazonSession:
    """A single browsing session shared by every product on one marketplace."""

    def __init__(self, hass: HomeAssistant, marketplace: str) -> None:
        self.hass = hass
        self.marketplace = marketplace
        self.home_url = f"https://www.{marketplace}/"
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._last_request: float | None = None
        self._warmed = False
        self._blocked_until: float | None = None

    # -- circuit breaker ---------------------------------------------------

    @property
    def is_blocked(self) -> bool:
        if self._blocked_until is None:
            return False
        if self.hass.loop.time() >= self._blocked_until:
            self._blocked_until = None
            return False
        return True

    @property
    def cooldown_remaining(self) -> float:
        if self._blocked_until is None:
            return 0.0
        return max(0.0, self._blocked_until - self.hass.loop.time())

    async def async_note_block(self) -> None:
        """Put the marketplace in cooldown and discard the burnt session."""
        cooldown = BLOCK_COOLDOWN_SECONDS + random.uniform(0, BLOCK_COOLDOWN_JITTER)
        self._blocked_until = self.hass.loop.time() + cooldown
        _LOGGER.warning(
            "Amazon blocked %s — pausing every product on this marketplace for "
            "%d minutes",
            self.marketplace,
            round(cooldown / 60),
        )
        # The cookies that got walled are worth nothing; start clean afterwards.
        await self.async_close()

    # -- client lifecycle --------------------------------------------------

    async def _async_get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # httpx reads the CA bundle while constructing the client, which is
            # blocking and must not happen on the event loop.
            self._client = await self.hass.async_add_executor_job(
                partial(
                    httpx.AsyncClient,
                    headers=build_headers(self.marketplace),
                    follow_redirects=True,
                    timeout=httpx.Timeout(REQUEST_TIMEOUT),
                )
            )
            self._warmed = False
        return self._client

    async def async_close(self) -> None:
        self._warmed = False
        self._last_request = None
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    # -- request pacing ----------------------------------------------------

    async def _async_space_requests(self) -> None:
        """Keep a randomised gap between consecutive requests."""
        if self._last_request is None:
            return
        spacing = random.uniform(MIN_REQUEST_SPACING, MAX_REQUEST_SPACING)
        elapsed = self.hass.loop.time() - self._last_request
        if (wait := spacing - elapsed) > 0:
            await asyncio.sleep(wait)

    async def _async_warm_up(self, client: httpx.AsyncClient) -> None:
        """Load the homepage once to pick up session cookies."""
        if self._warmed:
            return
        # Marked warmed up front: a failed warm-up must not retry on every
        # product, and the product request works without cookies anyway.
        self._warmed = True
        try:
            await client.get(self.home_url)
        except httpx.HTTPError as err:
            _LOGGER.debug("Warm-up of %s failed: %s", self.marketplace, err)
            return
        self._last_request = self.hass.loop.time()
        await asyncio.sleep(random.uniform(MIN_WARMUP_PAUSE, MAX_WARMUP_PAUSE))

    # -- public API --------------------------------------------------------

    async def async_get(self, url: str) -> httpx.Response:
        """Fetch a URL on this marketplace's shared session.

        Raises AmazonBlockedError without touching the network while the
        marketplace is in cooldown.
        """
        if self.is_blocked:
            raise AmazonBlockedError(
                f"{self.marketplace} is in cooldown for another "
                f"{round(self.cooldown_remaining / 60)} min after a block"
            )

        async with self._lock:
            # The lock may have been held through the whole cooldown by a queue
            # of waiting products; re-check before spending a request.
            if self.is_blocked:
                raise AmazonBlockedError(
                    f"{self.marketplace} is in cooldown for another "
                    f"{round(self.cooldown_remaining / 60)} min after a block"
                )

            client = await self._async_get_client()
            await self._async_warm_up(client)
            await self._async_space_requests()

            response = await client.get(
                url,
                headers={
                    "Referer": self.home_url,
                    "Sec-Fetch-Site": "same-origin",
                },
            )
            self._last_request = self.hass.loop.time()
            return response


def async_get_session(hass: HomeAssistant, marketplace: str) -> AmazonSession:
    """Return the shared session for a marketplace, creating it if needed."""
    sessions: dict[str, AmazonSession] = hass.data.setdefault(DOMAIN, {}).setdefault(
        SESSIONS, {}
    )
    if marketplace not in sessions:
        session = sessions[marketplace] = AmazonSession(hass, marketplace)

        async def _close_on_stop(_event: Event) -> None:
            await session.async_close()

        # A session can outlive every config entry — the config flow creates one
        # before any entry exists — so it needs its own shutdown hook.
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _close_on_stop)
    return sessions[marketplace]


async def async_close_sessions(hass: HomeAssistant) -> None:
    """Close every open session."""
    sessions: dict[str, AmazonSession] = hass.data.get(DOMAIN, {}).get(SESSIONS, {})
    for session in list(sessions.values()):
        await session.async_close()
    sessions.clear()
