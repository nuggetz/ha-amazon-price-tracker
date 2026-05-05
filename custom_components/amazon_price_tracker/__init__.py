from __future__ import annotations

import logging
import re

import httpx
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DEFAULT_MARKETPLACE, DOMAIN, DOMAIN_CONFIG, HEADERS, WISHLIST_ID_RE
from .coordinator import AmazonPriceCoordinator, parse_wishlist_page

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

SERVICE_FORCE_REFRESH = "force_refresh"
SERVICE_IMPORT_WISHLIST = "import_wishlist"

_FORCE_REFRESH_SCHEMA = vol.Schema({vol.Optional("entity_id"): cv.entity_ids})
_IMPORT_WISHLIST_SCHEMA = vol.Schema(
    {
        vol.Required("url"): cv.string,
        vol.Optional("marketplace"): vol.In(list(DOMAIN_CONFIG.keys())),
        vol.Optional("alert_threshold"): vol.Coerce(float),
    }
)
_WISHLIST_RE = re.compile(WISHLIST_ID_RE, re.IGNORECASE)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    # Options override the original data for mutable fields (name, alert_threshold)
    name = entry.options.get("name", entry.data["name"])
    # marketplace is immutable (set once at creation, not in options)
    marketplace = entry.data.get("marketplace", DEFAULT_MARKETPLACE)

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

    # Register services once for the whole domain
    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_REFRESH):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCE_REFRESH,
            _make_force_refresh_handler(hass),
            schema=_FORCE_REFRESH_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_IMPORT_WISHLIST):
        hass.services.async_register(
            DOMAIN,
            SERVICE_IMPORT_WISHLIST,
            _make_import_wishlist_handler(hass),
            schema=_IMPORT_WISHLIST_SCHEMA,
        )

    return True


def _make_force_refresh_handler(hass: HomeAssistant):
    async def _handle_force_refresh(call: ServiceCall) -> None:
        domain_data: dict[str, AmazonPriceCoordinator] = hass.data.get(DOMAIN, {})
        entity_ids: list[str] | None = call.data.get("entity_id")

        if not entity_ids:
            for coordinator in domain_data.values():
                await coordinator.async_request_refresh()
            return

        registry = er.async_get(hass)
        entry_ids: set[str] = set()
        for entity_id in entity_ids:
            entity_entry = registry.async_get(entity_id)
            if entity_entry and entity_entry.config_entry_id in domain_data:
                entry_ids.add(entity_entry.config_entry_id)

        for entry_id in entry_ids:
            await domain_data[entry_id].async_request_refresh()

    return _handle_force_refresh


def _make_import_wishlist_handler(hass: HomeAssistant):
    async def _handle_import_wishlist(call: ServiceCall) -> None:
        url: str = call.data["url"]
        override_marketplace: str | None = call.data.get("marketplace")
        alert_threshold: float | None = call.data.get("alert_threshold")

        # Parse marketplace and wishlist ID from the URL
        match = _WISHLIST_RE.search(url)
        if not match:
            raise ServiceValidationError(
                f"Invalid wishlist URL: {url!r}. "
                "Expected format: https://www.amazon.xx/hz/wishlist/ls/XXXX"
            )

        marketplace_suffix = match.group(1).lower()   # e.g. "it", "co.uk"
        wishlist_id = match.group(2)
        marketplace = override_marketplace or f"amazon.{marketplace_suffix}"

        if marketplace not in DOMAIN_CONFIG:
            _LOGGER.warning(
                "Marketplace %r not supported, falling back to %s",
                marketplace, DEFAULT_MARKETPLACE,
            )
            marketplace = DEFAULT_MARKETPLACE

        market_config = DOMAIN_CONFIG[marketplace]
        headers = {**HEADERS, "Accept-Language": market_config["language"]}
        wishlist_url = f"https://www.{marketplace}/hz/wishlist/ls/{wishlist_id}"

        _LOGGER.debug("Fetching wishlist %s", wishlist_url)

        try:
            async with httpx.AsyncClient(
                headers=headers,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0),
            ) as client:
                response = await client.get(wishlist_url)
                response.raise_for_status()
        except httpx.HTTPStatusError as err:
            raise ServiceValidationError(
                f"Cannot fetch wishlist (HTTP {err.response.status_code}). "
                "Make sure the wishlist is set to Public."
            ) from err
        except httpx.HTTPError as err:
            raise ServiceValidationError(f"Network error fetching wishlist: {err}") from err

        products = await hass.async_add_executor_job(parse_wishlist_page, response.text)

        if not products:
            _LOGGER.warning(
                "No products found in wishlist %s — it may be empty or set to Private.",
                wishlist_url,
            )
            return

        _LOGGER.info(
            "Wishlist %s: found %d products, importing…", wishlist_id, len(products)
        )

        added = skipped = 0
        for product in products:
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={
                    "asin": product["asin"],
                    "name": product["name"],
                    "marketplace": marketplace,
                    "alert_threshold": alert_threshold,
                },
            )
            if result.get("type") == "create_entry":
                added += 1
            else:
                skipped += 1

        _LOGGER.info(
            "Wishlist import complete: %d added, %d skipped (already configured)",
            added, skipped,
        )

    return _handle_import_wishlist


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: AmazonPriceCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

        # Remove services when the last entry is unloaded
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_FORCE_REFRESH)
            hass.services.async_remove(DOMAIN, SERVICE_IMPORT_WISHLIST)

    return unload_ok
