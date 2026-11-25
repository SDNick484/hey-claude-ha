# hey-claude-ha design

A Home Assistant custom integration (domain `hey_claude`) that makes a
`hey-claude-relay` instance a conversation agent. A voice satellite hears
the driver, Home Assistant turns speech into text, this integration posts
the text to the relay, and Home Assistant speaks the reply.

## Relay API (shared with the relay repo; do not change unilaterally)

Every request carries `CF-Access-Client-Id` and `CF-Access-Client-Secret`.

- `POST /v1/turn` with `{turn_id, text, conversation_id?, client:
  "home-assistant", profile?}` returns `200 {conversation_id, reply,
  expect_secret, tools_used}`.
  - A repeated `turn_id` returns the stored response (10 minutes).
  - `expect_secret: true` means the reply asked for the passphrase.
  - `profile` omitted means the caller's first allowed profile. A profile the
    token is not allowed gets `403` with code `unauthorized`. A conversation
    keeps the profile it started with.
  - An unknown or expired `conversation_id` starts a new conversation and
    returns the new id. It is not an error.
- Errors: 4xx/5xx with `{"error": {"code", "spoken"?}}`. Codes:
  `unauthorized`, `bad_request`, `upstream_timeout`, `upstream_error`,
  `rate_limited`, `internal`. The client reads `spoken` aloud when present,
  and its own fallback line otherwise.
- `POST /v1/conversations/{id}/end` forgets a conversation (`204`).
- `GET /healthz` answers before auth.
- Single JSON body, no streaming. Clients allow 60 seconds.

## Milestone 0 findings (Home Assistant 2026.11.3 source)

**Passphrases do not go through Home Assistant.** The text of an utterance
is kept or shown, outside this integration's control, in: the STT server's
log (wyoming-faster-whisper logs every transcript at INFO), pipeline debug
(last 10 runs per pipeline), the satellite itself (the `stt-end` event), the
chat log (in memory, 5-minute idle timeout, admin websocket subscribers),
conversation traces (last 3), and any debug logging. Some satellites also
publish the words to sensors and events that the recorder keeps on disk.
So the integration tells the relay nothing special, and each room's relay
profile refuses gated actions.

**If the relay still replies `expect_secret: true`** (a misconfigured
profile), the integration does not continue the conversation. It ends the
relay conversation with `POST /v1/conversations/{id}/end`, forgets the
mapping, and speaks a fixed refusal line. Ending it matters: otherwise the
driver's next ordinary sentence on that conversation would reach the relay
as a passphrase attempt.

**Continued conversation.** The entity returns
`ConversationResult(continue_conversation=True)` when its spoken reply ends
in a question mark (Home Assistant's own `ChatLog.continue_conversation`
rule). The pipeline forwards the flag to the satellite. ESPHome-protocol
satellites that honour it (ESPHome `voice_assistant`, so the Voice Preview
Edition, and others) reopen the microphone without a wake word, and the
pipeline sends the follow-up straight to this agent, skipping local
intents. Wyoming and VoIP satellites do not honour the flag in 2026.11.

**Minimum Home Assistant: 2026.10.0.** The newest
`pytest-homeassistant-custom-component` (0.13.375) pins 2026.10.4, and every
API this integration uses is identical in 2026.10.4 and 2026.11.3.

## Behaviour

- **Setup flow** (UI only): relay URL, Access client ID, Access client
  secret. Validate with `GET /healthz`, then one real test turn (no
  profile), then end that test conversation. Secret stored in config entry
  data, never logged.
- **Reauth** (client ID and secret) and **reconfigure** (all three; a blank
  secret keeps the stored one).
- **Options flow:** a default profile, and a profile per Home Assistant
  area. Free text.
- **A turn:** find the area (satellite entity's area, else its device's
  area, else the input device's area), pick that area's profile or the
  default (or omit), post to `/v1/turn` with a fresh UUID `turn_id` and
  `client = "home-assistant"`. Map Home Assistant conversation ID to relay
  conversation ID. 60-second budget. On a network failure, retry once with
  the same `turn_id`.
- **Errors:** speak `spoken`, else a fallback line per code. Never silence.
  A rejected credential also starts a reauth flow.
- **Local commands:** not reimplemented; "prefer handling commands locally"
  stays on in the pipeline.
- Diagnostics with URL, client ID and secret redacted. Unload supported.
- The integration never logs turn text, replies, or credentials.
