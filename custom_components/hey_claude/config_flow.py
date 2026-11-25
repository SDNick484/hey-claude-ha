"""Config flow for Hey Claude."""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class HeyClaudeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hey Claude."""

    VERSION = 1
