DOMAIN = "amazon_price_tracker"

# URL template — marketplace and asin are injected at runtime
BASE_URL = "https://www.{marketplace}/dp/{asin}"
REQUEST_TIMEOUT = 30

BASE_INTERVAL_SECONDS = 4 * 3600
JITTER_SECONDS = 30 * 60

ASIN_PATTERN = r"^[A-Z0-9]{10}$"

# Base HTTP headers — Accept-Language is overridden per marketplace.
# Accept-Encoding is deliberately absent: httpx sets it from the codecs it can
# actually decode, and advertising "br" without brotli installed yields a body
# that decodes to binary garbage.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    # A request that claims to be Chrome should carry the client hints and the
    # fetch metadata a Chrome top-level navigation actually sends; the mismatch
    # is trivial for Amazon to spot.
    "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
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
    "amazon.ie": {"currency": "EUR", "language": "en-IE,en;q=0.9", "european_format": False},
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
    "#apex_desktop span.a-offscreen",
    "#buybox span.a-price span.a-offscreen",
    "#tp_price_block_total_price_ww span.a-offscreen",
    ".a-price .a-offscreen",
]

TITLE_SELECTORS = [
    "#productTitle",
    "#title span",
]

# Markers of an Amazon anti-bot page served with HTTP 200 instead of the
# product. Matched case-insensitively against the raw HTML.
# The first two are locale-independent — the "Continue shopping" interstitial
# and the CAPTCHA wall both post to /errors_page/validateCaptcha in every
# marketplace, so they catch localised variants the English strings miss.
BOT_WALL_SIGNALS = [
    "/errors_page/validatecaptcha",
    "/errors/validatecaptcha",
    "opfcaptcha-prod",
    "api-services-support@amazon.com",
    "robot check",
    "enter the characters you see below",
    "digita i caratteri che vedi",
    "type the characters you see in this image",
]

# Deprecated alias kept for external callers.
CAPTCHA_SIGNALS = BOT_WALL_SIGNALS

# A real product page is hundreds of KB. Anything this small carrying neither a
# title nor a price is an interstitial or error shell, not a product.
MIN_PRODUCT_PAGE_BYTES = 100_000

# Presence of this div means the product is out of stock
OUT_OF_STOCK_SELECTOR = "#outOfStockBuyBox_feature_div"
# Human-readable availability string (e.g. "Solo 3 rimasti in magazzino")
AVAILABILITY_SELECTOR = "#availability span"

# Wishlist — matches both /hz/wishlist/ls/ and legacy /gp/registry/wishlist/ URLs
# Group 1 = marketplace suffix (e.g. "it", "co.uk"), Group 2 = wishlist ID
WISHLIST_ID_RE = r"amazon\.([a-z.]+)/(?:hz/wishlist/ls|gp/registry/wishlist)/([A-Z0-9]{10,})"
