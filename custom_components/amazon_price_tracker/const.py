DOMAIN = "amazon_price_tracker"

# URL template — marketplace and asin are injected at runtime
BASE_URL = "https://www.{marketplace}/dp/{asin}"
REQUEST_TIMEOUT = 30

BASE_INTERVAL_SECONDS = 4 * 3600
JITTER_SECONDS = 30 * 60

ASIN_PATTERN = r"^[A-Z0-9]{10}$"

# Base HTTP headers — Accept-Language is overridden per marketplace
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

# Supported Amazon marketplaces
# european_format: True  → 1.299,99  (dot=thousands, comma=decimal)
# european_format: False → 1,299.99  (comma=thousands, dot=decimal)
DOMAIN_CONFIG: dict[str, dict] = {
    "amazon.it": {"currency": "EUR", "language": "it-IT,it;q=0.9,en;q=0.8", "european_format": True},
    "amazon.de": {"currency": "EUR", "language": "de-DE,de;q=0.9,en;q=0.8", "european_format": True},
    "amazon.fr": {"currency": "EUR", "language": "fr-FR,fr;q=0.9,en;q=0.8", "european_format": True},
    "amazon.es": {"currency": "EUR", "language": "es-ES,es;q=0.9,en;q=0.8", "european_format": True},
    "amazon.nl": {"currency": "EUR", "language": "nl-NL,nl;q=0.9,en;q=0.8", "european_format": True},
    "amazon.be": {"currency": "EUR", "language": "fr-BE,fr;q=0.9,nl;q=0.8,en;q=0.7", "european_format": True},
    "amazon.pl": {"currency": "PLN", "language": "pl-PL,pl;q=0.9,en;q=0.8", "european_format": True},
    "amazon.se": {"currency": "SEK", "language": "sv-SE,sv;q=0.9,en;q=0.8", "european_format": True},
    "amazon.co.uk": {"currency": "GBP", "language": "en-GB,en;q=0.9", "european_format": False},
    "amazon.com": {"currency": "USD", "language": "en-US,en;q=0.9", "european_format": False},
    "amazon.ca": {"currency": "CAD", "language": "en-CA,en;q=0.9,fr;q=0.8", "european_format": False},
    "amazon.co.jp": {"currency": "JPY", "language": "ja-JP,ja;q=0.9,en;q=0.8", "european_format": False},
    "amazon.com.au": {"currency": "AUD", "language": "en-AU,en;q=0.9", "european_format": False},
    "amazon.com.br": {"currency": "BRL", "language": "pt-BR,pt;q=0.9,en;q=0.8", "european_format": True},
    "amazon.com.mx": {"currency": "MXN", "language": "es-MX,es;q=0.9,en;q=0.8", "european_format": False},
    "amazon.in": {"currency": "INR", "language": "en-IN,en;q=0.9", "european_format": False},
    "amazon.com.tr": {"currency": "TRY", "language": "tr-TR,tr;q=0.9,en;q=0.8", "european_format": True},
    "amazon.ae": {"currency": "AED", "language": "en-AE,en;q=0.9,ar;q=0.8", "european_format": False},
    "amazon.sg": {"currency": "SGD", "language": "en-SG,en;q=0.9", "european_format": False},
}

DEFAULT_MARKETPLACE = "amazon.it"

# Price selectors — ordered by reliability (Amazon DOM 2025-2026)
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
# Human-readable availability string (e.g. "Solo 3 rimasti in magazzino")
AVAILABILITY_SELECTOR = "#availability span"

# Wishlist — matches both /hz/wishlist/ls/ and legacy /gp/registry/wishlist/ URLs
# Group 1 = marketplace suffix (e.g. "it", "co.uk"), Group 2 = wishlist ID
WISHLIST_ID_RE = r"amazon\.([a-z.]+)/(?:hz/wishlist/ls|gp/registry/wishlist)/([A-Z0-9]{10,})"
