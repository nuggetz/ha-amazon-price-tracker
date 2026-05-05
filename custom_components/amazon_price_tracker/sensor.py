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

from .const import DEFAULT_MARKETPLACE, DOMAIN, DOMAIN_CONFIG
from .coordinator import AmazonPriceCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AmazonPriceCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AmazonPriceSensor(coordinator, entry)])


class AmazonPriceSensor(CoordinatorEntity[AmazonPriceCoordinator], RestoreSensor):
    """Price sensor for a single Amazon ASIN."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
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
        self._min_price: float | None = None
        self._min_price_date: str | None = None
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

        # Seed min_price from coordinator data already fetched during first_refresh —
        # _handle_coordinator_update won't fire for data that arrived before subscription.
        if self._min_price is None and self.coordinator.data is not None:
            price = self.coordinator.data.get("price")
            if price is not None:
                self._min_price = price
                self._min_price_date = datetime.utcnow().isoformat()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update min_price when new coordinator data arrives, then propagate."""
        if self.coordinator.data is not None:
            price = self.coordinator.data.get("price")
            if price is not None:
                if self._min_price is None or price < self._min_price:
                    self._min_price = price
                    self._min_price_date = datetime.utcnow().isoformat()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("price")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        last_updated = data.get("last_updated")
        return {
            "asin": self._asin,
            "marketplace": self._entry.data.get("marketplace", DEFAULT_MARKETPLACE),
            "title": data.get("title"),
            "url": data.get("url"),
            "min_price": self._min_price,
            "min_price_date": self._min_price_date,
            "is_available": data.get("is_available"),
            "availability_text": data.get("availability_text"),
            "alert_threshold": self._alert_threshold,
            "last_updated": (
                last_updated.isoformat()
                if isinstance(last_updated, datetime)
                else None
            ),
        }

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
