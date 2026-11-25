"""Client for the hey-claude-relay HTTP API.

This module knows the wire protocol only. It imports nothing from Home
Assistant, so the protocol can be tested and reasoned about on its own.

It never logs request or response bodies, headers, or the relay URL: turn
text, replies and the Access credentials stay out of the logs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

import aiohttp
from yarl import URL

from .const import CLIENT_NAME, SHORT_TIMEOUT, TURN_TIMEOUT

_LOGGER = logging.getLogger(__name__)

# Statuses the edge (Cloudflare) answers with when it cannot reach the relay.
GATEWAY_STATUSES: Final = frozenset({502, 503, 504, 530})


@dataclass(frozen=True, slots=True)
class TurnReply:
    """A successful turn."""

    conversation_id: str
    reply: str
    expect_secret: bool
    tools_used: tuple[str, ...]


class RelayError(Exception):
    """The relay, or the path to it, did not produce a reply."""

    def __init__(
        self, code: str, spoken: str | None = None, status: int | None = None
    ) -> None:
        """Store the error code, the relay's spoken line and the HTTP status."""
        super().__init__(code if status is None else f"{code} (HTTP {status})")
        self.code = code
        self.spoken = spoken
        self.status = status


class RelayAuthError(RelayError):
    """Cloudflare Access or the relay refused the credentials."""


class RelayConnectionError(RelayError):
    """The relay could not be reached."""

    def __init__(self, status: int | None = None) -> None:
        """Create a network error."""
        super().__init__("network", status=status)


class RelayTimeoutError(RelayError):
    """The relay did not answer in time."""

    def __init__(self) -> None:
        """Create a timeout error."""
        super().__init__("timeout")


class _GatewayError(Exception):
    """The edge answered for a relay it could not reach. Retryable."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def normalize_url(url: str) -> str:
    """Return the relay URL without surrounding space or trailing slashes.

    Raise ValueError unless it is an http or https URL with a host.
    """
    cleaned = url.strip().rstrip("/")
    try:
        parsed = URL(cleaned)
    except ValueError as err:
        raise ValueError("invalid URL") from err
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise ValueError("relay URL must be http or https with a host")
    return cleaned


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _error_from(data: Any) -> tuple[str, str | None] | None:
    """Return (code, spoken) from a relay error body, or None if it is not one."""
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if not isinstance(error, dict) or not isinstance(code := error.get("code"), str):
        return None
    spoken = error.get("spoken")
    return code, spoken if isinstance(spoken, str) and spoken.strip() else None


def _is_access_login(location: str | None) -> bool:
    """Return whether a redirect points at Cloudflare Access's login page."""
    if not location:
        return False
    try:
        target = URL(location)
    except ValueError:
        return False
    host = target.host or ""
    return host.endswith(".cloudflareaccess.com") or "/cdn-cgi/access/" in target.path


def _raise_for_failure(status: int, data: Any, location: str | None) -> None:
    """Raise the error a non-success response stands for."""
    if 300 <= status < 400:
        # Access redirects to its login page when it refuses a token. Any
        # other redirect (http to https, a moved relay) is not about the token.
        if _is_access_login(location):
            raise RelayAuthError("unauthorized", status=status)
        raise RelayError("redirect", status=status)
    if (error := _error_from(data)) is not None:
        code, spoken = error
        if status == 401:
            raise RelayAuthError(code, spoken, status)
        raise RelayError(code, spoken, status)
    if status in (401, 403):
        raise RelayAuthError("unauthorized", status=status)
    if status in GATEWAY_STATUSES:
        raise _GatewayError(status)
    raise RelayError("unexpected_response", status=status)


