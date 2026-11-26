"""Tests for diagnostics."""

from __future__ import annotations

import json

from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .conftest import TEST_CLIENT_ID, TEST_SECRET
from .fake_relay import FakeRelay


async def test_diagnostics_redacted(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Diagnostics carry no URL, client ID or secret."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    text = json.dumps(result)
    assert TEST_SECRET not in text
    assert TEST_CLIENT_ID not in text
    assert "relay.example.com" not in text
    assert result["entry"]["data"]["client_secret"] == "**REDACTED**"


async def test_diagnostics_counts_conversations(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    fake_relay: FakeRelay,
) -> None:
    """Diagnostics say how many conversations are mapped to the relay."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await conversation.async_converse(
        hass, "hello", None, Context(), agent_id="conversation.claude"
    )

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    assert result["conversations_tracked"] == 1
