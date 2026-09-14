"""The price drop event, and when it must stay silent.

Issue #9: covering every product used to mean triggering on `state_changed` and
filtering in the condition, which drops the run that matters once the queue
fills. The integration fires its own event instead.
"""
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.amazon_price_tracker.const import (
    COORDINATORS,
    DOMAIN,
    EVENT_PRICE_DROP,
    HISTORY_MIN_DAYS,
    STATUS_COLLECTING,
    STATUS_READY,
    STORAGE_KEY,
    STORAGE_VERSION,
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


async def _setup(hass, threshold=None, price="299,99", discount=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Product",
        data={
            "asin": "B09FKN79QR",
            "name": "Test Product",
            "marketplace": "amazon.it",
            "alert_threshold": threshold,
            "alert_discount_pct": discount,
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


# ---------------------------------------------------------------------------
# Percentage thresholds (issue #10)
# ---------------------------------------------------------------------------

def _seed_history(hass_storage, daily_price, days=HISTORY_MIN_DAYS):
    """A product that has been tracked long enough to have a usual price."""
    today = dt_util.utcnow().date()
    hass_storage[STORAGE_KEY] = {
        "version": STORAGE_VERSION,
        "data": {
            "B09FKN79QR": {
                "days": {
                    (today - timedelta(days=offset)).isoformat(): daily_price
                    for offset in range(1, days + 1)
                },
                "pending_day": None,
                "pending": [],
            }
        },
    }


async def test_a_percentage_fires_against_the_usual_price(hass, events, hass_storage):
    _seed_history(hass_storage, 300.0)

    entry = await _setup(hass, discount=20, price="299,99")
    assert events == []

    await _refresh(hass, entry, "199,99")

    assert len(events) == 1
    data = events[0].data
    assert data["price"] == 199.99
    # Resolved to money: an automation written for a fixed threshold still works
    assert data["alert_threshold"] == 240.0
    assert data["reference_price"] == 300.0
    assert data["discount_pct"] == 20
    assert data["threshold_mode"] == "percent"


async def test_a_price_between_reference_and_threshold_stays_quiet(
    hass, events, hass_storage
):
    """20% off means 20% off — cheaper than usual is not the same as cheap."""
    _seed_history(hass_storage, 300.0)

    entry = await _setup(hass, discount=20, price="299,99")
    await _refresh(hass, entry, "269,99")

    assert events == []


async def test_a_percentage_stays_quiet_while_collecting(hass, events):
    """No reference, no comparison — not even for an absurd price."""
    entry = await _setup(hass, discount=20, price="299,99")
    await _refresh(hass, entry, "1,99")

    assert events == []


async def test_an_incomplete_window_does_not_arm(hass, events, hass_storage):
    _seed_history(hass_storage, 300.0, days=HISTORY_MIN_DAYS - 1)

    entry = await _setup(hass, discount=20, price="299,99")
    await _refresh(hass, entry, "1,99")

    assert events == []


async def test_the_sensor_says_why_it_is_quiet(hass, events):
    await _setup(hass, discount=20, price="299,99")

    state = hass.states.get("sensor.test_product")
    assert state.attributes["reference_status"] == STATUS_COLLECTING
    assert state.attributes["reference_price"] is None
    assert state.attributes["alert_threshold"] is None
    assert state.attributes["reference_days_required"] == HISTORY_MIN_DAYS


async def test_an_armed_sensor_shows_the_reference(hass, events, hass_storage):
    _seed_history(hass_storage, 300.0)

    await _setup(hass, discount=20, price="299,99")

    state = hass.states.get("sensor.test_product")
    assert state.attributes["reference_status"] == STATUS_READY
    assert state.attributes["reference_price"] == 300.0
    assert state.attributes["alert_threshold"] == 240.0
    assert state.attributes["reference_days"] == HISTORY_MIN_DAYS


async def test_a_fixed_threshold_gains_no_attributes(hass, events):
    """The percentage attributes would be permanently empty and recorded anyway."""
    await _setup(hass, threshold=200.0, price="299,99")

    state = hass.states.get("sensor.test_product")
    assert "reference_status" not in state.attributes
    assert "discount_pct" not in state.attributes
    assert state.attributes["alert_threshold"] == 200.0
