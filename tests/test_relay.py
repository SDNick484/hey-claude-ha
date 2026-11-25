"""Tests for the relay client."""

from __future__ import annotations

import uuid

import pytest
from aiohttp import ClientConnectionError, ClientSession, ServerDisconnectedError, web
from aiohttp.test_utils import TestServer
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.hey_claude.relay import (
    RelayAuthError,
    RelayClient,
    RelayConnectionError,
    RelayError,
    RelayTimeoutError,
    TurnReply,
    normalize_url,
)

from .conftest import TEST_CLIENT_ID, TEST_SECRET, TEST_URL
from .fake_relay import Error, FakeRelay, Raise, Raw, Reply

ERROR_CODES = [
    "unauthorized",
    "bad_request",
    "upstream_timeout",
    "upstream_error",
    "rate_limited",
    "internal",
]


@pytest.fixture
def client(hass: HomeAssistant, fake_relay: FakeRelay) -> RelayClient:
    """Return a client pointed at the fake relay."""
    return RelayClient(
        async_get_clientsession(hass), TEST_URL, TEST_CLIENT_ID, TEST_SECRET
    )


async def test_turn_success(client: RelayClient, fake_relay: FakeRelay) -> None:
    """A turn posts the documented body and headers and returns the reply."""
    fake_relay.queue_turn(
        Reply("Hello there.", conversation_id="c-9", tools_used=("matinee.search",))
    )

    result = await client.turn("hello")

    assert result == TurnReply(
        conversation_id="c-9",
        reply="Hello there.",
        expect_secret=False,
        tools_used=("matinee.search",),
    )
    [body] = fake_relay.turn_requests
    assert body["text"] == "hello"
    assert body["client"] == "home-assistant"
    assert str(uuid.UUID(body["turn_id"])) == body["turn_id"]
    assert "conversation_id" not in body
    assert "profile" not in body
    [headers] = fake_relay.turn_headers
    assert headers["CF-Access-Client-Id"] == TEST_CLIENT_ID
    assert headers["CF-Access-Client-Secret"] == TEST_SECRET


