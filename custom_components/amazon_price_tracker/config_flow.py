from __future__ import annotations

import logging
import re
from typing import Any

import httpx
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DEFAULT_MARKETPLACE, DOMAIN, DOMAIN_CONFIG, HEADERS, WISHLIST_ID_RE

_LOGGER = logging.getLogger(__name__)

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
_WISHLIST_RE = re.compile(WISHLIST_ID_RE, re.IGNORECASE)
_MARKETPLACES = sorted(DOMAIN_CONFIG.keys())

_COUNTRY_TO_MARKETPLACE: dict[str, str] = {
    "IT": "amazon.it",
    "DE": "amazon.de",
    "FR": "amazon.fr",
    "ES": "amazon.es",
    "NL": "amazon.nl",
    "BE": "amazon.be",
    "PL": "amazon.pl",
    "SE": "amazon.se",
    "GB": "amazon.co.uk",
    "IE": "amazon.ie",
    "US": "amazon.com",
    "CA": "amazon.ca",
    "JP": "amazon.co.jp",
    "AU": "amazon.com.au",
    "BR": "amazon.com.br",
    "MX": "amazon.com.mx",
    "IN": "amazon.in",
    "TR": "amazon.com.tr",
    "AE": "amazon.ae",
    "SG": "amazon.sg",
}


def _default_marketplace(country: str | None) -> str:
    if country:
        return _COUNTRY_TO_MARKETPLACE.get(country.upper(), DEFAULT_MARKETPLACE)
    return DEFAULT_MARKETPLACE


def _build_add_product_schema(default_marketplace: str) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("asin"): str,
            vol.Required("name"): str,
            vol.Required("marketplace", default=default_marketplace): vol.In(_MARKETPLACES),
            vol.Optional("alert_threshold"): vol.Coerce(float),
        }
    )

_STEP_WISHLIST_SCHEMA = vol.Schema(
    {
        vol.Required("url"): str,
        vol.Optional("alert_threshold"): vol.Coerce(float),
    }
)


def _validate_asin(raw: str) -> str:
    asin = raw.strip().upper()
    if not _ASIN_RE.match(asin):
        raise ValueError(f"Invalid ASIN: {raw!r}")
    return asin


class AmazonPriceTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AmazonPriceTrackerOptionsFlow:
        return AmazonPriceTrackerOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=["add_product", "import_wishlist"],
        )

    async def async_step_add_product(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                asin = _validate_asin(user_input["asin"])
            except ValueError:
                errors["asin"] = "invalid_asin"
            else:
                await self.async_set_unique_id(asin)
                self._abort_if_unique_id_configured()

                marketplace = user_input.get("marketplace", DEFAULT_MARKETPLACE)
                if not await self._check_reachable(asin, marketplace):
                    errors["base"] = "cannot_connect"

            if not errors:
                name = user_input["name"].strip()
                alert_threshold = user_input.get("alert_threshold")
                return self.async_create_entry(
                    title=name,
                    data={
                        "asin": asin,
                        "name": name,
                        "marketplace": marketplace,
                        "alert_threshold": alert_threshold,
                    },
                )

        return self.async_show_form(
            step_id="add_product",
            data_schema=_build_add_product_schema(
                _default_marketplace(self.hass.config.country)
            ),
            errors=errors,
        )

    async def async_step_import_wishlist(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url: str = user_input["url"].strip()
            alert_threshold: float | None = user_input.get("alert_threshold")

            wishlist_match = _WISHLIST_RE.search(url)
            if not wishlist_match:
                errors["url"] = "invalid_wishlist_url"
            else:
                marketplace_suffix = wishlist_match.group(1).lower()
                wishlist_id = wishlist_match.group(2)
                marketplace = f"amazon.{marketplace_suffix}"
                if marketplace not in DOMAIN_CONFIG:
                    marketplace = DEFAULT_MARKETPLACE

                market_config = DOMAIN_CONFIG[marketplace]
                headers = {**HEADERS, "Accept-Language": market_config["language"]}
                wishlist_url = f"https://www.{marketplace}/hz/wishlist/ls/{wishlist_id}"

                try:
                    async with httpx.AsyncClient(
                        headers=headers,
                        follow_redirects=True,
                        timeout=httpx.Timeout(30.0),
                    ) as client:
                        response = await client.get(wishlist_url)
                        response.raise_for_status()
                except httpx.HTTPStatusError:
                    errors["base"] = "wishlist_not_found"
                except httpx.HTTPError:
                    errors["base"] = "cannot_connect"

                if not errors:
                    from .coordinator import parse_wishlist_page  # avoid circular import

                    products = await self.hass.async_add_executor_job(
                        parse_wishlist_page, response.text
                    )

                    if not products:
                        errors["base"] = "wishlist_empty"

                if not errors:
                    added = 0
                    for product in products:
                        result = await self.hass.config_entries.flow.async_init(
                            DOMAIN,
                            context={"source": config_entries.SOURCE_IMPORT},
                            data={
                                "asin": product["asin"],
                                "name": product["name"],
                                "marketplace": marketplace,
                                "alert_threshold": alert_threshold,
                            },
                        )
                        if result.get("type") == "create_entry":
                            added += 1

                    return self.async_abort(
                        reason="wishlist_imported",
                        description_placeholders={
                            "added": str(added),
                            "total": str(len(products)),
                        },
                    )

        return self.async_show_form(
            step_id="import_wishlist",
            data_schema=_STEP_WISHLIST_SCHEMA,
            errors=errors,
        )

    async def _check_reachable(self, asin: str, marketplace: str) -> bool:
        config = DOMAIN_CONFIG.get(marketplace, DOMAIN_CONFIG[DEFAULT_MARKETPLACE])
        headers = {**HEADERS, "Accept-Language": config["language"]}
        url = f"https://www.{marketplace}/dp/{asin}"
        try:
            async with httpx.AsyncClient(
                headers=headers,
                follow_redirects=True,
                timeout=httpx.Timeout(10.0),
            ) as client:
                response = await client.get(url)
                return response.status_code == 200
        except httpx.HTTPError as err:
            _LOGGER.warning("Connectivity check failed for %s on %s: %s", asin, marketplace, err)
            return False

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Create an entry from the import_wishlist service — no network check."""
        asin = import_data["asin"]
        await self.async_set_unique_id(asin)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=import_data.get("name", asin),
            data=import_data,
        )


class AmazonPriceTrackerOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        current_name = self._config_entry.options.get(
            "name", self._config_entry.data["name"]
        )
        current_threshold = self._config_entry.options.get(
            "alert_threshold", self._config_entry.data.get("alert_threshold")
        )

        if user_input is not None:
            name = user_input["name"].strip()
            alert_threshold = user_input.get("alert_threshold")
            return self.async_create_entry(
                title=name,
                data={"name": name, "alert_threshold": alert_threshold},
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=current_name): str,
                    vol.Optional(
                        "alert_threshold",
                        description={"suggested_value": current_threshold},
                    ): vol.Coerce(float),
                }
            ),
        )
