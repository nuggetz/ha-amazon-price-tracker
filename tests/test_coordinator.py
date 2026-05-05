"""Tests for coordinator parsing functions (no HA required)."""
import pytest

from custom_components.amazon_price_tracker.coordinator import (
    AmazonCaptchaError,
    parse_price,
    parse_product_page,
    parse_wishlist_page,
)

# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

HTML_JSONLD = """
<html><body>
<script type="application/ld+json">
{"@type": "Product", "name": "AMD Ryzen 7 9700X",
 "offers": {"@type": "Offer", "price": "299.99", "priceCurrency": "EUR"}}
</script>
<div id="availability"><span>In stock</span></div>
</body></html>
"""

HTML_CSS_PRICE = """
<html><body>
<span id="productTitle">Test Product</span>
<div id="corePriceDisplay_desktop_feature_div">
  <span class="a-offscreen">€ 299,99</span>
</div>
<div id="availability"><span>Disponibile</span></div>
</body></html>
"""

HTML_FRACTION_FALLBACK = """
<html><body>
<span id="productTitle">Fraction Product</span>
<span class="a-price-whole">149,</span>
<span class="a-price-fraction">99</span>
<div id="availability"><span>In stock</span></div>
</body></html>
"""

HTML_CAPTCHA = """
<html><body>
<p>To discuss automated access to Amazon data please contact
api-services-support@amazon.com</p>
</body></html>
"""

HTML_OUT_OF_STOCK = """
<html><body>
<span id="productTitle">Sold Out GPU</span>
<div id="corePriceDisplay_desktop_feature_div">
  <span class="a-offscreen">€ 599,99</span>
</div>
<div id="outOfStockBuyBox_feature_div">Currently unavailable.</div>
<div id="availability"><span>Non disponibile.</span></div>
</body></html>
"""

HTML_WISHLIST = """
<html><body><ul>
<li class="g-item-sortable"
    data-reposition-action-params='{"itemExternalId":"ASIN:B09FKN79QR|A1F83G8C2ARO7P"}'>
  <a id="itemName_ABC" href="/dp/B09FKN79QR" title="Kingston 32GB DDR5">Kingston 32GB DDR5</a>
</li>
<li class="g-item-sortable"
    data-reposition-action-params='{"itemExternalId":"ASIN:B0D6NMDNNX|A1F83G8C2ARO7P"}'>
  <a id="itemName_DEF" href="/dp/B0D6NMDNNX" title="Sapphire RX 9070 XT">Sapphire RX 9070 XT</a>
</li>
</ul></body></html>
"""

HTML_WISHLIST_HREF_FALLBACK = """
<html><body><ul>
<li class="g-item-sortable">
  <a id="itemName_XYZ" href="/dp/B0AABBCCDD/ref=wishlist" title="Fallback Product">Fallback Product</a>
</li>
</ul></body></html>
"""

# ---------------------------------------------------------------------------
# parse_price
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("€ 1.299,99", 1299.99),
    ("299,99 EUR", 299.99),
    ("EUR 49,00", 49.0),
    ("1.000,00", 1000.0),
    ("9,99", 9.99),
])
def test_parse_price_european(raw, expected):
    assert parse_price(raw, european_format=True) == expected


@pytest.mark.parametrize("raw,expected", [
    ("$1,299.99", 1299.99),
    ("299.99 USD", 299.99),
    ("GBP 49.00", 49.0),
    ("1,000.00", 1000.0),
])
def test_parse_price_us(raw, expected):
    assert parse_price(raw, european_format=False) == expected


@pytest.mark.parametrize("raw", ["N/A", "", "unavailable", "—"])
def test_parse_price_invalid(raw):
    assert parse_price(raw, european_format=True) is None


# ---------------------------------------------------------------------------
# parse_product_page
# ---------------------------------------------------------------------------

def test_parse_product_page_json_ld():
    price, title, is_available, avail_text = parse_product_page(
        HTML_JSONLD, "B09FKN79QR", european_format=True
    )
    assert price == 299.99
    assert title == "AMD Ryzen 7 9700X"
    assert is_available is True


def test_parse_product_page_css_price():
    price, title, is_available, avail_text = parse_product_page(
        HTML_CSS_PRICE, "B09FKN79QR", european_format=True
    )
    assert price == 299.99
    assert title == "Test Product"
    assert is_available is True
    assert avail_text == "Disponibile"


def test_parse_product_page_fraction_fallback():
    price, title, is_available, avail_text = parse_product_page(
        HTML_FRACTION_FALLBACK, "B0TEST12AB", european_format=True
    )
    assert price == 149.99
    assert title == "Fraction Product"


def test_parse_product_page_captcha():
    with pytest.raises(AmazonCaptchaError):
        parse_product_page(HTML_CAPTCHA, "B09FKN79QR", european_format=True)


def test_parse_product_page_out_of_stock():
    price, title, is_available, avail_text = parse_product_page(
        HTML_OUT_OF_STOCK, "B0TEST12AB", european_format=True
    )
    assert is_available is False
    assert price == 599.99
    assert "Non disponibile" in (avail_text or "")


# ---------------------------------------------------------------------------
# parse_wishlist_page
# ---------------------------------------------------------------------------

def test_parse_wishlist_page_full():
    products = parse_wishlist_page(HTML_WISHLIST)
    assert len(products) == 2
    assert products[0]["asin"] == "B09FKN79QR"
    assert products[0]["name"] == "Kingston 32GB DDR5"
    assert products[1]["asin"] == "B0D6NMDNNX"
    assert products[1]["name"] == "Sapphire RX 9070 XT"


def test_parse_wishlist_page_href_fallback():
    products = parse_wishlist_page(HTML_WISHLIST_HREF_FALLBACK)
    assert len(products) == 1
    assert products[0]["asin"] == "B0AABBCCDD"
    assert products[0]["name"] == "Fallback Product"


def test_parse_wishlist_page_empty():
    assert parse_wishlist_page("<html><body></body></html>") == []


def test_parse_wishlist_page_no_duplicates():
    html = HTML_WISHLIST + HTML_WISHLIST  # same items twice
    products = parse_wishlist_page(html)
    asins = [p["asin"] for p in products]
    assert len(asins) == len(set(asins))
