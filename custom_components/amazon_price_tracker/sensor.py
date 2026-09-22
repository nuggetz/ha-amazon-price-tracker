from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    COORDINATORS,
    DEFAULT_MARKETPLACE,
    DOMAIN,
    DOMAIN_CONFIG,
    EVENT_PRICE_DROP,
    HISTORY_MIN_DAYS,
    MODE_ABSOLUTE,
    MODE_BOTH,
    MODE_PERCENT,
    STATUS_COLLECTING,
    STATUS_READY,
)
from .coordinator import AmazonPriceCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AmazonPriceCoordinator = hass.data[DOMAIN][COORDINATORS][entry.entry_id]
    async_add_entities([AmazonPriceSensor(coordinator, entry)])


class AmazonPriceSensor(CoordinatorEntity[AmazonPriceCoordinator], RestoreSensor):
    """Price sensor for a single Amazon ASIN."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_has_entity_name = True
    # None = entity IS the device; avoids "Product Name Product Name" duplication
    _attr_name = None

    def __init__(
        self,
        coordinator: AmazonPriceCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._asin: str = entry.data["asin"]
        marketplace = entry.data.get("marketplace", DEFAULT_MARKETPLACE)
        market_config = DOMAIN_CONFIG.get(marketplace, DOMAIN_CONFIG[DEFAULT_MARKETPLACE])

        # Currency depends on marketplace (EUR, GBP, USD, PLN, SEK…)
        self._attr_native_unit_of_measurement = market_config["currency"]

        # Options override data for mutable fields
        self._alert_threshold: float | None = entry.options.get(
            "alert_threshold", entry.data.get("alert_threshold")
        )
        # A percentage below the product's usual price. It can stand on its own
        # or sit next to the absolute threshold above, in which case the alert
        # is whichever of the two the price reaches first.
        self._discount_pct: float | None = entry.options.get(
            "alert_discount_pct", entry.data.get("alert_discount_pct")
        )
        self._history = coordinator.history
        self._min_price: float | None = None
        self._min_price_date: str | None = None
        # None = unknown side of the threshold (never seen, or the price is
        # currently unavailable). The alert event fires on the transition into
        # True, so None behaves like "was above": coming back from unknown with
        # a price under the threshold is a crossing.
        self._below_threshold: bool | None = None
        self._attr_unique_id = f"amazon_price_{self._asin}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore min_price from the last recorded state so it survives HA restarts
        if (last_state := await self.async_get_last_state()) is not None:
            attrs = last_state.attributes
            if (raw := attrs.get("min_price")) is not None:
                try:
                    self._min_price = float(raw)
                    self._min_price_date = attrs.get("min_price_date")
                except (ValueError, TypeError):
                    pass

            # Restore which side of the threshold we were on, so a restart with
            # a price already below it does not re-announce an old drop.
            if (threshold := self._resolve_threshold()) is not None:
                try:
                    self._below_threshold = float(last_state.state) <= threshold
                except (ValueError, TypeError):
                    self._below_threshold = None

        # Seed min_price from coordinator data already fetched during first_refresh —
        # _handle_coordinator_update won't fire for data that arrived before subscription.
        if self.coordinator.data is not None:
            price = self.coordinator.data.get("price")
            if price is not None and self._min_price is None:
                self._min_price = price
                self._min_price_date = datetime.utcnow().isoformat()
            # Same reason: a drop that happened while Home Assistant was down
            # lands in that first fetch, and nothing would announce it.
            self._check_alert_threshold(price)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update min_price when new coordinator data arrives, then propagate."""
        if self.coordinator.data is not None:
            price = self.coordinator.data.get("price")
            if price is not None:
                if self._min_price is None or price < self._min_price:
                    self._min_price = price
                    self._min_price_date = datetime.utcnow().isoformat()
            self._check_alert_threshold(price)
        super()._handle_coordinator_update()

    @property
    def _discount_threshold(self) -> float | None:
        """The percentage as an amount of money, or None while it cannot be."""
        if self._discount_pct is None:
            return None
        if (reference := self._reference_price) is None:
            return None
        return round(reference * (1 - self._discount_pct / 100), 2)

    def _resolve_threshold(self) -> float | None:
        """The threshold as an amount of money, whatever the user configured.

        A percentage is resolved against the reference price and handed to the
        same crossing check as a fixed amount — the alert has one mechanism, not
        one per kind of threshold. With both set the alert is whichever comes
        first, and "price below either" is "price below the higher of the two",
        so two thresholds still collapse into the single amount the crossing
        check compares against.

        None means "do not evaluate": nothing set, or nothing usable yet — a
        percentage whose reference is still collecting. A fixed threshold
        alongside it keeps working throughout that wait, which is the reason
        setting both is worth allowing at all.
        """
        candidates = [
            candidate
            for candidate in (self._alert_threshold, self._discount_threshold)
            if candidate is not None
        ]
        if not candidates:
            return None
        return max(candidates)

    @property
    def _threshold_mode(self) -> str | None:
        if self._alert_threshold is not None and self._discount_pct is not None:
            return MODE_BOTH
        if self._discount_pct is not None:
            return MODE_PERCENT
        if self._alert_threshold is not None:
            return MODE_ABSOLUTE
        return None

    @property
    def _reference_price(self) -> float | None:
        """The product's usual price, or None while the window is filling."""
        if self._history is None:
            return None
        return self._history.reference_price(self._asin)

    @callback
    def _check_alert_threshold(self, price: float | None) -> None:
        """Fire the price drop event on the crossing, not on every refresh."""
        threshold = self._resolve_threshold()

        if threshold is None:
            # No threshold, or a percentage one still collecting. Forget which
            # side we were on, so the first evaluation once it arms counts as a
            # crossing — the same reason the first fetch after a restart is
            # evaluated rather than assumed.
            self._below_threshold = None
            return

        if price is None:
            # No price this cycle: forget which side we were on, so the next
            # price under the threshold counts as a fresh crossing.
            self._below_threshold = None
            return

        below = price <= threshold
        was_below = self._below_threshold
        self._below_threshold = below

        if not below or was_below:
            return

        data = self.coordinator.data or {}
        self.hass.bus.async_fire(
            EVENT_PRICE_DROP,
            {
                "entity_id": self.entity_id,
                "asin": self._asin,
                "name": self._entry.options.get("name", self._entry.data["name"]),
                "title": data.get("title"),
                "price": price,
                "currency": self._attr_native_unit_of_measurement,
                "alert_threshold": threshold,
                "threshold_mode": self._threshold_mode,
                # The two configured thresholds as money, so an automation can
                # tell which one the price actually reached. `alert_threshold`
                # stays the amount compared against.
                "fixed_threshold": self._alert_threshold,
                "discount_threshold": self._discount_threshold,
                "reference_price": self._reference_price,
                "discount_pct": self._discount_pct,
                "min_price": self._min_price,
                "url": data.get("url"),
                "marketplace": self._entry.data.get("marketplace", DEFAULT_MARKETPLACE),
            },
        )

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("price")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        last_updated = data.get("last_updated")
        attributes = {
            "asin": self._asin,
            "marketplace": self._entry.data.get("marketplace", DEFAULT_MARKETPLACE),
            "title": data.get("title"),
            "url": data.get("url"),
            "min_price": self._min_price,
            "min_price_date": self._min_price_date,
            "is_available": data.get("is_available"),
            "availability_text": data.get("availability_text"),
            # Always the amount of money being compared against, so automations
            # written for a fixed threshold keep working on a percentage one.
            "alert_threshold": self._resolve_threshold(),
            "last_updated": (
                last_updated.isoformat()
                if isinstance(last_updated, datetime)
                else None
            ),
        }

        # Only meaningful on a percentage threshold. On a fixed one these would
        # be five permanently empty attributes written to the Recorder on every
        # state change.
        if self._discount_pct is not None:
            reference = self._reference_price
            attributes.update(
                {
                    "threshold_mode": self._threshold_mode,
                    "discount_pct": self._discount_pct,
                    "reference_price": reference,
                    # Says out loud why an alert is not armed yet, so a quiet
                    # first fortnight reads as a warm-up and not as a bug.
                    "reference_status": (
                        STATUS_READY if reference is not None else STATUS_COLLECTING
                    ),
                    "reference_days": (
                        self._history.coverage_days(self._asin) if self._history else 0
                    ),
                    "reference_days_required": HISTORY_MIN_DAYS,
                }
            )
            # Only when both are set: `alert_threshold` is then the higher of
            # the two, so the fixed amount would otherwise be invisible exactly
            # when it is not the one being compared against.
            if self._alert_threshold is not None:
                attributes["fixed_threshold"] = self._alert_threshold

        return attributes

    @property
    def device_info(self) -> DeviceInfo:
        name = self._entry.options.get("name", self._entry.data["name"])
        marketplace = self._entry.data.get("marketplace", DEFAULT_MARKETPLACE)
        return DeviceInfo(
            identifiers={(DOMAIN, self._asin)},
            name=name,
            manufacturer=f"Amazon ({marketplace})",
            model=self._asin,
            entry_type=DeviceEntryType.SERVICE,
        )
