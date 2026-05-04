# Amazon Price Tracker for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.11%2B-blue)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Track Amazon.it product prices directly in Home Assistant — no PA-API or third-party account required.

Each product is exposed as a sensor whose state is the current price in EUR. Price history is stored natively by the HA Recorder, so you get built-in graphs for free. Alerts are handled by standard HA automations.

---

## Features

- Scrapes Amazon.it product pages (JSON-LD first, CSS selectors as fallback)
- One sensor per product, added via UI Config Flow
- Tracks historical minimum price, persisted across HA restarts
- Detects out-of-stock products
- Anti-fingerprinting: randomised polling interval (~4 h ± 30 min)
- No external database, no Amazon account needed

---

## Installation

### HACS (recommended)

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/nuggetz/ha-amazon-price-tracker` — category **Integration**
3. Install **Amazon Price Tracker** and restart Home Assistant

### Manual

1. Copy `custom_components/amazon_price_tracker/` into your HA `config/custom_components/` folder
2. Restart Home Assistant

---

## Configuration

Go to **Settings → Integrations → Add integration → Amazon Price Tracker**.

Each product is added individually. Add as many as you need.

| Field | Required | Description |
| ------- | ---------- | ----------- |
| ASIN | Yes | 10-character Amazon product code (e.g. `B09FKN79QR`) |
| Custom name | Yes | Label shown in Home Assistant (e.g. `Kingston 32GB DDR5`) |
| Price alert threshold (EUR) | No | Used in automations to trigger below a target price |

> **Finding the ASIN:** open the Amazon.it product page. The ASIN is in the URL after `/dp/` (e.g. `amazon.it/dp/B09FKN79QR`) or in the product details section.

---

## Sensor

Each product creates one sensor entity under a dedicated device.

| Attribute | Type | Description |
| ----------- | ------ | ----------- |
| `state` | `float` | Current price in EUR |
| `asin` | `str` | Amazon ASIN |
| `title` | `str` | Product title from Amazon |
| `url` | `str` | Link to the product page |
| `min_price` | `float` | Lowest price ever recorded (survives restarts) |
| `min_price_date` | `str ISO` | Date the minimum was recorded |
| `is_available` | `bool` | `false` when the product is out of stock |
| `alert_threshold` | `float` or `null` | Threshold configured by the user |
| `last_updated` | `str ISO` | Timestamp of the last successful fetch |

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
        dropped to {{ states('sensor.kingston_32gb_ddr5') }} EUR
        (threshold: {{ state_attr('sensor.kingston_32gb_ddr5', 'alert_threshold') }} EUR)
```

---

## Technical notes

- Polling every ~4 hours with ±30 min jitter (reduces Amazon fingerprinting)
- Direct HTML scraping: JSON-LD structured data first, CSS selectors as fallback
- `min_price` uses `RestoreSensor` — survives HA restarts without an external DB
- HTTP client: `httpx` async (not `aiohttp`, to avoid version conflicts with HA internals)
- BeautifulSoup runs in an executor thread (non-blocking)

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

- [ ] Options Flow (edit threshold without removing the entry)
- [ ] `amazon_price_tracker.force_refresh` service call
- [ ] Multi-domain support (Amazon.de, Amazon.com)
- [ ] Proxy support for blocked IPs
- [ ] GitHub Actions release workflow for HACS community store

---

## License

MIT — see [LICENSE](LICENSE).
