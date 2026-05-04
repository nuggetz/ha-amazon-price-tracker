from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BASE_INTERVAL_SECONDS,
    BASE_URL,
    CAPTCHA_SIGNALS,
    DOMAIN,
    HEADERS,
    JITTER_SECONDS,
    OUT_OF_STOCK_SELECTOR,
    PRICE_SELECTORS,
    REQUEST_TIMEOUT,
    TITLE_SELECTORS,
)

_LOGGER = logging.getLogger(__name__)


class AmazonCaptchaError(Exception):
    pass


def parse_price(raw: str) -> float | None:
    """Normalize a European-format price string to float."""
    cleaned = raw.strip().replace("€", "").replace("EUR", "").strip()
    # European format: dot = thousands separator, comma = decimal
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_product_page(html: str, asin: str) -> tuple[float | None, str | None, bool]:
    """Parse an Amazon product page and return (price, title, is_available).

    Runs synchronously — must be called via async_add_executor_job.
    Raises AmazonCaptchaError if a CAPTCHA wall is detected.
    """
    html_lower = html.lower()
    for signal in CAPTCHA_SIGNALS:
        if signal in html_lower:
            raise AmazonCaptchaError(f"CAPTCHA detected for {asin}")

    soup = BeautifulSoup(html, "html.parser")

    is_available = soup.select_one(OUT_OF_STOCK_SELECTOR) is None

    price: float | None = None
    title: str | None = None

    # --- Strategy 1: JSON-LD (most stable) ---
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            # Some pages wrap multiple objects in a list
            if isinstance(data, list):
                data = next(
                    (d for d in data if isinstance(d, dict) and d.get("@type") == "Product"),
                    {},
                )
            if not isinstance(data, dict) or data.get("@type") != "Product":
                continue
            title = data.get("name") or title
            offers = data.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            raw_price = offers.get("price")
            if raw_price is not None:
                try:
                    price = float(str(raw_price).replace(",", "."))
                except (ValueError, TypeError):
                    pass
            if price is not None:
                break
        except (json.JSONDecodeError, AttributeError, StopIteration):
            continue

    # --- Strategy 2: CSS selectors (scoped, narrow → wide) ---
    if price is None:
        for selector in PRICE_SELECTORS:
            el = soup.select_one(selector)
            if el:
                candidate = parse_price(el.get_text(strip=True))
                if candidate is not None:
                    price = candidate
                    break

    # --- Strategy 2b: composite whole + fraction fallback ---
    if price is None:
        whole_el = soup.select_one("span.a-price-whole")
        frac_el = soup.select_one("span.a-price-fraction")
        if whole_el and frac_el:
            whole = whole_el.get_text(strip=True).rstrip(",.")
            frac = frac_el.get_text(strip=True)
            price = parse_price(f"{whole}.{frac}")

    # --- Title fallback ---
    if title is None:
        for selector in TITLE_SELECTORS:
            el = soup.select_one(selector)
            if el:
                candidate = el.get_text(strip=True)
                if candidate:
                    title = candidate
                    break

    if price is None and is_available:
        _LOGGER.warning(
            "Could not parse price for ASIN %s — page snippet: %.300s",
            asin,
            html,
        )

    return price, title, is_available


class AmazonPriceCoordinator(DataUpdateCoordinator[dict]):
    """Fetches and caches price data for a single Amazon ASIN."""

    def __init__(self, hass: HomeAssistant, asin: str, name: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{asin}",
            update_interval=timedelta(hours=4),
        )
        self.asin = asin
        self.product_name = name
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=HEADERS,
                follow_redirects=True,
                timeout=httpx.Timeout(REQUEST_TIMEOUT),
            )
        return self._client

    async def async_shutdown(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _async_update_data(self) -> dict:
        url = BASE_URL.format(asin=self.asin)
        try:
            client = await self._get_client()
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as err:
            raise UpdateFailed(
                f"HTTP {err.response.status_code} for {self.asin}"
            ) from err
        except httpx.HTTPError as err:
            raise UpdateFailed(f"Network error for {self.asin}: {err}") from err

        try:
            price, title, is_available = await self.hass.async_add_executor_job(
                parse_product_page, response.text, self.asin
            )
        except AmazonCaptchaError as err:
            _LOGGER.warning("CAPTCHA for ASIN %s — will retry next cycle", self.asin)
            raise UpdateFailed(str(err)) from err

        # Randomize next polling interval to spread requests and reduce fingerprinting
        jitter = random.uniform(-JITTER_SECONDS, JITTER_SECONDS)
        self.update_interval = timedelta(seconds=BASE_INTERVAL_SECONDS + jitter)

        return {
            "price": price,
            "title": title or self.product_name,
            "url": url,
            "last_updated": datetime.utcnow(),
            "is_available": is_available,
        }
