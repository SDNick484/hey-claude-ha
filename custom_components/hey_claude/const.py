"""Constants for the Hey Claude integration."""

from typing import Final

DOMAIN: Final = "hey_claude"

CONF_URL: Final = "url"
CONF_CLIENT_ID: Final = "client_id"
CONF_CLIENT_SECRET: Final = "client_secret"
CONF_DEFAULT_PROFILE: Final = "default_profile"
CONF_AREA_PROFILES: Final = "area_profiles"

CLIENT_NAME: Final = "home-assistant"

TURN_TIMEOUT: Final = 60.0
SHORT_TIMEOUT: Final = 10.0

SETUP_TEST_TEXT: Final = (
    "This is a connection test from Home Assistant. Reply with one word."
)

# What the speaker says when the relay gives no line of its own.
FALLBACK_LINES: Final[dict[str, str]] = {
    "unauthorized": "Claude isn't letting this speaker in right now.",
    "bad_request": "Claude couldn't make sense of that.",
    "upstream_timeout": "Claude ran out of time on that one.",
    "upstream_error": "Something went wrong on Claude's side.",
    "rate_limited": "Claude is busy right now. Try again in a minute.",
    "internal": "Something went wrong on Claude's side.",
    "timeout": "I couldn't get an answer from Claude in time.",
    "network": "I couldn't reach Claude.",
}
DEFAULT_FALLBACK: Final = "Sorry, something went wrong reaching Claude."
EMPTY_REPLY_LINE: Final = "Claude didn't have anything to say."
SECRET_REFUSED_LINE: Final = "That needs your passphrase, which I can't take here."

# How many Home Assistant conversations keep their relay conversation ID.
CONVERSATION_MAP_SIZE: Final = 100
