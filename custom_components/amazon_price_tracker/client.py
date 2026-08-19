"""Shared httpx client construction.

`httpx.AsyncClient()` loads the CA bundle (`load_verify_locations`) while it is
being constructed. That is a blocking file read, and Home Assistant flags it
when it happens inside the event loop. Every client in this integration is
therefore built through `async_create_client`, which does the construction in
the executor.
"""

from __future__ import annotations

from functools import partial

import httpx

from homeassistant.core import HomeAssistant

from .const import DEFAULT_MARKETPLACE, DOMAIN_CONFIG, HEADERS, REQUEST_TIMEOUT


def build_headers(marketplace: str) -> dict[str, str]:
    """Return the base headers with the marketplace's Accept-Language."""
    config = DOMAIN_CONFIG.get(marketplace, DOMAIN_CONFIG[DEFAULT_MARKETPLACE])
    return {**HEADERS, "Accept-Language": config["language"]}


async def async_create_client(
    hass: HomeAssistant,
    marketplace: str,
    timeout: float = REQUEST_TIMEOUT,
) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient off the event loop."""
    return await hass.async_add_executor_job(
        partial(
            httpx.AsyncClient,
            headers=build_headers(marketplace),
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
        )
    )
