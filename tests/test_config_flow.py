"""Tests for the setup, reauth and reconfigure flows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.hey_claude.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_URL,
    DOMAIN,
    SETUP_TEST_TEXT,
)

from .conftest import TEST_CLIENT_ID, TEST_SECRET, TEST_URL
from .fake_relay import Error, FakeRelay, Raise, Raw

OTHER_URL = "https://other.example.com"

USER_INPUT = {
    CONF_URL: TEST_URL + "/",
    CONF_CLIENT_ID: TEST_CLIENT_ID,
    CONF_CLIENT_SECRET: TEST_SECRET,
}


async def _start_user_flow(hass: HomeAssistant) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    return result


async def test_user_flow_success(hass: HomeAssistant, fake_relay: FakeRelay) -> None:
    """A good relay and token create an entry after a test turn."""
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hey Claude"
    assert result["data"] == {
        CONF_URL: TEST_URL,
        CONF_CLIENT_ID: TEST_CLIENT_ID,
        CONF_CLIENT_SECRET: TEST_SECRET,
    }
    assert result["result"].unique_id == TEST_URL
    [body] = fake_relay.turn_requests
    assert body["text"] == SETUP_TEST_TEXT
    assert "profile" not in body
    assert fake_relay.ended == ["relay-conv-1"]


async def test_user_flow_end_failure_still_creates_entry(
    hass: HomeAssistant, fake_relay: FakeRelay
) -> None:
    """Failing to end the test conversation does not fail setup."""
    fake_relay.end_ok = False
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY


def _health_down(relay: FakeRelay) -> None:
    relay.health_ok = False


def _queue(outcome: Any) -> Callable[[FakeRelay], None]:
    return lambda relay: relay.queue_turn(outcome)


@pytest.mark.parametrize(
    ("break_relay", "url", "error"),
    [
        (_health_down, TEST_URL, "cannot_connect"),
        (_queue(Raw(302, "")), TEST_URL, "invalid_auth"),
        (_queue(Raw(403, "<html>")), TEST_URL, "invalid_auth"),
        (_queue(Error(401, "unauthorized")), TEST_URL, "invalid_auth"),
        (_queue(Error(403, "unauthorized")), TEST_URL, "not_allowed"),
        (_queue(Raise(TimeoutError())), TEST_URL, "cannot_connect"),
        (_queue(Error(500, "internal")), TEST_URL, "relay_error"),
        (lambda relay: None, "relay.example.com", "invalid_url"),
    ],
    ids=[
        "health-down",
        "access-redirect",
        "access-html",
        "relay-401",
        "no-profile-allowed",
        "timeout",
        "relay-error",
        "bad-url",
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    fake_relay: FakeRelay,
    break_relay: Callable[[FakeRelay], None],
    url: str,
    error: str,
) -> None:
    """Each failure shows its error, and the form recovers once it is fixed."""
    break_relay(fake_relay)
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_URL: url}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    fake_relay.health_ok = True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_unknown_error(
    hass: HomeAssistant, fake_relay: FakeRelay
) -> None:
    """An unexpected exception shows the unknown error."""
    result = await _start_user_flow(hass)

    with patch(
        "custom_components.hey_claude.config_flow.RelayClient.health",
        side_effect=RuntimeError("boom"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_duplicate_aborts(
    hass: HomeAssistant, fake_relay: FakeRelay, mock_config_entry: MockConfigEntry
) -> None:
    """The same relay cannot be added twice, and no turn is sent."""
    mock_config_entry.add_to_hass(hass)
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert fake_relay.turn_requests == []


async def test_reauth_flow(
    hass: HomeAssistant, fake_relay: FakeRelay, mock_config_entry: MockConfigEntry
) -> None:
    """Reauth replaces the token and keeps the URL."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CLIENT_ID: "new-id.access", CONF_CLIENT_SECRET: "NEW-SECRET-1"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {
        CONF_URL: TEST_URL,
        CONF_CLIENT_ID: "new-id.access",
        CONF_CLIENT_SECRET: "NEW-SECRET-1",
    }
    [headers] = fake_relay.turn_headers
    assert headers["CF-Access-Client-Secret"] == "NEW-SECRET-1"


async def test_reauth_flow_invalid_auth(
    hass: HomeAssistant, fake_relay: FakeRelay, mock_config_entry: MockConfigEntry
) -> None:
    """A refused token keeps the reauth form open."""
    mock_config_entry.add_to_hass(hass)
    fake_relay.queue_turn(Raw(403, "<html>"))
    result = await mock_config_entry.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CLIENT_ID: "new-id.access", CONF_CLIENT_SECRET: "WRONG"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data[CONF_CLIENT_SECRET] == TEST_SECRET


async def test_reconfigure_flow_changes_url(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reconfigure can move the entry to another relay."""
    other_relay = FakeRelay(aioclient_mock, OTHER_URL)
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_URL: OTHER_URL + "/",
            CONF_CLIENT_ID: "other-id.access",
            CONF_CLIENT_SECRET: "OTHER-SECRET",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.unique_id == OTHER_URL
    assert mock_config_entry.data == {
        CONF_URL: OTHER_URL,
        CONF_CLIENT_ID: "other-id.access",
        CONF_CLIENT_SECRET: "OTHER-SECRET",
    }
    assert len(other_relay.turn_requests) == 1


async def test_reconfigure_blank_secret_keeps_secret(
    hass: HomeAssistant, fake_relay: FakeRelay, mock_config_entry: MockConfigEntry
) -> None:
    """A blank secret keeps the stored one, which is used to validate."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: TEST_URL, CONF_CLIENT_ID: TEST_CLIENT_ID, CONF_CLIENT_SECRET: ""},
    )

    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_CLIENT_SECRET] == TEST_SECRET
    [headers] = fake_relay.turn_headers
    assert headers["CF-Access-Client-Secret"] == TEST_SECRET


async def test_reconfigure_errors(
    hass: HomeAssistant, fake_relay: FakeRelay, mock_config_entry: MockConfigEntry
) -> None:
    """A refused token keeps the reconfigure form open and the entry unchanged."""
    mock_config_entry.add_to_hass(hass)
    fake_relay.queue_turn(Error(401, "unauthorized"))
    result = await mock_config_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: TEST_URL, CONF_CLIENT_ID: "x", CONF_CLIENT_SECRET: "y"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data[CONF_CLIENT_ID] == TEST_CLIENT_ID


async def test_reconfigure_duplicate_url_aborts(
    hass: HomeAssistant, fake_relay: FakeRelay, mock_config_entry: MockConfigEntry
) -> None:
    """Reconfigure cannot point at a relay another entry already uses."""
    mock_config_entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=OTHER_URL,
        data={CONF_URL: OTHER_URL, CONF_CLIENT_ID: "a", CONF_CLIENT_SECRET: "b"},
    ).add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: OTHER_URL, CONF_CLIENT_ID: "a", CONF_CLIENT_SECRET: "b"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_URL] == TEST_URL
