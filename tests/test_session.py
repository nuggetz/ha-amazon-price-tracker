"""Tests for the shared per-marketplace session (throttle, warm-up, breaker)."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from custom_components.amazon_price_tracker.const import (
    BLOCK_COOLDOWN_SECONDS,
    DOMAIN,
    SESSIONS,
)
from custom_components.amazon_price_tracker.exceptions import AmazonBlockedError
from custom_components.amazon_price_tracker.session import (
    AmazonSession,
    async_close_sessions,
    async_get_session,
)


@pytest.fixture
def session(hass):
    """A session whose client and sleeps are stubbed out."""
    session = AmazonSession(hass, "amazon.it")
    client = AsyncMock()
    client.is_closed = False
    client.get = AsyncMock(return_value=MagicMock(status_code=200))
    session._client = client
    return session


# ---------------------------------------------------------------------------
# Warm-up
# ---------------------------------------------------------------------------

async def test_first_request_warms_up_from_the_homepage(session):
    with patch("custom_components.amazon_price_tracker.session.asyncio.sleep"):
        await session.async_get("https://www.amazon.it/dp/B09FKN79QR")

    urls = [call.args[0] for call in session._client.get.await_args_list]
    assert urls == ["https://www.amazon.it/", "https://www.amazon.it/dp/B09FKN79QR"]


async def test_warm_up_happens_only_once(session):
    with patch("custom_components.amazon_price_tracker.session.asyncio.sleep"):
        await session.async_get("https://www.amazon.it/dp/AAAAAAAAAA")
        await session.async_get("https://www.amazon.it/dp/BBBBBBBBBB")

    urls = [call.args[0] for call in session._client.get.await_args_list]
    assert urls.count("https://www.amazon.it/") == 1


async def test_product_request_carries_a_referer(session):
    with patch("custom_components.amazon_price_tracker.session.asyncio.sleep"):
        await session.async_get("https://www.amazon.it/dp/B09FKN79QR")

    headers = session._client.get.await_args_list[-1].kwargs["headers"]
    assert headers["Referer"] == "https://www.amazon.it/"
    assert headers["Sec-Fetch-Site"] == "same-origin"


async def test_failed_warm_up_does_not_block_the_product_request(session):
    session._client.get = AsyncMock(
        side_effect=[httpx.ConnectError("nope"), MagicMock(status_code=200)]
    )
    with patch("custom_components.amazon_price_tracker.session.asyncio.sleep"):
        response = await session.async_get("https://www.amazon.it/dp/B09FKN79QR")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------

async def test_consecutive_requests_are_spaced_apart(session):
    with patch(
        "custom_components.amazon_price_tracker.session.asyncio.sleep"
    ) as sleep:
        await session.async_get("https://www.amazon.it/dp/AAAAAAAAAA")
        await session.async_get("https://www.amazon.it/dp/BBBBBBBBBB")

    # Warm-up pause, then a spacing wait before the second product
    assert sleep.await_count >= 2
    assert max(call.args[0] for call in sleep.await_args_list) > 0


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

async def test_block_puts_the_whole_marketplace_in_cooldown(session):
    await session.async_note_block()

    assert session.is_blocked is True
    assert session.cooldown_remaining > 0
    # The walled cookie jar is thrown away rather than reused
    assert session._client is None


async def test_requests_during_cooldown_never_reach_the_network(session):
    client = session._client
    await session.async_note_block()
    session._client = client  # a fresh client would be built on the next request

    with pytest.raises(AmazonBlockedError, match="cooldown"):
        await session.async_get("https://www.amazon.it/dp/B09FKN79QR")

    client.get.assert_not_awaited()


async def test_cooldown_expires(session, hass):
    await session.async_note_block()
    assert session.is_blocked is True

    # Wind the deadline back into the past rather than the clock forward
    session._blocked_until = hass.loop.time() - 1

    assert session.is_blocked is False
    assert session._blocked_until is None


async def test_cooldown_is_at_least_the_configured_minimum(session):
    await session.async_note_block()
    assert session.cooldown_remaining >= BLOCK_COOLDOWN_SECONDS - 1


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

async def test_one_session_is_shared_per_marketplace(hass):
    first = async_get_session(hass, "amazon.it")
    second = async_get_session(hass, "amazon.it")
    other = async_get_session(hass, "amazon.de")

    assert first is second
    assert other is not first
    assert set(hass.data[DOMAIN][SESSIONS]) == {"amazon.it", "amazon.de"}


async def test_close_sessions_empties_the_registry(hass):
    async_get_session(hass, "amazon.it")
    await async_close_sessions(hass)
    assert hass.data[DOMAIN][SESSIONS] == {}
