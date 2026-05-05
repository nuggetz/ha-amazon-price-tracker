from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import AmazonPriceCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

SERVICE_FORCE_REFRESH = "force_refresh"
_SERVICE_SCHEMA = vol.Schema({vol.Optional("entity_id"): cv.entity_ids})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    # Options override the original data for mutable fields (name, alert_threshold)
    name = entry.options.get("name", entry.data["name"])
    # marketplace is immutable (set once at creation, not in options)
    marketplace = entry.data.get("marketplace", "amazon.it")

    coordinator = AmazonPriceCoordinator(
        hass,
        asin=entry.data["asin"],
        name=name,
        marketplace=marketplace,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload the entry when the user saves new options so all values stay in sync
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Register the service once for the whole domain
    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_REFRESH):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCE_REFRESH,
            _make_force_refresh_handler(hass),
            schema=_SERVICE_SCHEMA,
        )

    return True


def _make_force_refresh_handler(hass: HomeAssistant):
    async def _handle_force_refresh(call: ServiceCall) -> None:
        domain_data: dict[str, AmazonPriceCoordinator] = hass.data.get(DOMAIN, {})
        entity_ids: list[str] | None = call.data.get("entity_id")

        if not entity_ids:
            # No filter — refresh every tracked product
            for coordinator in domain_data.values():
                await coordinator.async_request_refresh()
            return

        # Map entity_id → config_entry_id → coordinator
        registry = er.async_get(hass)
        entry_ids: set[str] = set()
        for entity_id in entity_ids:
            entity_entry = registry.async_get(entity_id)
            if entity_entry and entity_entry.config_entry_id in domain_data:
                entry_ids.add(entity_entry.config_entry_id)

        for entry_id in entry_ids:
            await domain_data[entry_id].async_request_refresh()

    return _handle_force_refresh


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: AmazonPriceCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

        # Remove the service when the last entry is unloaded
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_FORCE_REFRESH)

    return unload_ok
