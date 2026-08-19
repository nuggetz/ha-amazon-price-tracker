from __future__ import annotations

import json
import logging
import random
import re
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    AVAILABILITY_SELECTOR,
    BASE_INTERVAL_SECONDS,
    BASE_URL,
    BOT_WALL_SIGNALS,
    DEFAULT_MARKETPLACE,
    DOMAIN,
    DOMAIN_CONFIG,
    JITTER_SECONDS,
    MIN_PRODUCT_PAGE_BYTES,
    OUT_OF_STOCK_SELECTOR,
    PRICE_SELECTORS,
    TITLE_SELECTORS,
    WISHLIST_ID_RE,
)
from .exceptions import AmazonBlockedError, AmazonCaptchaError
from .session import AmazonSession, async_get_session

_LOGGER = logging.getLogger(__name__)

_CURRENCY_SYMBOLS = ("€", "£", "$", "¥", "kr", "zł", "EUR", "GBP", "USD", "JPY", "CAD", "AUD", "PLN", "SEK")
_ASIN_IN_HREF_RE = re.compile(r"/dp/([A-Z0-9]{10})")
_WISHLIST_RE = re.compile(WISHLIST_ID_RE, re.IGNORECASE)


def parse_price(raw: str, european_format: bool = True) -> float | None:
    """Normalize a price string to float.

    european_format=True : dots are thousands separators, comma is decimal (1.299,99)
    european_format=False: commas are thousands separators, dot is decimal (1,299.99)
    """
    cleaned = raw.strip()
    for sym in _CURRENCY_SYMBOLS:
        cleaned = cleaned.replace(sym, "")
    cleaned = cleaned.strip()

    if european_format:
        cleaned = cleaned.replace(" ", "").replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "").replace(" ", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_product_page(
    html: str, asin: str, european_format: bool = True
) -> tuple[float | None, str | None, bool, str | None]:
    """Parse an Amazon product page.

    Returns (price, title, is_available, availability_text).
    Runs synchronously — must be called via async_add_executor_job.
    Raises AmazonCaptchaError if Amazon served an anti-bot wall or any other
    non-product page instead of the listing.
    """
    html_lower = html.lower()
    for signal in BOT_WALL_SIGNALS:
        if signal in html_lower:
            raise AmazonCaptchaError(
                f"Amazon served an anti-bot page instead of {asin} "
                f"(matched {signal!r})"
            )

    soup = BeautifulSoup(html, "html.parser")

    # --- Availability ---
    is_available = soup.select_one(OUT_OF_STOCK_SELECTOR) is None
    availability_text: str | None = None
    avail_el = soup.select_one(AVAILABILITY_SELECTOR)
    if avail_el:
        availability_text = avail_el.get_text(strip=True) or None

    price: float | None = None
    title: str | None = None

    # --- Strategy 1: JSON-LD (most stable) ---
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
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
                candidate = parse_price(el.get_text(strip=True), european_format)
                if candidate is not None:
                    price = candidate
                    break

    # --- Strategy 2b: composite whole + fraction fallback ---
    if price is None:
        whole_el = soup.select_one("span.a-price-whole")
        frac_el = soup.select_one("span.a-price-fraction")
        if whole_el and frac_el:
            whole = whole_el.get_text(strip=True).rstrip(",. ")
            frac = frac_el.get_text(strip=True).strip()
            if european_format:
                whole = whole.replace(".", "").replace(",", "").replace(" ", "")
            else:
                whole = whole.replace(",", "").replace(" ", "")
            try:
                price = float(f"{whole}.{frac}")
            except ValueError:
                pass

    # --- Title fallback ---
    if title is None:
        for selector in TITLE_SELECTORS:
            el = soup.select_one(selector)
            if el:
                candidate = el.get_text(strip=True)
                if candidate:
                    title = candidate
                    break

    # Anti-bot interstitials keep changing their wording, so fall back to shape:
    # a page carrying neither a price nor a title, far too small to be a product
    # listing, is a wall or an error shell — not a product we failed to parse.
    if price is None and title is None and len(html) < MIN_PRODUCT_PAGE_BYTES:
        raise AmazonCaptchaError(
            f"Amazon returned a non-product page for {asin} "
            f"({len(html)} bytes, no title, no price)"
        )

    if price is None and is_available:
        # Dumping the first 300 chars only ever showed Amazon's boilerplate
        # doctype. Report what actually helps triage instead, and keep the full
        # page behind debug logging.
        _LOGGER.warning(
            "Could not parse price for ASIN %s on what looks like a real product "
            "page (%d bytes, title=%r, availability=%r). Amazon may have changed "
            "its layout — enable debug logging for %s and open an issue with the "
            "captured page.",
            asin,
            len(html),
            title,
            availability_text,
            __name__,
        )
        _LOGGER.debug("Unparsed product page for %s:\n%s", asin, html)

    return price, title, is_available, availability_text


def parse_wishlist_page(html: str) -> list[dict]:
    """Parse a public Amazon wishlist page and return list of {asin, name}.

    Runs synchronously — must be called via async_add_executor_job.
    Returns an empty list if the wishlist is private or contains no parseable items.
    """
    soup = BeautifulSoup(html, "html.parser")
    products: list[dict] = []
    seen: set[str] = set()

    for item in soup.find_all("li", class_="g-item-sortable"):
        asin: str | None = None
        name: str | None = None

        # Primary: structured data in data-reposition-action-params JSON
        raw_params = item.get("data-reposition-action-params")
        if raw_params:
            try:
                params = json.loads(raw_params)
                external_id = params.get("itemExternalId", "")
                # Format: "ASIN:B095PV5G87|A1F83G8C2ARO7P"
                if external_id.startswith("ASIN:"):
                    asin = external_id.split(":")[1].split("|")[0]
            except (json.JSONDecodeError, IndexError):
                pass

        # Fallback: parse ASIN from the itemName link href
        name_link = item.select_one("a[id^='itemName_']")
        if name_link:
            name = (name_link.get("title") or name_link.get_text(strip=True)) or None
            if asin is None:
                href = name_link.get("href", "")
                match = _ASIN_IN_HREF_RE.search(href)
                if match:
                    asin = match.group(1)

        if asin and asin not in seen:
            seen.add(asin)
            products.append({"asin": asin, "name": name or asin})

    return products


class AmazonPriceCoordinator(DataUpdateCoordinator[dict]):
    """Fetches and caches price data for a single Amazon ASIN."""

    def __init__(
        self,
        hass: HomeAssistant,
        asin: str,
        name: str,
        marketplace: str = DEFAULT_MARKETPLACE,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{asin}",
            update_interval=timedelta(hours=4),
        )
        self.asin = asin
        self.product_name = name
        self.marketplace = marketplace
        self._market_config = DOMAIN_CONFIG.get(marketplace, DOMAIN_CONFIG[DEFAULT_MARKETPLACE])
        # True when the last failure was Amazon blocking us rather than a
        # network or configuration problem. Setup reads this to decide whether
        # the entry is genuinely not ready or merely walled for now.
        self.blocked_by_amazon = False

    @property
    def session(self) -> AmazonSession:
        """The session shared by every product on this marketplace."""
        return async_get_session(self.hass, self.marketplace)

    async def _async_update_data(self) -> dict:
        url = BASE_URL.format(marketplace=self.marketplace, asin=self.asin)
        european_format: bool = self._market_config["european_format"]

        session = self.session

        try:
            response = await session.async_get(url)
            response.raise_for_status()
        except AmazonBlockedError as err:
            # The marketplace is already in cooldown — no request was sent and
            # there is no new block to record. Stay quiet; the session logged
            # the block once, for all products, when it happened.
            self.blocked_by_amazon = True
            _LOGGER.debug("Skipped %s: %s", self.asin, err)
            self.update_interval = timedelta(minutes=30)
            raise UpdateFailed(str(err)) from err
        except httpx.HTTPStatusError as err:
            self.blocked_by_amazon = False
            self.update_interval = timedelta(minutes=30)
            raise UpdateFailed(
                f"HTTP {err.response.status_code} for {self.asin}"
            ) from err
        except httpx.HTTPError as err:
            self.blocked_by_amazon = False
            self.update_interval = timedelta(minutes=30)
            raise UpdateFailed(f"Network error for {self.asin}: {err}") from err

        try:
            price, title, is_available, availability_text = (
                await self.hass.async_add_executor_job(
                    parse_product_page, response.text, self.asin, european_format
                )
            )
        except AmazonBlockedError as err:
            # We spent a request and got a wall: put the whole marketplace in
            # cooldown so the other products don't each collect one too.
            _LOGGER.debug("Anti-bot page for %s: %s", self.asin, err)
            self.blocked_by_amazon = True
            await session.async_note_block()
            self.update_interval = timedelta(minutes=30)
            raise UpdateFailed(str(err)) from err

        self.blocked_by_amazon = False

        jitter = random.uniform(-JITTER_SECONDS, JITTER_SECONDS)
        self.update_interval = timedelta(seconds=BASE_INTERVAL_SECONDS + jitter)

        return {
            "price": price,
            "title": title or self.product_name,
            "url": url,
            "last_updated": datetime.utcnow(),
            "is_available": is_available,
            "availability_text": availability_text,
        }
