# Amazon Price Tracker for Home Assistant

![Amazon Price Tracker logo](docs/amazon_price_tracker_logo.svg)

[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/default)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.11%2B-blue)](https://www.home-assistant.io/)
[![GitHub Release](https://img.shields.io/github/v/release/nuggetz/ha-amazon-price-tracker)](https://github.com/nuggetz/ha-amazon-price-tracker/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/nuggetz/ha-amazon-price-tracker?style=social)](https://github.com/nuggetz/ha-amazon-price-tracker/stargazers)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nuggetz&repository=ha-amazon-price-tracker&category=integration)

Track Amazon product prices directly in Home Assistant — no PA-API or third-party account required.

Each product is exposed as a sensor whose state is the current price. Price history is stored natively by the HA Recorder, so you get built-in graphs for free. Alerts are handled by standard HA automations.

---

## Features

- **20 Amazon marketplaces**: IT, DE, FR, ES, NL, BE, PL, SE, UK, IE, US, CA, JP, AU, BR, MX, IN, TR, AE, SG — each with the correct currency and language
- **Auto-detected default marketplace**: the marketplace dropdown pre-selects the one matching your Home Assistant country setting — no manual change needed for non-Italian installs
- Scrapes product pages without an Amazon account (JSON-LD first, CSS selectors as fallback)
- One sensor per product, added via UI Config Flow — edit name and alert threshold at any time via Options Flow
- Tracks historical minimum price, persisted across HA restarts
- Real-time stock status: `is_available` bool + `availability_text` from Amazon (e.g. "Only 2 left in stock")
- `amazon_price_tracker.force_refresh` service for on-demand price updates
- Anti-fingerprinting: randomised polling interval (~4 h ± 30 min)
- No external database, no Amazon account needed

---

## Supported marketplaces

| Marketplace | Currency |
| ----------- | -------- |
| amazon.it | EUR |
| amazon.de | EUR |
| amazon.fr | EUR |
| amazon.es | EUR |
| amazon.nl | EUR |
| amazon.be | EUR |
| amazon.pl | PLN |
| amazon.se | SEK |
| amazon.co.uk | GBP |
| amazon.ie | EUR |
| amazon.com | USD |
| amazon.ca | CAD |
| amazon.co.jp | JPY |
| amazon.com.au | AUD |
| amazon.com.br | BRL |
| amazon.com.mx | MXN |
| amazon.in | INR |
| amazon.com.tr | TRY |
| amazon.ae | AED |
| amazon.sg | SGD |

---

## Installation

### HACS (recommended)

**Amazon Price Tracker is now part of the default HACS store** — no custom repository needed.

1. Open HACS → search for **Amazon Price Tracker**
2. Click **Download** and restart Home Assistant

Or use the one-click button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nuggetz&repository=ha-amazon-price-tracker&category=integration)

### Manual

1. Copy `custom_components/amazon_price_tracker/` into your HA `config/custom_components/` folder
2. Restart Home Assistant

---

## Configuration

Go to **Settings → Integrations → Add integration → Amazon Price Tracker**.

When adding the integration you can choose between two modes:

- **Add product** — add a single product by ASIN
- **Import from wishlist** — import all products from a public Amazon wishlist at once

![Config Flow menu](docs/screenshots/config-flow.png)

### Add product

| Field | Required | Description |
| ----- | -------- | ----------- |
| ASIN | Yes | 10-character Amazon product code (e.g. `B09FKN79QR`) |
| Custom name | Yes | Label shown in Home Assistant (e.g. `Kingston 32GB DDR5`) |
| Amazon marketplace | Yes | Which Amazon site to track — pre-selected automatically from your HA country setting |
| Price alert threshold | No | Used in automations to trigger below a target price |

> **Finding the ASIN:** open the product page on Amazon. The ASIN is in the URL after `/dp/` (e.g. `amazon.de/dp/B09FKN79QR`) or in the product details section near the bottom of the page. For products with variants (colour, size, storage…), select the exact variant first, then copy the URL.

### Import from wishlist

| Field | Required | Description |
| ----- | -------- | ----------- |
| Wishlist URL | Yes | Full URL of a **public** Amazon wishlist |
| Price alert threshold | No | Applied to all imported products (editable per-product later) |

The wishlist must be set to **Public** on Amazon (Account → Lists → Manage list → Privacy: Public). Only the first page (~40 products) is scraped.

To **edit** the name or alert threshold of an existing product, go to the integration panel and click **Configure** — no need to remove and re-add.

---

## Sensor

Each product creates one sensor entity under a dedicated device.

| Attribute | Type | Description |
| --------- | ---- | ----------- |
| `state` | `float` | Current price in the marketplace currency |
| `asin` | `str` | Amazon ASIN |
| `marketplace` | `str` | Marketplace being tracked (e.g. `amazon.de`) |
| `title` | `str` | Product title from Amazon |
| `url` | `str` | Link to the product page |
| `min_price` | `float` | Lowest price ever recorded (survives HA restarts) |
| `min_price_date` | `str ISO` | Date the minimum was recorded |
| `is_available` | `bool` | `false` when the product is out of stock |
| `availability_text` | `str` | Raw stock message from Amazon (e.g. "Only 2 left in stock") |
| `alert_threshold` | `float` or `null` | Threshold configured by the user |
| `last_updated` | `str ISO` | Timestamp of the last successful fetch |

![Sensor attributes](docs/screenshots/entity-states.png)

---

## Services

### `amazon_price_tracker.import_wishlist`

Import all products from a **public** Amazon wishlist in one shot. One sensor is created per product; products already configured are skipped.

> The wishlist must be set to **Public** on Amazon (Account → Lists → Manage list → Privacy: Public).

```yaml
service: amazon_price_tracker.import_wishlist
data:
  url: "https://www.amazon.it/hz/wishlist/ls/XXXXXXXXXXXXXXXX"
  # marketplace: "amazon.it"     # optional, auto-detected from URL
  # alert_threshold: 150.00      # optional, applied to all imported products
```

Only the first page of the wishlist is scraped (~40 products). For longer lists, call the service multiple times with paginated URLs or split the wishlist.

---

### `amazon_price_tracker.force_refresh`

Immediately fetch the latest price without waiting for the next scheduled poll.

**Refresh all tracked products:**

```yaml
service: amazon_price_tracker.force_refresh
```

**Refresh a specific product:**

```yaml
service: amazon_price_tracker.force_refresh
target:
  entity_id: sensor.kingston_32gb_ddr5
```

---

## Price history graph

```yaml
type: history-graph
entities:
  - entity: sensor.kingston_32gb_ddr5
title: Price trend
hours_to_show: 720  # 30 days
```

Or with [mini-graph-card](https://github.com/kalkih/mini-graph-card) (HACS):

```yaml
type: custom:mini-graph-card
entities:
  - sensor.kingston_32gb_ddr5
hours_to_show: 720
```

![Price history graph](docs/screenshots/statistics.png)

---

## Price alert automation

```yaml
alias: "RAM price drop alert"
trigger:
  - platform: numeric_state
    entity_id: sensor.kingston_32gb_ddr5
    below: "{{ state_attr('sensor.kingston_32gb_ddr5', 'alert_threshold') }}"
action:
  - service: notify.mobile_app
    data:
      title: "Price drop!"
      message: >
        {{ state_attr('sensor.kingston_32gb_ddr5', 'title') }}
        dropped to {{ states('sensor.kingston_32gb_ddr5') }}
        (threshold: {{ state_attr('sensor.kingston_32gb_ddr5', 'alert_threshold') }})
```

---

## Technical notes

- Default marketplace is auto-detected from `hass.config.country` (ISO 3166-1 alpha-2); falls back to `amazon.it` if unset
- Polling every ~4 hours with ±30 min jitter (reduces Amazon fingerprinting)
- Direct HTML scraping: JSON-LD structured data first, CSS selectors as fallback, composite whole+fraction as last resort
- `min_price` uses `RestoreSensor` — survives HA restarts without an external DB
- HTTP client: `httpx` async (not `aiohttp`, to avoid version conflicts with HA internals)
- HTML parsing runs in an executor thread (non-blocking)
- Each marketplace uses the correct `Accept-Language` header and decimal format

---

## Troubleshooting

### `Amazon is blocking scraping for ASIN … — retrying in 30 min`

Amazon answered with an anti-bot page instead of the product listing: either the
CAPTCHA wall, or the "Click the button below to continue shopping" interstitial,
which is served with HTTP 200 and looks like a normal page. The sensor goes
unavailable and the integration retries every 30 minutes until Amazon serves the
real page again.

This is a decision made on Amazon's side about your IP address, not a bug in the
parser. What helps:

- **Wait.** Blocks on residential IPs are usually temporary.
- **Track fewer products.** Every product is a separate request; a large wishlist
  import makes a block far more likely.
- **Check what else shares your IP.** A VPN exit node, a hosting/datacenter IP or
  another scraper on the same connection will get you flagged much faster.

Proxy support for permanently blocked IPs is on the roadmap.

### `Could not parse price for ASIN … on what looks like a real product page`

Amazon served a genuine listing but none of the price strategies matched — most
likely a layout change on that marketplace. Enable debug logging (below), wait
for the next refresh, and [open an issue](https://github.com/nuggetz/ha-amazon-price-tracker/issues)
with the captured page; that log line contains the full HTML the parser saw.

---

## Debug logging

Add to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.amazon_price_tracker: debug
```

---

## Roadmap

- [x] Options Flow (edit name and threshold without removing the entry)
- [x] `amazon_price_tracker.force_refresh` service call
- [x] Multi-domain support (20 Amazon marketplaces)
- [x] Real-time availability text
- [x] Wishlist import — from Config Flow UI and from Developer Tools service
- [x] Accepted into the default HACS store 🎉
- [ ] Proxy support for blocked IPs
- [ ] Product image as `entity_picture` attribute

---

## License

MIT — see [LICENSE](LICENSE).
