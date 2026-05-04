DOMAIN = "amazon_price_tracker"

BASE_URL = "https://www.amazon.it/dp/{asin}"
REQUEST_TIMEOUT = 30

BASE_INTERVAL_SECONDS = 4 * 3600
JITTER_SECONDS = 30 * 60

ASIN_PATTERN = r"^[A-Z0-9]{10}$"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Price selectors — ordered by reliability (Amazon DOM 2025-2026)
# Scoped to the main purchase box first, then progressively wider
PRICE_SELECTORS = [
    "#corePriceDisplay_desktop_feature_div span.a-offscreen",
    "#priceToPay span.a-offscreen",
    "#apex_desktop_newAccordionRow span.a-offscreen",
    ".a-price .a-offscreen",
]

TITLE_SELECTORS = [
    "#productTitle",
    "#title span",
]

CAPTCHA_SIGNALS = [
    "api-services-support@amazon.com",
    "robot check",
    "enter the characters you see below",
    "digita i caratteri che vedi",
    "type the characters you see in this image",
]

# Presence of this div means the product is out of stock
OUT_OF_STOCK_SELECTOR = "#outOfStockBuyBox_feature_div"
