from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from statistics import median

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    HISTORY_MIN_DAYS,
    HISTORY_WINDOW_DAYS,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

# Several products refresh within seconds of each other, so writes are
# coalesced rather than issued per sample. Losing the last minute of samples to
# an unclean shutdown costs nothing: the next fetch replaces them.
SAVE_DELAY = 60


class PriceHistory:
    """Per-ASIN daily price history, kept in .storage.

    Not in state attributes: the window would ride along on every state write
    and land in the Recorder each time. Not read back from the Recorder either —
    `min_price` already lives outside it so it survives a purge, and a reference
    price that exists on one installation but not on another (purged, or
    recorder disabled) would be worse than no reference at all.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, dict] = {}
        self._loaded = False
        self._load_lock = asyncio.Lock()

    async def async_load(self) -> None:
        """Read the store once, however many entries ask for it.

        Every product's setup calls this, and they can overlap: without the
        lock the second caller would read an empty history while the first is
        still awaiting the store, and report a warm-up that isn't real.
        """
        async with self._load_lock:
            if self._loaded:
                return
            stored = await self._store.async_load()
            self._data = stored if isinstance(stored, dict) else {}
            self._loaded = True

    @callback
    def async_add_sample(
        self, asin: str, price: float, now: datetime | None = None
    ) -> None:
        """Record one observed price.

        Days are bucketed on UTC dates. A few hours of offset from the user's
        own midnight is irrelevant to a 30-day median, and a fixed reference
        keeps the buckets stable across DST changes.
        """
        today = (now or dt_util.utcnow()).date()
        record = self._data.setdefault(asin, {"days": {}, "pending_day": None, "pending": []})

        if record.get("pending_day") != today.isoformat():
            self._close_pending(record)
            record["pending_day"] = today.isoformat()
            record["pending"] = []

        record["pending"].append(float(price))
        self._prune(record, today)
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    def reference_price(self, asin: str, now: datetime | None = None) -> float | None:
        """The product's usual price, or None while still collecting.

        The median, not the mean: a single misparse does not move it, and a long
        promotion does not drag it down the way an exponential average would —
        which would quietly make the threshold stricter exactly when prices are
        low.
        """
        values = self._window_values(asin, now)
        if len(values) < HISTORY_MIN_DAYS:
            return None
        return round(median(values), 2)

    def coverage_days(self, asin: str, now: datetime | None = None) -> int:
        """Days carrying data inside the window — what arming is measured on."""
        return len(self._window_values(asin, now))

    async def async_flush(self) -> None:
        """Write now instead of waiting out the delay.

        Used when there may be nothing left to trigger the delayed write — the
        last product of an integration being removed, for one.
        """
        await self._store.async_save(self._data)

    @callback
    def async_remove(self, asin: str) -> None:
        """Forget a product's history when its entry is removed.

        Removing and re-adding a product is the only reset users have, so it has
        to be one. The cost is another warm-up, which is visible in the sensor's
        attributes rather than silent.
        """
        if self._data.pop(asin, None) is not None:
            self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    # --- internals ---------------------------------------------------------

    def _window_values(self, asin: str, now: datetime | None = None) -> list[float]:
        """Closed daily values inside the window.

        The day in progress is deliberately excluded: including it would let the
        reference price — and so the threshold — drift under the price during
        the day, which turns a stable comparison into a moving one.
        """
        record = self._data.get(asin)
        if not record:
            return []

        today = (now or dt_util.utcnow()).date().isoformat()
        cutoff = (
            date.fromisoformat(today) - timedelta(days=HISTORY_WINDOW_DAYS)
        ).isoformat()
        days: dict = record.get("days") or {}

        values = [
            float(value)
            for day, value in days.items()
            if day > cutoff and isinstance(value, (int, float))
        ]

        # A day only gets folded into `days` when the next sample arrives, so
        # the last day a product was seen sits in `pending`. It is finished all
        # the same once the date has moved on — otherwise a product that stops
        # updating would lose its final day, and one sampled today would count
        # a day that is still changing.
        pending_day = record.get("pending_day")
        pending = record.get("pending") or []
        if pending and pending_day and cutoff < pending_day < today:
            values.append(round(median(pending), 2))

        return values

    @staticmethod
    def _close_pending(record: dict) -> None:
        """Fold the finished day's samples into one value.

        The median of the day, not its minimum: the minimum would pull the
        reference down over time and make alerts progressively rarer — the same
        ratchet that rules `min_price` out as a threshold basis.
        """
        pending_day = record.get("pending_day")
        pending = record.get("pending") or []
        if pending_day and pending:
            record.setdefault("days", {})[pending_day] = round(median(pending), 2)

    @staticmethod
    def _prune(record: dict, today: date) -> None:
        cutoff = (today - timedelta(days=HISTORY_WINDOW_DAYS)).isoformat()
        days: dict = record.get("days") or {}
        for day in [day for day in days if day <= cutoff]:
            del days[day]

    def _data_to_save(self) -> dict:
        return self._data
