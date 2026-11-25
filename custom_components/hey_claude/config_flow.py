"""Config flow for Hey Claude: setup, reauth and reconfigure."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_URL,
    DOMAIN,
    SETUP_TEST_TEXT,
)
from .relay import (
    RelayAuthError,
    RelayClient,
    RelayConnectionError,
    RelayError,
    RelayTimeoutError,
    normalize_url,
)

_LOGGER = logging.getLogger(__name__)

TITLE = "Hey Claude"

URL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
TEXT_SELECTOR = TextSelector()
SECRET_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def validate_relay(
    hass: HomeAssistant, url: str, client_id: str, client_secret: str
) -> None:
    """Check the relay answers and accepts the token, with one real turn.

    Raises the relay module's exceptions.
    """
    client = RelayClient(async_get_clientsession(hass), url, client_id, client_secret)
    await client.health()
    reply = await client.turn(SETUP_TEST_TEXT)
    try:
        await client.end_conversation(reply.conversation_id)
    except RelayError as err:
        _LOGGER.debug("Could not end the setup test conversation: %s", err.code)


async def _errors_for(
    hass: HomeAssistant, url: str, client_id: str, client_secret: str
) -> dict[str, str]:
    """Validate and return the form errors, empty when the relay is good."""
    try:
        await validate_relay(hass, url, client_id, client_secret)
    except RelayAuthError:
        return {"base": "invalid_auth"}
    except RelayConnectionError, RelayTimeoutError:
        return {"base": "cannot_connect"}
    except RelayError as err:
        if err.code == "redirect":
            return {"base": "redirected"}
        if err.code in ("unexpected_response", "bad_response"):
            return {"base": "not_relay"}
        if err.status == 403:
            return {"base": "not_allowed"}
        return {"base": "relay_error"}
    except Exception:
        _LOGGER.exception("Unexpected error validating the relay")
        return {"base": "unknown"}
    return {}


class HeyClaudeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hey Claude."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the relay URL and the Access service token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                client_id = user_input[CONF_CLIENT_ID].strip()
                client_secret = user_input[CONF_CLIENT_SECRET].strip()
                errors = await _errors_for(self.hass, url, client_id, client_secret)
                if not errors:
                    return self.async_create_entry(
                        title=TITLE,
                        data={
                            CONF_URL: url,
                            CONF_CLIENT_ID: client_id,
                            CONF_CLIENT_SECRET: client_secret,
                        },
                    )

        suggested = {
            key: value
            for key, value in (user_input or {}).items()
            if key != CONF_CLIENT_SECRET
        }
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_URL): URL_SELECTOR,
                        probatio.Required(CONF_CLIENT_ID): TEXT_SELECTOR,
                        probatio.Required(CONF_CLIENT_SECRET): SECRET_SELECTOR,
                    }
                ),
                suggested,
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth when the relay or Access refuses the token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new Access service token."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            client_id = user_input[CONF_CLIENT_ID].strip()
            client_secret = user_input[CONF_CLIENT_SECRET].strip()
            errors = await _errors_for(
                self.hass, entry.data[CONF_URL], client_id, client_secret
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_CLIENT_ID: client_id,
                        CONF_CLIENT_SECRET: client_secret,
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_CLIENT_ID): TEXT_SELECTOR,
                        probatio.Required(CONF_CLIENT_SECRET): SECRET_SELECTOR,
                    }
                ),
                {CONF_CLIENT_ID: entry.data[CONF_CLIENT_ID]},
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the relay URL or token. A blank secret keeps the stored one."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                if url != entry.unique_id:
                    await self.async_set_unique_id(url)
                    self._abort_if_unique_id_configured()
                client_id = user_input[CONF_CLIENT_ID].strip()
                client_secret = (
                    user_input.get(CONF_CLIENT_SECRET, "").strip()
                    or entry.data[CONF_CLIENT_SECRET]
                )
                errors = await _errors_for(self.hass, url, client_id, client_secret)
                if not errors:
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=url,
                        data_updates={
                            CONF_URL: url,
                            CONF_CLIENT_ID: client_id,
                            CONF_CLIENT_SECRET: client_secret,
                        },
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_URL): URL_SELECTOR,
                        probatio.Required(CONF_CLIENT_ID): TEXT_SELECTOR,
                        probatio.Optional(CONF_CLIENT_SECRET): SECRET_SELECTOR,
                    }
                ),
                {
                    CONF_URL: entry.data[CONF_URL],
                    CONF_CLIENT_ID: entry.data[CONF_CLIENT_ID],
                },
            ),
            errors=errors,
        )
