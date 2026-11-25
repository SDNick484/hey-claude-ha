"""Shared fixtures for Hey Claude tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.hey_claude.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_URL,
    DOMAIN,
)

from .fake_relay import FakeRelay

TEST_URL = "https://relay.example.com"
TEST_CLIENT_ID = "test-client-id.access"
TEST_SECRET = "TEST-SECRET-6f1c"
SATELLITE = "assist_satellite.test_satellite"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,
) -> Generator[None]:
    """Let Home Assistant load the integration from custom_components."""
    yield


@pytest.fixture(autouse=True)
async def setup_homeassistant_core(hass: HomeAssistant) -> None:
    """Load the core component, which every real install has."""
    assert await async_setup_component(hass, "homeassistant", {})


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for a relay."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Hey Claude",
        unique_id=TEST_URL,
        data={
            CONF_URL: TEST_URL,
            CONF_CLIENT_ID: TEST_CLIENT_ID,
            CONF_CLIENT_SECRET: TEST_SECRET,
        },
    )


@pytest.fixture
def fake_relay(aioclient_mock: AiohttpClientMocker) -> FakeRelay:
    """Return a fake relay answering at TEST_URL."""
    return FakeRelay(aioclient_mock, TEST_URL)


@pytest.fixture
def satellite(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> tuple[str, str]:
    """Return (device_id, entity_id) of a satellite with no areas."""
    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("test", "sat")}
    )
    entity = entity_registry.async_get_or_create(
        "assist_satellite",
        "test",
        "sat",
        device_id=device.id,
        suggested_object_id="test_satellite",
        original_name="Assist satellite",
        has_entity_name=True,
    )
    assert entity.entity_id == SATELLITE
    return device.id, entity.entity_id
