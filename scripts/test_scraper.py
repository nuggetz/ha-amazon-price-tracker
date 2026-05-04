#!/usr/bin/env python3
"""Standalone scraper test — run without Home Assistant.

Usage:
    python scripts/test_scraper.py B09FKN79QR
    python scripts/test_scraper.py B09FKN79QR B0BLPJLT8S
"""

import asyncio
import sys
from pathlib import Path

# Allow importing from custom_components without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from custom_components.amazon_price_tracker.const import HEADERS
from custom_components.amazon_price_tracker.coordinator import (
    AmazonCaptchaError,
    parse_product_page,
)


async def test_asin(asin: str) -> None:
    url = f"https://www.amazon.it/dp/{asin}"
    print(f"\n{'='*60}")
    print(f"ASIN : {asin}")
    print(f"URL  : {url}")

    async with httpx.AsyncClient(
        headers=HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
    ) as client:
        try:
            response = await client.get(url)
            print(f"HTTP : {response.status_code}")
        except httpx.HTTPError as err:
            print(f"ERROR: {err}")
            return

    try:
        price, title, is_available = parse_product_page(response.text, asin)
    except AmazonCaptchaError:
        print("RESULT: CAPTCHA detected — try again later or change User-Agent")
        return

    print(f"Title    : {title}")
    print(f"Price    : {price} EUR" if price is not None else "Price    : not found")
    print(f"Available: {is_available}")


async def main() -> None:
    asins = sys.argv[1:] if len(sys.argv) > 1 else ["B09FKN79QR"]
    for asin in asins:
        await test_asin(asin.strip().upper())


if __name__ == "__main__":
    asyncio.run(main())
