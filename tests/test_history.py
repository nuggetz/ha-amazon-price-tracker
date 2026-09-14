"""The price history behind a percentage threshold.

Issue #10: "percentage" needs a reference price, and the one the request asks
for is the product's usual price. These tests pin the properties that make that
reference usable — one value per day, outliers absorbed, a window that empties,
and a warm-up that has to be passed before anything is armed.
"""
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.amazon_price_tracker.const import (
    HISTORY_MIN_DAYS,
    HISTORY_WINDOW_DAYS,
)
from custom_components.amazon_price_tracker.history import PriceHistory

ASIN = "B09FKN79QR"
DAY_ONE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
async def history(hass, hass_storage):
    store = PriceHistory(hass)
    await store.async_load()
    return store


def _feed(store: PriceHistory, prices, start=DAY_ONE) -> datetime:
    """One sample per day, returning the day after the last one."""
    for offset, price in enumerate(prices):
        store.async_add_sample(ASIN, price, now=start + timedelta(days=offset))
    return start + timedelta(days=len(prices))


async def test_a_day_of_samples_becomes_one_value(history):
    """Six fetches in a day are one observation, not six."""
    for hour in range(0, 24, 4):
        history.async_add_sample(ASIN, 100.0, now=DAY_ONE + timedelta(hours=hour))

    # The day only closes when a sample from the next one arrives.
    history.async_add_sample(ASIN, 90.0, now=DAY_ONE + timedelta(days=1))

    assert history.coverage_days(ASIN, now=DAY_ONE + timedelta(days=1)) == 1


async def test_the_day_in_progress_does_not_move_the_reference(history):
    today = _feed(history, [100.0] * HISTORY_MIN_DAYS)
    assert history.reference_price(ASIN, now=today) == 100.0

    # A collapse today must not drag the reference down under the price while
    # the comparison is being made against it.
    for hour in range(3):
        history.async_add_sample(ASIN, 10.0, now=today + timedelta(hours=hour))

    assert history.reference_price(ASIN, now=today) == 100.0


async def test_the_reference_waits_for_enough_days(history):
    almost = _feed(history, [100.0] * (HISTORY_MIN_DAYS - 1))
    assert history.reference_price(ASIN, now=almost) is None
    assert history.coverage_days(ASIN, now=almost) == HISTORY_MIN_DAYS - 1

    enough = _feed(history, [100.0], start=almost)
    assert history.reference_price(ASIN, now=enough) == 100.0


async def test_a_misparse_within_a_day_is_absorbed(history):
    """Issue #8 put another product's price in a sample; a day survives one."""
    for hour, price in enumerate([80.0, 80.0, 3.99, 80.0]):
        history.async_add_sample(ASIN, price, now=DAY_ONE + timedelta(hours=hour))

    rest = _feed(history, [80.0] * HISTORY_MIN_DAYS, start=DAY_ONE + timedelta(days=1))

    assert history.reference_price(ASIN, now=rest) == 80.0


async def test_one_wrong_day_does_not_move_the_median(history):
    """A mean would follow the outlier; the median is why it is a median."""
    prices = [100.0] * (HISTORY_MIN_DAYS - 1) + [3.0]
    today = _feed(history, prices)

    assert history.reference_price(ASIN, now=today) == 100.0


async def test_days_fall_out_of_the_window(history):
    today = _feed(history, [100.0] * HISTORY_MIN_DAYS)
    assert history.reference_price(ASIN, now=today) == 100.0

    # Nothing recorded for long enough that the window empties: the threshold
    # disarms instead of being computed from stale prices.
    much_later = today + timedelta(days=HISTORY_WINDOW_DAYS + 1)
    assert history.coverage_days(ASIN, now=much_later) == 0
    assert history.reference_price(ASIN, now=much_later) is None


async def test_a_price_drop_moves_the_reference_slowly(history):
    """The reference is a median, so a few cheap days do not become "usual"."""
    today = _feed(history, [100.0] * 20)
    cheaper = _feed(history, [50.0] * 5, start=today)

    assert history.reference_price(ASIN, now=cheaper) == 100.0


async def test_removing_a_product_forgets_it(history):
    today = _feed(history, [100.0] * HISTORY_MIN_DAYS)
    assert history.reference_price(ASIN, now=today) == 100.0

    history.async_remove(ASIN)

    assert history.coverage_days(ASIN, now=today) == 0
    assert history.reference_price(ASIN, now=today) is None


async def test_history_survives_a_reload(hass, hass_storage):
    first = PriceHistory(hass)
    await first.async_load()
    today = _feed(first, [100.0] * HISTORY_MIN_DAYS)
    await first._store.async_save(first._data_to_save())

    second = PriceHistory(hass)
    await second.async_load()

    assert second.reference_price(ASIN, now=today) == 100.0
