"""Tests for Config Flow and Options Flow."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.amazon_price_tracker.const import DOMAIN

WISHLIST_HTML = """
<html><body><ul>
<li class="g-item-sortable"
    data-reposition-action-params='{"itemExternalId":"ASIN:B09FKN79QR|A1F83G8C2ARO7P"}'>
  <a id="itemName_A" href="/dp/B09FKN79QR" title="Kingston 32GB DDR5">Kingston 32GB DDR5</a>
</li>
<li class="g-item-sortable"
    data-reposition-action-params='{"itemExternalId":"ASIN:B0D6NMDNNX|A1F83G8C2ARO7P"}'>
  <a id="itemName_B" href="/dp/B0D6NMDNNX" title="Sapphire RX 9070 XT">Sapphire RX 9070 XT</a>
</li>
</ul></body></html>
"""


@pytest.fixture
def mock_setup_entry():
    """Prevent actual coordinator setup during flow tests."""
    with patch(
        "custom_components.amazon_price_tracker.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock


def _mock_session(**kwargs) -> MagicMock:
    """Stand-in for the shared AmazonSession returned by async_get_session."""
    session = MagicMock()
    for key, value in kwargs.items():
        setattr(session, key, value)
    return session


@pytest.fixture
def mock_reachable():
    """Make the connectivity check always pass."""
    with patch(
        "custom_components.amazon_price_tracker.config_flow."
        "AmazonPriceTrackerConfigFlow._check_reachable",
        return_value=True,
    ) as mock:
        yield mock


# ---------------------------------------------------------------------------
# Step: user (menu)
# ---------------------------------------------------------------------------

async def test_user_step_shows_menu(hass: HomeAssistant, mock_setup_entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.MENU
    assert set(result["menu_options"]) == {"add_product", "import_wishlist"}


# ---------------------------------------------------------------------------
# Step: add_product
# ---------------------------------------------------------------------------

async def test_add_product_creates_entry(
    hass: HomeAssistant, mock_setup_entry, mock_reachable
):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "add_product"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"asin": "B09FKN79QR", "name": "Test Product", "marketplace": "amazon.it"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["asin"] == "B09FKN79QR"
    assert result["data"]["name"] == "Test Product"
    assert result["data"]["marketplace"] == "amazon.it"
    assert result["data"]["alert_threshold"] is None


async def test_add_product_with_threshold(
    hass: HomeAssistant, mock_setup_entry, mock_reachable
):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "add_product"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "asin": "B09FKN79QR",
            "name": "Test Product",
            "marketplace": "amazon.it",
            "alert_threshold": 250.0,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["alert_threshold"] == 250.0


async def test_add_product_invalid_asin(hass: HomeAssistant, mock_setup_entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "add_product"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"asin": "TOOSHORT", "name": "Test", "marketplace": "amazon.it"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get("asin") == "invalid_asin"


async def test_add_product_cannot_connect(hass: HomeAssistant, mock_setup_entry):
    with patch(
        "custom_components.amazon_price_tracker.config_flow."
        "AmazonPriceTrackerConfigFlow._check_reachable",
        return_value=False,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "add_product"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"asin": "B09FKN79QR", "name": "Test", "marketplace": "amazon.it"},
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get("base") == "cannot_connect"


async def test_add_product_duplicate_aborts(
    hass: HomeAssistant, mock_setup_entry, mock_reachable
):
    for _ in range(2):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "add_product"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"asin": "B09FKN79QR", "name": "Test Product", "marketplace": "amazon.it"},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Step: import_wishlist
# ---------------------------------------------------------------------------

async def test_import_wishlist_invalid_url(hass: HomeAssistant, mock_setup_entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_wishlist"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "https://www.not-amazon.com/list/123"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get("url") == "invalid_wishlist_url"


async def test_import_wishlist_success(hass: HomeAssistant, mock_setup_entry):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = WISHLIST_HTML

    session = _mock_session(async_get=AsyncMock(return_value=mock_response))

    with patch(
        "custom_components.amazon_price_tracker.config_flow.async_get_session",
        return_value=session,
    ):

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "import_wishlist"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"url": "https://www.amazon.it/hz/wishlist/ls/ABCDEFGHIJ12"},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "wishlist_imported"
    assert result["description_placeholders"]["added"] == "2"
    assert result["description_placeholders"]["total"] == "2"
    session.async_get.assert_awaited_once()


async def test_import_wishlist_http_error(hass: HomeAssistant, mock_setup_entry):
    import httpx

    session = _mock_session(
        async_get=AsyncMock(side_effect=httpx.ConnectError("timeout"))
    )

    with patch(
        "custom_components.amazon_price_tracker.config_flow.async_get_session",
        return_value=session,
    ):

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "import_wishlist"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"url": "https://www.amazon.it/hz/wishlist/ls/ABCDEFGHIJ12"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get("base") == "cannot_connect"


# ---------------------------------------------------------------------------
# Step: import (SOURCE_IMPORT — used by the service)
# ---------------------------------------------------------------------------

async def test_source_import_creates_entry(hass: HomeAssistant, mock_setup_entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_IMPORT},
        data={
            "asin": "B09FKN79QR",
            "name": "Imported Product",
            "marketplace": "amazon.it",
            "alert_threshold": None,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["asin"] == "B09FKN79QR"


async def test_source_import_duplicate_aborts(hass: HomeAssistant, mock_setup_entry):
    data = {
        "asin": "B09FKN79QR",
        "name": "Imported Product",
        "marketplace": "amazon.it",
        "alert_threshold": None,
    }
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Options Flow
# ---------------------------------------------------------------------------

async def test_options_flow_updates_name_and_threshold(
    hass: HomeAssistant, mock_setup_entry, mock_reachable
):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "add_product"}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"asin": "B09FKN79QR", "name": "Original Name", "marketplace": "amazon.it"},
    )

    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Updated Name", "alert_threshold": 199.99},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["name"] == "Updated Name"
    assert result["data"]["alert_threshold"] == 199.99
