"""Tests for the conversation agent."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from aiohttp import ClientConnectionError
from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.intent import IntentResponseType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hey_claude.const import (
    CONF_AREA_PROFILES,
    CONF_DEFAULT_PROFILE,
    DEFAULT_FALLBACK,
    DOMAIN,
    EMPTY_REPLY_LINE,
    FALLBACK_LINES,
    SECRET_REFUSED_LINE,
)

from .conftest import SATELLITE
from .fake_relay import Error, FakeRelay, Outcome, Raise, Raw, Reply

AGENT_ID = "conversation.claude"
ACCESS_LOGIN = "https://example.cloudflareaccess.com/cdn-cgi/access/login/relay"
ERROR_CODES = [
    "unauthorized",
    "bad_request",
    "upstream_timeout",
    "upstream_error",
    "rate_limited",
    "internal",
]


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_relay: FakeRelay
) -> MockConfigEntry:
    """Set up the integration against the fake relay."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


async def _say(
    hass: HomeAssistant,
    text: str = "hello",
    conversation_id: str | None = None,
    *,
    device_id: str | None = None,
    satellite_id: str | None = None,
) -> conversation.ConversationResult:
    return await conversation.async_converse(
        hass,
        text,
        conversation_id,
        Context(),
        agent_id=AGENT_ID,
        device_id=device_id,
        satellite_id=satellite_id,
    )


def _speech(result: conversation.ConversationResult) -> str:
    speech: str = result.response.speech["plain"]["speech"]
    return speech


def _reauth_flows(hass: HomeAssistant) -> list[object]:
    return [
        flow
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"]["source"] == "reauth"
    ]


