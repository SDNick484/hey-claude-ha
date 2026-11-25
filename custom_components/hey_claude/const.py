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
