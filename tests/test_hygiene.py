"""The integration never logs credentials, the relay host, or what was said."""

from __future__ import annotations

import json
import logging

import pytest
from aiohttp import ClientConnectorError
from aiohttp.client_reqrep import ConnectionKey
from homeassistant import config_entries
from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.hey_claude.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DEFAULT_PROFILE,
    CONF_URL,
    DOMAIN,
)

from .conftest import TEST_CLIENT_ID, TEST_SECRET, TEST_URL
from .fake_relay import Error, FakeRelay, Raise, Raw, Reply

NEW_SECRET = "NEW-SECRET-77a0"
SAID = "unique words for the log check"
REPLIED = "distinct reply for the log check"
SECRET_PROMPT = "passphrase prompt for the log check?"
ACCESS_LOGIN = "https://example.cloudflareaccess.com/cdn-cgi/access/login/relay"
OWN_LOGGERS = "custom_components.hey_claude"


def _connector_error() -> ClientConnectorError:
    key = ConnectionKey("relay.example.com", 443, True, True, None, None, None)
    return ClientConnectorError(key, OSError(111, "Connection refused"))


async def test_secret_and_words_never_logged(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    fake_relay: FakeRelay,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Run every path at DEBUG and look for anything that must stay private."""
    caplog.set_level(logging.DEBUG)

    # Setup.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_URL: TEST_URL,
            CONF_CLIENT_ID: TEST_CLIENT_ID,
            CONF_CLIENT_SECRET: TEST_SECRET,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    # Reauth, with one refusal first.
    fake_relay.queue_turn(Raw(403, "<html>"))
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )
    for secret in ("WRONG-SECRET-x1", NEW_SECRET):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_CLIENT_ID: TEST_CLIENT_ID, CONF_CLIENT_SECRET: secret},
        )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()

    # Reconfigure, keeping the secret.
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: TEST_URL, CONF_CLIENT_ID: TEST_CLIENT_ID, CONF_CLIENT_SECRET: ""},
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    # Options.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DEFAULT_PROFILE: "home"}
    )
    await hass.async_block_till_done()

    # Turns: a reply, a relay error, a refused token, a passphrase request,
    # and an unreachable relay whose aiohttp error names the host.
    fake_relay.queue_turn(
        Reply(REPLIED),
        Error(500, "internal", "relay words for the log check"),
        Raw(302, "", headers={"Location": ACCESS_LOGIN}),
        Reply(SECRET_PROMPT, expect_secret=True),
        Raise(_connector_error()),
        Raise(_connector_error()),
    )
    for _ in range(5):
        await conversation.async_converse(
            hass, SAID, None, Context(), agent_id="conversation.claude"
        )
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)

    everything = caplog.text
    for private in (TEST_SECRET, NEW_SECRET, "WRONG-SECRET-x1", TEST_CLIENT_ID):
        assert private not in everything, private

    ours = "\n".join(
        record.getMessage()
        + (
            logging.Formatter().formatException(record.exc_info)
            if record.exc_info
            else ""
        )
        for record in caplog.records
        if record.name.startswith(OWN_LOGGERS)
    )
    assert ours, "expected the integration to log something at DEBUG"
    for private in (SAID, REPLIED, SECRET_PROMPT, "relay words", "relay.example.com"):
        assert private not in ours, private

    dumped = json.dumps(diagnostics)
    for private in (TEST_SECRET, NEW_SECRET, TEST_CLIENT_ID, "relay.example.com"):
        assert private not in dumped, private
