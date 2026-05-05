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
# all component modules can be loaded without homeassistant installed.
# ---------------------------------------------------------------------------
class _DataUpdateCoordinator:
    def __init__(self, *a, **kw): pass
    def __class_getitem__(cls, item): return cls

class _UpdateFailed(Exception):
    pass

def _noop(*a, **kw): pass

_ha           = types.ModuleType("homeassistant")
_ha_core      = types.ModuleType("homeassistant.core")
_ha_helpers   = types.ModuleType("homeassistant.helpers")
_ha_udc       = types.ModuleType("homeassistant.helpers.update_coordinator")
_ha_cv        = types.ModuleType("homeassistant.helpers.config_validation")
_ha_er        = types.ModuleType("homeassistant.helpers.entity_registry")
_ha_ce        = types.ModuleType("homeassistant.config_entries")
_ha_df        = types.ModuleType("homeassistant.data_entry_flow")
_ha_sensor    = types.ModuleType("homeassistant.components.sensor")
_ha_devreg    = types.ModuleType("homeassistant.helpers.device_registry")
_ha_ep        = types.ModuleType("homeassistant.helpers.entity_platform")

_ha_core.HomeAssistant   = type("HomeAssistant", (), {})
_ha_core.ServiceCall     = type("ServiceCall", (), {"data": {}})
_ha_core.callback        = lambda f: f

_ha_udc.DataUpdateCoordinator = _DataUpdateCoordinator
_ha_udc.UpdateFailed          = _UpdateFailed

_ha_cv.entity_ids = _noop

_ha_ce.ConfigEntry   = type("ConfigEntry", (), {})
_ha_ce.OptionsFlow   = type("OptionsFlow", (), {})
_ha_ce.ConfigFlow    = type("ConfigFlow", (), {})

_ha_df.FlowResult = dict

_ha_sensor.SensorDeviceClass  = type("SensorDeviceClass",  (), {"MONETARY": "monetary"})
_ha_sensor.SensorStateClass   = type("SensorStateClass",   (), {"MEASUREMENT": "measurement"})
_ha_sensor.RestoreSensor      = type("RestoreSensor",      (), {})

_ha_devreg.DeviceEntryType = type("DeviceEntryType", (), {"SERVICE": "service"})
_ha_devreg.DeviceInfo      = dict

_ha_ep.AddEntitiesCallback = _noop

for _name, _mod in [
    ("homeassistant",                              _ha),
    ("homeassistant.core",                         _ha_core),
    ("homeassistant.helpers",                      _ha_helpers),
    ("homeassistant.helpers.update_coordinator",   _ha_udc),
    ("homeassistant.helpers.config_validation",    _ha_cv),
    ("homeassistant.helpers.entity_registry",      _ha_er),
    ("homeassistant.helpers.device_registry",      _ha_devreg),
    ("homeassistant.helpers.entity_platform",      _ha_ep),
    ("homeassistant.config_entries",               _ha_ce),
    ("homeassistant.data_entry_flow",              _ha_df),
    ("homeassistant.components",                   types.ModuleType("homeassistant.components")),
    ("homeassistant.components.sensor",            _ha_sensor),
]:
    sys.modules[_name] = _mod

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
        price, title, is_available, availability_text = parse_product_page(
            response.text, asin, european_format=True
        )
    except AmazonCaptchaError:
        print("RESULT: CAPTCHA detected — try again later or change User-Agent")
        return

    print(f"Title             : {title}")
    if price is not None:
        print(f"Price             : {price}")
    else:
        print("Price             : not found")
    print(f"Available         : {is_available}")
    print(f"Availability text : {availability_text}")


async def main() -> None:
    asins = sys.argv[1:] if len(sys.argv) > 1 else ["B09FKN79QR"]
    for asin in asins:
        await test_asin(asin.strip().upper())


if __name__ == "__main__":
    asyncio.run(main())
