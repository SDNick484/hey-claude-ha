"""The Hey Claude conversation agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from homeassistant.components import conversation
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeyClaudeConfigEntry
from .const import (
    DEFAULT_FALLBACK,
    DOMAIN,
    EMPTY_REPLY_LINE,
    FALLBACK_LINES,
    SECRET_REFUSED_LINE,
)
from .profile import area_for_turn, resolve_profile
from .relay import RelayAuthError, RelayError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeyClaudeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the conversation agent for this relay."""
    async_add_entities([HeyClaudeConversationEntity(entry)])


class HeyClaudeConversationEntity(conversation.ConversationEntity):
    """Send each turn to the relay and speak its reply.

    Never logs what was said or replied, and never returns silence.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = conversation.ConversationEntityFeature(0)

    def __init__(self, entry: HeyClaudeConfigEntry) -> None:
        """Create the agent for a config entry."""
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Claude",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def supported_languages(self) -> Literal["*"]:
        """Claude answers in any language."""
        return "*"

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Send the turn to the relay and return what to speak."""
        data = self._entry.runtime_data
        ha_id = chat_log.conversation_id
        profile = resolve_profile(
            self._entry.options,
            area_for_turn(self.hass, user_input.device_id, user_input.satellite_id),
        )
        response = intent.IntentResponse(language=user_input.language)
        can_continue = False

        try:
            reply = await data.client.turn(
                user_input.text,
                conversation_id=data.relay_conversations.get(ha_id),
                profile=profile,
            )
        except RelayError as err:
            # No traceback: aiohttp errors chained here can carry the host.
            _LOGGER.debug("Turn failed: %s (profile %s)", err.code, profile)
            if isinstance(err, RelayAuthError):
                self._entry.async_start_reauth(self.hass)
            speech = err.spoken or FALLBACK_LINES.get(err.code, DEFAULT_FALLBACK)
            response.async_set_error(intent.IntentResponseErrorCode.UNKNOWN, speech)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.error("Unexpected error in a turn: %s", type(err).__name__)
            speech = DEFAULT_FALLBACK
            response.async_set_error(intent.IntentResponseErrorCode.UNKNOWN, speech)
        else:
            _LOGGER.debug(
                "Turn answered (profile %s, tools %s)", profile, reply.tools_used
            )
            if reply.expect_secret:
                # Passphrases never go through Home Assistant: end the relay
                # conversation so the next sentence is not taken as an attempt.
                data.relay_conversations.pop(ha_id, None)
                try:
                    await data.client.end_conversation(reply.conversation_id)
                except RelayError as err:
                    _LOGGER.debug("Could not end the conversation: %s", err.code)
                speech = SECRET_REFUSED_LINE
            else:
                data.relay_conversations[ha_id] = reply.conversation_id
                speech = reply.reply.strip() or EMPTY_REPLY_LINE
                can_continue = True
            response.async_set_speech(speech)

        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=speech)
        )
        return conversation.ConversationResult(
            response=response,
            conversation_id=ha_id,
            continue_conversation=can_continue and chat_log.continue_conversation,
        )