async def test_agent_is_registered(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """One conversation entity named after the device appears."""
    state = hass.states.get(AGENT_ID)
    assert state is not None


async def test_turn_speaks_reply(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """The relay's reply is spoken, and the turn is labelled as Home Assistant's."""
    fake_relay.queue_turn(Reply("It is sunny."))

    result = await _say(hass, "what's the weather")

    assert _speech(result) == "It is sunny."
    assert result.response.response_type is IntentResponseType.ACTION_DONE
    [body] = fake_relay.turn_requests
    assert body["text"] == "what's the weather"
    assert body["client"] == "home-assistant"


async def test_profile_from_area(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    fake_relay: FakeRelay,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
    satellite: tuple[str, str],
) -> None:
    """A satellite in an area with a profile sends that profile."""
    device_id, entity_id = satellite
    office = area_registry.async_create("Office")
    device_registry.async_update_device(device_id, area_id=office.id)
    hass.config_entries.async_update_entry(
        setup_entry,
        options={CONF_DEFAULT_PROFILE: "home", CONF_AREA_PROFILES: {office.id: "work"}},
    )

    await _say(hass, device_id=device_id, satellite_id=entity_id)

    assert fake_relay.turn_requests[0]["profile"] == "work"


async def test_profile_default(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    fake_relay: FakeRelay,
    satellite: tuple[str, str],
) -> None:
    """A satellite without an area profile sends the default."""
    device_id, entity_id = satellite
    hass.config_entries.async_update_entry(
        setup_entry, options={CONF_DEFAULT_PROFILE: "home", CONF_AREA_PROFILES: {}}
    )

    await _say(hass, device_id=device_id, satellite_id=entity_id)

    assert fake_relay.turn_requests[0]["profile"] == "home"


async def test_profile_omitted(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """With no profiles set, the relay chooses."""
    await _say(hass, satellite_id=SATELLITE)

    assert "profile" not in fake_relay.turn_requests[0]


async def test_conversation_id_mapping(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """A Home Assistant conversation keeps its relay conversation."""
    first = await _say(hass, "one")
    await _say(hass, "two", first.conversation_id)
    await _say(hass, "three")

    bodies = fake_relay.turn_requests
    assert first.conversation_id is not None
    assert "conversation_id" not in bodies[0]
    assert bodies[1]["conversation_id"] == "relay-conv-1"
    assert "conversation_id" not in bodies[2]


async def test_relay_rotates_conversation_id(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """When the relay starts a new conversation, the next turn uses its new ID."""
    fake_relay.queue_turn(
        Reply("a", conversation_id="c1"),
        Reply("b", conversation_id="c2"),
        Reply("c", conversation_id="c2"),
    )

    first = await _say(hass, "one")
    await _say(hass, "two", first.conversation_id)
    await _say(hass, "three", first.conversation_id)

    bodies = fake_relay.turn_requests
    assert bodies[1]["conversation_id"] == "c1"
    assert bodies[2]["conversation_id"] == "c2"


async def test_retry_same_turn_id(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """A network failure is retried once, and the reply is spoken."""
    fake_relay.queue_turn(Raise(ClientConnectionError()), Reply("Got it."))

    result = await _say(hass)

    assert _speech(result) == "Got it."
    first, second = fake_relay.turn_requests
    assert first["turn_id"] == second["turn_id"]


async def test_timeout_speaks_fallback(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """A timeout is spoken as such."""
    fake_relay.queue_turn(Raise(TimeoutError()))

    result = await _say(hass)

    assert _speech(result) == FALLBACK_LINES["timeout"]
    assert result.response.response_type is IntentResponseType.ERROR


async def test_network_failure_speaks_fallback(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """An unreachable relay is spoken as such."""
    fake_relay.queue_turn(Raw(530, "<html>"), Raw(530, "<html>"))

    result = await _say(hass)

    assert _speech(result) == "I couldn't reach Claude."


@pytest.mark.parametrize(
    "spoken", ["The relay's own words.", None], ids=["spoken", "silent"]
)
@pytest.mark.parametrize("code", ERROR_CODES)
async def test_error_codes_spoken(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    fake_relay: FakeRelay,
    code: str,
    spoken: str | None,
) -> None:
    """The relay's spoken line is used, else this integration's line for the code."""
    fake_relay.queue_turn(Error(500, code, spoken))

    result = await _say(hass)

    assert _speech(result) == (spoken or FALLBACK_LINES[code])
    assert result.response.response_type is IntentResponseType.ERROR
    assert result.continue_conversation is False


async def test_unknown_error_code_speaks_default(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """A code this integration does not know gets the default line."""
    fake_relay.queue_turn(Error(500, "brand_new_code"))

    assert _speech(await _say(hass)) == DEFAULT_FALLBACK


async def test_profile_forbidden_403_speaks_and_no_reauth(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """A refused profile is spoken, and does not ask for a new token."""
    fake_relay.queue_turn(Error(403, "unauthorized", "That room isn't allowed."))

    result = await _say(hass)
    await hass.async_block_till_done()

    assert _speech(result) == "That room isn't allowed."
    assert _reauth_flows(hass) == []


@pytest.mark.parametrize(
    "outcome",
    [
        Raw(302, "", headers={"Location": ACCESS_LOGIN}),
        Raw(403, "<html>Forbidden</html>"),
        Error(401, "unauthorized"),
    ],
    ids=["access-redirect", "access-html", "relay-401"],
)
async def test_auth_failure_starts_reauth(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    fake_relay: FakeRelay,
    outcome: Outcome,
) -> None:
    """A refused token is spoken and starts reauth."""
    fake_relay.queue_turn(outcome)

    result = await _say(hass)
    await hass.async_block_till_done()

    assert _speech(result) == FALLBACK_LINES["unauthorized"]
    assert len(_reauth_flows(hass)) == 1


@pytest.mark.parametrize("reply", ["", "   "], ids=["empty", "blank"])
async def test_empty_reply_speaks_fallback(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay, reply: str
) -> None:
    """An empty reply is never silence."""
    fake_relay.queue_turn(Reply(reply))

    assert _speech(await _say(hass)) == EMPTY_REPLY_LINE


async def test_reply_is_trimmed(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """Surrounding whitespace is not spoken."""
    fake_relay.queue_turn(Reply("  Done.\n"))

    assert _speech(await _say(hass)) == "Done."


async def test_question_continues_conversation(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """A reply that asks something keeps the microphone open."""
    fake_relay.queue_turn(Reply("Which room?"))

    assert (await _say(hass)).continue_conversation is True


async def test_statement_does_not_continue(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """A plain answer ends the exchange."""
    fake_relay.queue_turn(Reply("The lights are on."))

    assert (await _say(hass)).continue_conversation is False


async def test_expect_secret_refused(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """A passphrase request is refused, ended at the relay, and forgotten."""
    fake_relay.queue_turn(Reply("What's the passphrase?", expect_secret=True))

    first = await _say(hass, "unlock the front door")
    await _say(hass, "something else", first.conversation_id)

    assert _speech(first) == SECRET_REFUSED_LINE
    assert first.continue_conversation is False
    assert fake_relay.ended == ["relay-conv-1"]
    assert "conversation_id" not in fake_relay.turn_requests[1]


async def test_expect_secret_end_failure_still_refuses(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_relay: FakeRelay
) -> None:
    """If ending fails, the request is still refused and forgotten."""
    fake_relay.end_ok = False
    fake_relay.queue_turn(Reply("What's the passphrase?", expect_secret=True))

    first = await _say(hass)
    await _say(hass, "next", first.conversation_id)

    assert _speech(first) == SECRET_REFUSED_LINE
    assert first.continue_conversation is False
    assert "conversation_id" not in fake_relay.turn_requests[1]


@pytest.mark.parametrize(
    "outcomes",
    [
        [Reply("")],
        [Error(500, "internal")],
        [Error(429, "rate_limited", "")],
        [Raw(502, "<html>"), Raw(502, "<html>")],
        [Raw(500, "<html>oops</html>")],
        [Raw(301, "", headers={"Location": "https://relay.example.com/x"})],
        [Raw(200, "{}", "application/json")],
        [Raise(ClientConnectionError()), Raise(ClientConnectionError())],
        [Raise(TimeoutError())],
    ],
    ids=[
        "empty-reply",
        "relay-error",
        "blank-spoken",
        "gateway",
        "html-500",
        "redirect",
        "malformed",
        "network",
        "timeout",
    ],
)
async def test_never_silent(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    fake_relay: FakeRelay,
    outcomes: list[Outcome],
) -> None:
    """Every outcome speaks something."""
    fake_relay.queue_turn(*outcomes)

    speech = _speech(await _say(hass))

    assert speech.strip()


async def test_unexpected_exception_speaks_default(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Even a bug in the client speaks rather than failing the pipeline."""
    with patch(
        "custom_components.hey_claude.relay.RelayClient.turn",
        side_effect=RuntimeError("bug"),
    ):
        result = await _say(hass)

    assert _speech(result) == DEFAULT_FALLBACK
    assert result.response.response_type is IntentResponseType.ERROR