async def test_turn_sends_conversation_and_profile(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """The conversation ID and profile are sent when given."""
    await client.turn("hi", conversation_id="c-1", profile="office")

    [body] = fake_relay.turn_requests
    assert body["conversation_id"] == "c-1"
    assert body["profile"] == "office"


async def test_turn_ids_are_fresh(client: RelayClient, fake_relay: FakeRelay) -> None:
    """Each turn gets its own turn_id."""
    await client.turn("one")
    await client.turn("two")

    first, second = fake_relay.turn_requests
    assert first["turn_id"] != second["turn_id"]


@pytest.mark.parametrize(
    "exc", [ClientConnectionError(), ServerDisconnectedError()], ids=["conn", "disc"]
)
async def test_turn_retries_once_on_connection_error_same_turn_id(
    client: RelayClient, fake_relay: FakeRelay, exc: Exception
) -> None:
    """A network failure is retried once with the same turn_id."""
    fake_relay.queue_turn(Raise(exc), Reply("Back again."))

    result = await client.turn("hello")

    assert result.reply == "Back again."
    first, second = fake_relay.turn_requests
    assert first["turn_id"] == second["turn_id"]


async def test_turn_connection_error_twice_raises_network(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """Two network failures give up with a network error."""
    fake_relay.queue_turn(
        Raise(ClientConnectionError()), Raise(ClientConnectionError())
    )

    with pytest.raises(RelayConnectionError) as err:
        await client.turn("hello")

    assert err.value.code == "network"
    assert len(fake_relay.turn_requests) == 2


@pytest.mark.parametrize("status", [502, 503, 504, 530])
async def test_turn_gateway_html_retried_then_network_error(
    client: RelayClient, fake_relay: FakeRelay, status: int
) -> None:
    """A gateway page from the edge is retried once, then reported as network."""
    fake_relay.queue_turn(Raw(status, "<html>down</html>"), Raw(status, "<html>"))

    with pytest.raises(RelayConnectionError):
        await client.turn("hello")

    first, second = fake_relay.turn_requests
    assert first["turn_id"] == second["turn_id"]


async def test_turn_gateway_html_then_success(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """A gateway page followed by a reply returns the reply."""
    fake_relay.queue_turn(Raw(502, "<html>"), Reply("Fine now."))

    assert (await client.turn("hello")).reply == "Fine now."


async def test_turn_timeout(client: RelayClient, fake_relay: FakeRelay) -> None:
    """A timeout is not retried."""
    fake_relay.queue_turn(Raise(TimeoutError()))

    with pytest.raises(RelayTimeoutError) as err:
        await client.turn("hello")

    assert err.value.code == "timeout"
    assert len(fake_relay.turn_requests) == 1


@pytest.mark.parametrize("spoken", ["A line to say.", None], ids=["spoken", "silent"])
@pytest.mark.parametrize("code", ERROR_CODES)
async def test_turn_error_codes(
    client: RelayClient, fake_relay: FakeRelay, code: str, spoken: str | None
) -> None:
    """Relay errors carry their code, spoken line and status, without retry."""
    fake_relay.queue_turn(Error(500, code, spoken))

    with pytest.raises(RelayError) as err:
        await client.turn("hello")

    assert type(err.value) is RelayError
    assert err.value.code == code
    assert err.value.spoken == spoken
    assert err.value.status == 500
    assert len(fake_relay.turn_requests) == 1


async def test_turn_json_401_is_auth_error(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """A relay 401 means the credentials were refused."""
    fake_relay.queue_turn(Error(401, "unauthorized", "Who are you?"))

    with pytest.raises(RelayAuthError) as err:
        await client.turn("hello")

    assert err.value.spoken == "Who are you?"


async def test_turn_profile_forbidden_is_not_auth_error(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """A relay 403 is a refused profile, not refused credentials."""
    fake_relay.queue_turn(Error(403, "unauthorized", "That room isn't allowed."))

    with pytest.raises(RelayError) as err:
        await client.turn("hello", profile="garage")

    assert type(err.value) is RelayError
    assert err.value.status == 403
    assert err.value.spoken == "That room isn't allowed."


async def test_turn_access_redirect_is_auth_error(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """Access redirecting to its login page means the token was refused."""
    fake_relay.queue_turn(
        Raw(302, "", headers={"Location": "https://example.cloudflareaccess.com/x"})
    )

    with pytest.raises(RelayAuthError) as err:
        await client.turn("hello")

    assert err.value.code == "unauthorized"
    assert err.value.spoken is None
    assert len(fake_relay.turn_requests) == 1


@pytest.mark.parametrize("status", [401, 403])
async def test_turn_access_html_403_is_auth_error(
    client: RelayClient, fake_relay: FakeRelay, status: int
) -> None:
    """An HTML refusal from Access means the token was refused."""
    fake_relay.queue_turn(Raw(status, "<html>Forbidden</html>"))

    with pytest.raises(RelayAuthError):
        await client.turn("hello")


@pytest.mark.parametrize(
    "body",
    ["{}", "not json", '{"conversation_id": "c", "reply": 5}', "[]"],
    ids=["empty", "text", "wrong-type", "list"],
)
async def test_turn_malformed_200_raises(
    client: RelayClient, fake_relay: FakeRelay, body: str
) -> None:
    """A 200 that is not a turn response is an error, not a reply."""
    fake_relay.queue_turn(Raw(200, body, "application/json"))

    with pytest.raises(RelayError) as err:
        await client.turn("hello")

    assert err.value.code == "bad_response"


async def test_turn_unexpected_status_raises(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """A non-JSON response that is not a gateway or auth page is unexpected."""
    fake_relay.queue_turn(Raw(500, "<html>oops</html>"))

    with pytest.raises(RelayError) as err:
        await client.turn("hello")

    assert err.value.code == "unexpected_response"
    assert err.value.status == 500
    assert len(fake_relay.turn_requests) == 1


async def test_health_ok(client: RelayClient, fake_relay: FakeRelay) -> None:
    """Health passes when the relay answers, and carries the Access headers."""
    await client.health()

    [headers] = fake_relay.health_headers
    assert headers["CF-Access-Client-Id"] == TEST_CLIENT_ID


async def test_health_down_raises_connection_error(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """Health fails with a network error when the relay is unreachable."""
    fake_relay.health_ok = False

    with pytest.raises(RelayConnectionError):
        await client.health()


async def test_end_conversation_posts_end(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """Ending a conversation posts to its end URL."""
    await client.end_conversation("relay-conv-1")

    assert fake_relay.ended == ["relay-conv-1"]


async def test_end_conversation_failure_raises(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """A failed end is reported to the caller."""
    fake_relay.end_ok = False

    with pytest.raises(RelayError):
        await client.end_conversation("relay-conv-1")


def test_repr_hides_credentials(client: RelayClient) -> None:
    """The client's repr shows neither credential."""
    text = repr(client)
    assert TEST_SECRET not in text
    assert TEST_CLIENT_ID not in text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://relay.example.com/", "https://relay.example.com"),
        ("  https://relay.example.com  ", "https://relay.example.com"),
        ("https://relay.example.com/base//", "https://relay.example.com/base"),
        ("http://relay.local:8080", "http://relay.local:8080"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    """URLs lose surrounding space and trailing slashes."""
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "raw", ["ftp://relay.example.com", "relay.example.com", "https://", ""]
)
def test_normalize_url_rejects(raw: str) -> None:
    """Only http and https URLs with a host are accepted."""
    with pytest.raises(ValueError):
        normalize_url(raw)


async def test_turn_non_access_redirect_is_not_auth_error(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """A redirect that is not Access's login page is a redirect, not a bad token."""
    fake_relay.queue_turn(
        Raw(308, "", headers={"Location": "https://relay.example.com/v1/turn"})
    )

    with pytest.raises(RelayError) as err:
        await client.turn("hello")

    assert type(err.value) is RelayError
    assert err.value.code == "redirect"
    assert err.value.status == 308


async def test_turn_access_path_redirect_is_auth_error(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """A redirect to Access's login path on the same host is a refused token."""
    fake_relay.queue_turn(
        Raw(302, "", headers={"Location": "/cdn-cgi/access/login/relay.example.com"})
    )

    with pytest.raises(RelayAuthError):
        await client.turn("hello")


async def test_turn_undecodable_body_is_relay_error(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """A body that does not decode is a bad response, not a stray exception."""
    fake_relay.queue_turn(Raw(200, "é", "application/json; charset=ascii"))

    with pytest.raises(RelayError) as err:
        await client.turn("hello")

    assert err.value.code == "bad_response"


async def test_turn_missing_expect_secret_is_bad_response(
    client: RelayClient, fake_relay: FakeRelay
) -> None:
    """The safety flag must be present; a reply without it is not trusted."""
    fake_relay.queue_turn(
        Raw(200, '{"conversation_id": "c", "reply": "hi"}', "application/json")
    )

    with pytest.raises(RelayError) as err:
        await client.turn("hello")

    assert err.value.code == "bad_response"


async def test_redirects_are_not_followed(socket_enabled: None) -> None:
    """Against a real server, Access's login redirect is reported, not followed.

    If the client followed it, the login page's 200 HTML would come back as a
    bad response instead of a refused token.
    """

    async def turn(request: web.Request) -> web.Response:
        raise web.HTTPFound("/cdn-cgi/access/login/relay")

    async def login(request: web.Request) -> web.Response:
        return web.Response(text="<html>Sign in</html>", content_type="text/html")

    app = web.Application()
    app.router.add_post("/v1/turn", turn)
    app.router.add_route("*", "/cdn-cgi/access/login/relay", login)
    async with TestServer(app, host="127.0.0.1") as server, ClientSession() as session:
        client = RelayClient(
            session, str(server.make_url("")), TEST_CLIENT_ID, TEST_SECRET
        )
        with pytest.raises(RelayAuthError):
            await client.turn("hello")
