"""A fake hey-claude-relay built on the harness's aiohttp mocker."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from aiohttp import ClientConnectionError
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL


@dataclass(frozen=True)
class Reply:
    """A 200 turn response."""

    reply: str
    conversation_id: str = "relay-conv-1"
    expect_secret: bool = False
    tools_used: tuple[str, ...] = ()


@dataclass(frozen=True)
class Error:
    """A relay JSON error response."""

    status: int
    code: str
    spoken: str | None = None


@dataclass(frozen=True)
class Raw:
    """Any other response, such as an HTML page from Cloudflare."""

    status: int
    body: str
    content_type: str = "text/html"
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Raise:
    """The request fails with an exception instead of a response."""

    exc: BaseException


type Outcome = Reply | Error | Raw | Raise

END_PATTERN = re.compile(r"/v1/conversations/([^/]+)/end$")


class FakeRelay:
    """Answer relay requests from a queue of scripted outcomes."""

    def __init__(self, mock: AiohttpClientMocker, url: str) -> None:
        """Register the relay's endpoints on the mocker."""
        self._mock = mock
        self._url = url
        self._turns: deque[Outcome] = deque()
        self.health_ok = True
        self.end_ok = True
        self.ended: list[str] = []
        mock.get(f"{url}/healthz", side_effect=self._health)
        mock.post(f"{url}/v1/turn", side_effect=self._turn)
        mock.post(
            re.compile(re.escape(url) + END_PATTERN.pattern),
            side_effect=self._end,
        )

    def queue_turn(self, *outcomes: Outcome) -> None:
        """Answer the next turn requests with these outcomes, in order."""
        self._turns.extend(outcomes)

    def _calls(self, path: str) -> list[tuple[Any, ...]]:
        return [call for call in self._mock.mock_calls if URL(call[1]).path == path]

    @property
    def turn_requests(self) -> list[dict[str, Any]]:
        """JSON bodies of every turn request, in order."""
        return [call[2] for call in self._calls("/v1/turn")]

    @property
    def turn_headers(self) -> list[dict[str, str]]:
        """Headers of every turn request, in order."""
        return [call[3] for call in self._calls("/v1/turn")]

    @property
    def health_headers(self) -> list[dict[str, str]]:
        """Headers of every health request, in order."""
        return [call[3] for call in self._calls("/healthz")]

    async def _health(
        self, method: str, url: URL, data: Any
    ) -> AiohttpClientMockResponse:
        if not self.health_ok:
            raise ClientConnectionError("relay down")
        return AiohttpClientMockResponse(method, url, text="ok")

    async def _turn(
        self, method: str, url: URL, data: Any
    ) -> AiohttpClientMockResponse:
        outcome = self._turns.popleft() if self._turns else Reply("ok")
        match outcome:
            case Reply():
                return AiohttpClientMockResponse(
                    method,
                    url,
                    json={
                        "conversation_id": outcome.conversation_id,
                        "reply": outcome.reply,
                        "expect_secret": outcome.expect_secret,
                        "tools_used": list(outcome.tools_used),
                    },
                    headers={"content-type": "application/json"},
                )
            case Error():
                error: dict[str, str] = {"code": outcome.code}
                if outcome.spoken is not None:
                    error["spoken"] = outcome.spoken
                return AiohttpClientMockResponse(
                    method,
                    url,
                    status=outcome.status,
                    json={"error": error},
                    headers={"content-type": "application/json"},
                )
            case Raw():
                return AiohttpClientMockResponse(
                    method,
                    url,
                    status=outcome.status,
                    text=outcome.body,
                    headers={"content-type": outcome.content_type, **outcome.headers},
                )
            case Raise():
                raise outcome.exc

    async def _end(self, method: str, url: URL, data: Any) -> AiohttpClientMockResponse:
        match = END_PATTERN.search(URL(url).path)
        assert match is not None
        if not self.end_ok:
            return AiohttpClientMockResponse(
                method,
                url,
                status=500,
                json={"error": {"code": "internal"}},
                headers={"content-type": "application/json"},
            )
        self.ended.append(match.group(1))
        return AiohttpClientMockResponse(method, url, status=204)
