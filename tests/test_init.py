"""Tests for entry setup behaviour when Amazon blocks us."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amazon_price_tracker.const import DOMAIN, SESSIONS
from custom_components.amazon_price_tracker.exceptions import AmazonBlockedError

# Amazon's "Continue shopping" wall, served with HTTP 200
BLOCKED_PAGE = """
<!DOCTYPE html><html lang="it"><head><title>Amazon.it</title></head><body>
<form method="get" action="/errors_page/validateCaptcha"></form>
</body></html>
"""


@pytest.fixture
def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Product",
        data={
            "asin": "B09FKN79QR",
            "name": "Test Product",
            "marketplace": "amazon.it",
            "alert_threshold": None,
        },
        unique_id="B09FKN79QR",
    )
    entry.add_to_hass(hass)
    return entry


def _response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.status_code = 200
    response.raise_for_status = MagicMock()
    return response


async def test_block_during_setup_still_loads_the_entry(hass, entry):
    """A wall must not fail setup — that hands control to HA's retry ladder.

    See issue #1: failing here produced 40 retries in five hours instead of
    the 30 minute backoff the log promised.
    """
    with patch(
        "custom_components.amazon_price_tracker.session.AmazonSession.async_get",
        AsyncMock(return_value=_response(BLOCKED_PAGE)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.test_product").state == "unavailable"


async def test_network_failure_during_setup_still_retries(hass, entry):
    """A genuine connectivity problem must keep raising ConfigEntryNotReady."""
    with patch(
        "custom_components.amazon_price_tracker.session.AmazonSession.async_get",
        AsyncMock(side_effect=httpx.ConnectError("no route to host")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_wall_puts_the_whole_marketplace_in_cooldown(hass, entry):
    """One blocked product must silence the marketplace, not just itself."""
    with patch(
        "custom_components.amazon_price_tracker.session.AmazonSession.async_get",
        AsyncMock(return_value=_response(BLOCKED_PAGE)),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    session = hass.data[DOMAIN][SESSIONS]["amazon.it"]
    assert session.is_blocked is True

    # A second product on the same marketplace is refused without a request
    with pytest.raises(AmazonBlockedError):
        await session.async_get("https://www.amazon.it/dp/B0D6NMDNNX")
