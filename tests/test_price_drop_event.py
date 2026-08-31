"""The price drop event, and when it must stay silent.

Issue #9: covering every product used to mean triggering on `state_changed` and
filtering in the condition, which drops the run that matters once the queue
fills. The integration fires its own event instead.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import State
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.amazon_price_tracker.const import (
    COORDINATORS,
    DOMAIN,
    EVENT_PRICE_DROP,
)

PAGE = """
<html><body>
<span id="productTitle">Test Product</span>
<div id="corePriceDisplay_desktop_feature_div">
  <span class="a-offscreen">€ {price}</span>
</div>
<div id="availability"><span>Disponibile</span></div>
</body></html>
"""


def _response(price: str) -> MagicMock:
    response = MagicMock()
    response.text = PAGE.format(price=price)
    response.status_code = 200
    response.raise_for_status = MagicMock()
    return response


@pytest.fixture
def events(hass):
    captured = []
    hass.bus.async_listen(EVENT_PRICE_DROP, captured.append)
    return captured


async def _setup(hass, threshold, price="299,99"):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Product",
        data={
            "asin": "B09FKN79QR",
            "name": "Test Product",
            "marketplace": "amazon.it",
            "alert_threshold": threshold,
        },
        unique_id="B09FKN79QR",
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.amazon_price_tracker.session.AmazonSession.async_get",
        AsyncMock(return_value=_response(price)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _refresh(hass, entry, price):
    coordinator = hass.data[DOMAIN][COORDINATORS][entry.entry_id]
    with patch(
        "custom_components.amazon_price_tracker.session.AmazonSession.async_get",
        AsyncMock(return_value=_response(price)),
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()


async def test_crossing_the_threshold_fires_the_event(hass, events):
    entry = await _setup(hass, threshold=200.0, price="299,99")
    assert events == []

    await _refresh(hass, entry, "149,99")

    assert len(events) == 1
    data = events[0].data
    assert data["entity_id"] == "sensor.test_product"
    assert data["asin"] == "B09FKN79QR"
    assert data["price"] == 149.99
    assert data["alert_threshold"] == 200.0
    assert data["currency"] == "EUR"
    assert data["marketplace"] == "amazon.it"
    assert data["url"].endswith("/dp/B09FKN79QR")


async def test_staying_below_does_not_fire_again(hass, events):
    """The alert is the crossing, not the condition — no alert every 4 hours."""
    entry = await _setup(hass, threshold=200.0, price="299,99")
    await _refresh(hass, entry, "149,99")
    await _refresh(hass, entry, "139,99")

    assert len(events) == 1


async def test_going_back_above_rearms_the_alert(hass, events):
    entry = await _setup(hass, threshold=200.0, price="299,99")
    await _refresh(hass, entry, "149,99")
    await _refresh(hass, entry, "249,99")
    await _refresh(hass, entry, "159,99")

    assert len(events) == 2
    assert [event.data["price"] for event in events] == [149.99, 159.99]


async def test_no_threshold_never_fires(hass, events):
    entry = await _setup(hass, threshold=None, price="299,99")
    await _refresh(hass, entry, "1,99")

    assert events == []


async def test_a_price_already_below_at_setup_fires_once(hass, events):
    """The first fetch lands before the entity subscribes — it must still count."""
    await _setup(hass, threshold=500.0, price="299,99")

    assert len(events) == 1
    assert events[0].data["price"] == 299.99


async def test_an_unavailable_price_rearms_the_alert(hass, events):
    """No featured offer clears the state, so the next drop is a fresh crossing."""
    entry = await _setup(hass, threshold=200.0, price="299,99")
    await _refresh(hass, entry, "149,99")

    blocked = MagicMock()
    blocked.text = "<html><body><span id='productTitle'>Test Product</span></body></html>"
    blocked.status_code = 200
    blocked.raise_for_status = MagicMock()
    coordinator = hass.data[DOMAIN][COORDINATORS][entry.entry_id]
    with patch(
        "custom_components.amazon_price_tracker.session.AmazonSession.async_get",
        AsyncMock(return_value=blocked),
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    await _refresh(hass, entry, "149,99")

    assert len(events) == 2


async def test_a_restart_below_the_threshold_stays_quiet(hass, events):
    """The drop was already announced before the restart — do not repeat it."""
    mock_restore_cache(
        hass,
        (State("sensor.test_product", "149.99", {"min_price": 149.99}),),
    )
    await _setup(hass, threshold=200.0, price="149,99")

    assert events == []
