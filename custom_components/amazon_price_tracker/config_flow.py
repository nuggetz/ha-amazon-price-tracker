from __future__ import annotations

import logging
import re
from typing import Any

import httpx
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DEFAULT_MARKETPLACE, DOMAIN, DOMAIN_CONFIG, HEADERS

_LOGGER = logging.getLogger(__name__)

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
_MARKETPLACES = sorted(DOMAIN_CONFIG.keys())

_STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required("asin"): str,
        vol.Required("name"): str,
        vol.Required("marketplace", default=DEFAULT_MARKETPLACE): vol.In(_MARKETPLACES),
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
        errors: dict[str, str] = {}

        if user_input is not None:
            # 1. Validate ASIN format
            try:
                asin = _validate_asin(user_input["asin"])
            except ValueError:
                errors["asin"] = "invalid_asin"
            else:
                # 2. Prevent duplicates
                await self.async_set_unique_id(asin)
                self._abort_if_unique_id_configured()

                # 3. Light connectivity check — verifies the marketplace is reachable
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
            step_id="user",
            data_schema=_STEP_USER_SCHEMA,
            errors=errors,
        )

    async def _check_reachable(self, asin: str, marketplace: str) -> bool:
        """Return True if the marketplace responds 200 for this ASIN path."""
        from .const import DOMAIN_CONFIG  # avoid circular at module level
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
                # 200 even on CAPTCHA pages — we accept it; parsing issues surface later
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
        # Current values: options take precedence over the original data
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
