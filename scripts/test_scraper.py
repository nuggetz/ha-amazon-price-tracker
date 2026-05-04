#!/usr/bin/env python3
"""Standalone scraper test — runs without Home Assistant installed.

Usage:
    python scripts/test_scraper.py B09FKN79QR
    python scripts/test_scraper.py B09FKN79QR B0D6NMDNNX
"""

import asyncio
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal HA stubs — must be registered before any component import so that
# __init__.py and coordinator.py can be loaded without homeassistant installed.
# ---------------------------------------------------------------------------
def _stub(*a, **kw):
    pass

class _DataUpdateCoordinator:
    def __init__(self, *a, **kw): pass
    def __class_getitem__(cls, item): return cls  # supports DataUpdateCoordinator[dict]

class _UpdateFailed(Exception):
    pass

_ha = types.ModuleType("homeassistant")
_ha_core = types.ModuleType("homeassistant.core")
_ha_helpers = types.ModuleType("homeassistant.helpers")
_ha_udc = types.ModuleType("homeassistant.helpers.update_coordinator")
_ha_ce = types.ModuleType("homeassistant.config_entries")

_ha_core.HomeAssistant = type("HomeAssistant", (), {})
_ha_udc.DataUpdateCoordinator = _DataUpdateCoordinator
_ha_udc.UpdateFailed = _UpdateFailed
_ha_ce.ConfigEntry = type("ConfigEntry", (), {})

sys.modules["homeassistant"] = _ha
sys.modules["homeassistant.core"] = _ha_core
sys.modules["homeassistant.helpers"] = _ha_helpers
sys.modules["homeassistant.helpers.update_coordinator"] = _ha_udc
sys.modules["homeassistant.config_entries"] = _ha_ce

# ---------------------------------------------------------------------------
# Now it is safe to import from the component
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx  # noqa: E402  (after sys.path manipulation)
from custom_components.amazon_price_tracker.const import HEADERS
from custom_components.amazon_price_tracker.coordinator import (
    AmazonCaptchaError,
    parse_product_page,
)


async def test_asin(asin: str) -> None:
    url = f"https://www.amazon.it/dp/{asin}"
    print(f"\n{'=' * 60}")
    print(f"ASIN : {asin}")
    print(f"URL  : {url}")

    async with httpx.AsyncClient(
        headers=HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
    ) as client:
        try:
            response = await client.get(url)
            print(f"HTTP : {response.status_code}")
        except httpx.HTTPError as err:
            print(f"ERROR: {err}")
            return

    if response.status_code != 200:
        print(f"RESULT: HTTP {response.status_code} — ASIN not found or unavailable on Amazon.it")
        return

    try:
        price, title, is_available = parse_product_page(response.text, asin)
    except AmazonCaptchaError:
        print("RESULT: CAPTCHA detected — try again later or change User-Agent")
        return

    print(f"Title    : {title}")
    if price is not None:
        print(f"Price    : {price} EUR")
    else:
        print("Price    : not found")
    print(f"Available: {is_available}")


async def main() -> None:
    asins = sys.argv[1:] if len(sys.argv) > 1 else ["B09FKN79QR"]
    for asin in asins:
        await test_asin(asin.strip().upper())


if __name__ == "__main__":
    asyncio.run(main())