def _parse_reply(data: Any) -> TurnReply:
    if not isinstance(data, dict):
        raise RelayError("bad_response", status=200)
    conversation_id = data.get("conversation_id")
    reply = data.get("reply")
    expect_secret = data.get("expect_secret")
    tools_used = data.get("tools_used", [])
    if (
        not isinstance(conversation_id, str)
        or not conversation_id
        or not isinstance(reply, str)
        or not isinstance(expect_secret, bool)
        or not isinstance(tools_used, list)
        or not all(isinstance(tool, str) for tool in tools_used)
    ):
        raise RelayError("bad_response", status=200)
    return TurnReply(conversation_id, reply, expect_secret, tuple(tools_used))


class RelayClient:
    """Talk to one relay with one Cloudflare Access service token."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Create a client. The URL should already be normalized."""
        self._session = session
        self._url = url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret

    def __repr__(self) -> str:
        """Return a representation without the URL or credentials."""
        return f"{type(self).__name__}()"

    def _headers(self) -> dict[str, str]:
        return {
            "CF-Access-Client-Id": self._client_id,
            "CF-Access-Client-Secret": self._client_secret,
        }

    async def _send(
        self,
        method: str,
        path: str,
        name: str,
        budget: float,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, Any, str | None]:
        """Send one request and return (status, parsed JSON or None, Location)."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            async with asyncio.timeout(budget):
                async with self._session.request(
                    method,
                    f"{self._url}{path}",
                    json=body,
                    headers=self._headers(),
                    allow_redirects=False,
                ) as response:
                    status = response.status
                    location = response.headers.get("Location")
                    text = await response.text(errors="replace")
        except TimeoutError as err:
            _LOGGER.debug("Relay %s timed out after %.1fs", name, budget)
            raise RelayTimeoutError from err
        except aiohttp.ClientError as err:
            _LOGGER.debug("Relay %s failed: %s", name, type(err).__name__)
            raise RelayConnectionError from err
        _LOGGER.debug(
            "Relay %s answered %s in %.1fs", name, status, loop.time() - started
        )
        return status, _loads(text), location

    async def health(self) -> None:
        """Check that the relay answers its health endpoint."""
        status, data, location = await self._send(
            "GET", "/healthz", "health", SHORT_TIMEOUT
        )
        if status == 200:
            return
        try:
            _raise_for_failure(status, data, location)
        except _GatewayError as err:
            raise RelayConnectionError(err.status) from err

    async def turn(
        self,
        text: str,
        *,
        conversation_id: str | None = None,
        profile: str | None = None,
    ) -> TurnReply:
        """Send one turn and return the relay's reply.

        A network failure is retried once with the same turn_id, which the
        relay uses to avoid running the turn twice. The whole call, retry
        included, gets TURN_TIMEOUT seconds.
        """
        body: dict[str, Any] = {
            "turn_id": str(uuid.uuid4()),
            "text": text,
            "client": CLIENT_NAME,
        }
        if conversation_id is not None:
            body["conversation_id"] = conversation_id
        if profile is not None:
            body["profile"] = profile

        loop = asyncio.get_running_loop()
        deadline = loop.time() + TURN_TIMEOUT
        for attempt in (1, 2):
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise RelayTimeoutError
            try:
                status, data, location = await self._send(
                    "POST", "/v1/turn", "turn", remaining, body
                )
                if status == 200:
                    return _parse_reply(data)
                _raise_for_failure(status, data, location)
            except RelayConnectionError:
                if attempt == 2:
                    raise
            except _GatewayError as err:
                if attempt == 2:
                    raise RelayConnectionError(err.status) from err
            _LOGGER.debug("Retrying the turn once with the same turn_id")
        raise AssertionError("unreachable")  # pragma: no cover

    async def end_conversation(self, conversation_id: str) -> None:
        """Ask the relay to forget a conversation."""
        status, data, location = await self._send(
            "POST",
            f"/v1/conversations/{quote(conversation_id, safe='')}/end",
            "end",
            SHORT_TIMEOUT,
        )
        if 200 <= status < 300:
            return
        try:
            _raise_for_failure(status, data, location)
        except _GatewayError as err:
            raise RelayConnectionError(err.status) from err
