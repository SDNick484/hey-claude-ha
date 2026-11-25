"""The Hey Claude integration: a hey-claude-relay as a conversation agent."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_URL
from .relay import RelayClient

PLATFORMS: list[Platform] = []


@dataclass
class HeyClaudeData:
    """What a loaded entry keeps at runtime."""

    client: RelayClient


type HeyClaudeConfigEntry = ConfigEntry[HeyClaudeData]


async def async_setup_entry(hass: HomeAssistant, entry: HeyClaudeConfigEntry) -> bool:
    """Set up Hey Claude from a config entry.

    No network calls here: if the relay is down when Home Assistant starts,
    the agent still loads and says so on each turn.
    """
    entry.runtime_data = HeyClaudeData(
        client=RelayClient(
            async_get_clientsession(hass),
            entry.data[CONF_URL],
            entry.data[CONF_CLIENT_ID],
            entry.data[CONF_CLIENT_SECRET],
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HeyClaudeConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
