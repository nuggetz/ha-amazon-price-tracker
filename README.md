# Amazon Price Tracker for Home Assistant

Custom component per il monitoraggio prezzi Amazon.it, senza PA-API.

## Installazione

1. Copia `custom_components/amazon_price_tracker/` in `config/custom_components/`
2. Riavvia Home Assistant
3. Aggiungi integrazione via UI: **Impostazioni → Integrazioni → Aggiungi → Amazon Price Tracker**

## Configurazione

Ogni prodotto va aggiunto singolarmente tramite il Config Flow UI.

| Campo | Descrizione |
|-------|-------------|
| ASIN | Codice prodotto Amazon (es. `B09FKN79QR`) |
| Nome personalizzato | Nome visualizzato in HA (es. `Kingston 32GB DDR5`) |
| Soglia prezzo | Opzionale, usata nelle automazioni HA |

## Sensori esposti

Ogni prodotto genera un sensore con:

- **state**: prezzo attuale in EUR (`float`)
- **asin**: codice ASIN
- **title**: titolo da Amazon
- **url**: link alla pagina prodotto
- **min_price**: minimo storico rilevato (persistito tra i riavvii)
- **min_price_date**: data del minimo storico
- **is_available**: `true` se il prodotto è acquistabile
- **alert_threshold**: soglia configurata dall'utente
- **last_updated**: timestamp ultimo fetch riuscito

## Grafici Lovelace

```yaml
type: history-graph
entities:
  - entity: sensor.kingston_32gb_ddr5
title: Andamento prezzo
hours_to_show: 720
```

## Automazione alert prezzo

```yaml
alias: "Alert prezzo RAM sotto soglia"
trigger:
  - platform: numeric_state
    entity_id: sensor.kingston_32gb_ddr5
    below: "{{ state_attr('sensor.kingston_32gb_ddr5', 'alert_threshold') }}"
action:
  - service: notify.mobile_app
    data:
      title: "Prezzo in calo!"
      message: >
        {{ state_attr('sensor.kingston_32gb_ddr5', 'title') }}
        è sceso a {{ states('sensor.kingston_32gb_ddr5') }}€
```

## Note tecniche

- Polling ogni 4 ore con jitter ±30 min (anti-ban)
- Scraping diretto senza Amazon PA-API
- Parsing JSON-LD prima, CSS selectors come fallback
- `min_price` persistito tramite `RestoreSensor` (sopravvive ai riavvii)
- Nessuna dipendenza da database esterno

## Debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.amazon_price_tracker: debug
```
