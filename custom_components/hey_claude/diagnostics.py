"""Diagnostics for Hey Claude."""

from __future__ import annotations

from typing import Any, Final

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import HeyClaudeConfigEntry
from .const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_URL

TO_REDACT: Final = {CONF_URL, CONF_CLIENT_ID, CONF_CLIENT_SECRET, "unique_id", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HeyClaudeConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, without the URL or credentials."""
    return {"entry": async_redact_data(entry.as_dict(), TO_REDACT)}
