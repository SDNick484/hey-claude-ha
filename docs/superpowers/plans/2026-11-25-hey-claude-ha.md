# hey-claude-ha Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A HACS-installable Home Assistant custom integration, `hey_claude`, that makes a hey-claude-relay a conversation agent for voice satellites.

**Architecture:** A pure aiohttp `RelayClient` (no Home Assistant imports) owns the wire protocol, retry and error mapping. A config flow and options flow store credentials and area→profile choices. One `ConversationEntity` per config entry resolves the area's profile, calls the client, maps conversation IDs, and always returns spoken text.

**Tech Stack:** Python 3.14, Home Assistant ≥ 2026.10.0, aiohttp (from Home Assistant), `pytest-homeassistant-custom-component==0.13.375` (pins HA 2026.10.4), uv, ruff, mypy, GitHub Actions (hassfest, HACS action).

**Spec:** `docs/superpowers/specs/2026-11-25-hey-claude-ha-design.md`

## Global Constraints

- Domain `hey_claude`; package `custom_components/hey_claude/`; UI setup only (`config_flow: true`, no YAML schema).
- `hacs.json` `"homeassistant": "2026.10.0"`; manifest `"version": "0.1.0"`, `"integration_type": "service"`, `"iot_class": "cloud_polling"`, `"dependencies": ["conversation"]`, `"requirements": []`.
- Relay API exactly as in the spec. `client` is always `"home-assistant"`. `turn_id` is `str(uuid.uuid4())`.
- Turn budget 60 s total across both attempts; `/healthz` and `/end` 10 s each.
- Never log, and never put in diagnostics: the Access client secret, the Access client ID, the relay URL, turn text, or reply text.
- Never follow redirects (`allow_redirects=False`).
- Public repo: no hostnames, tokens, or household details in code, tests, docs, or commit messages. Tests use `https://relay.example.com`.
- Commits authored as `Nick Andrade <SDNick484@users.noreply.github.com>` (`git config user.email SDNick484@users.noreply.github.com` in this repo).
- Editor instructions in the README use vim.
- One PR per milestone; CI green before the next milestone starts; voice checklist results from Nick before merging.

## Review Focus

1. Cloudflare Access refuses the token with a 302 to its login page, or with an HTML 403 → treated as a credential failure (reauth plus a spoken line), never parsed as a reply. Test: `test_turn_access_redirect_is_auth_error`, `test_turn_access_html_403_is_auth_error` (Task 2).
2. The relay returns `"reply": ""` or whitespace → a spoken fallback, never silence. Test: `test_empty_reply_speaks_fallback` (Task 5).
3. The relay hands back a new `conversation_id` because the old one expired → the map is updated and the next turn sends the new ID. Test: `test_relay_rotates_conversation_id` (Task 5).
4. An area is deleted or renamed after options are saved → a rename keeps its profile (stored by area ID), and a deleted area's entry is ignored and dropped on the next save. Tests: `test_profile_survives_area_rename`, `test_options_drop_deleted_areas` (Task 4).
5. The Cloudflare tunnel is down, so the edge returns a non-JSON 502/530 → retried once with the same `turn_id`, then "I couldn't reach Claude." Test: `test_turn_gateway_html_retried_then_network_error` (Task 2).

---

## Milestone 1 — installable and configurable (PR 1)

### Task 0: Initial commit on main

**Files:**
- Create: `.gitignore` (Python, `.venv/`, `.coverage`, `.mypy_cache/`, `.ruff_cache/`), `README.md` (title and one-line description only)
- Add: `docs/superpowers/specs/2026-11-25-hey-claude-ha-design.md`, this plan

- [ ] **Step 1:** `git config user.email SDNick484@users.noreply.github.com`, commit the files on `main` ("Start the repo with the design and plan"), push `main`.
- [ ] **Step 2:** `git switch -c m1-foundation`.

### Task 1: Scaffold, tooling and CI

**Files:**
- Create: `custom_components/hey_claude/__init__.py`, `const.py`, `manifest.json`, `translations/en.json`, `brand/icon.png` (256×256, generic speech-bubble glyph drawn with Pillow; no Anthropic marks)
- Create: `hacs.json`, `pyproject.toml`, `uv.lock`, `.github/workflows/validate.yml`, `.github/workflows/tests.yml`
- Test: `tests/__init__.py`, `tests/conftest.py`, `tests/test_init.py`

**Interfaces:**
- Produces (`const.py`): `DOMAIN = "hey_claude"`, `CONF_URL = "url"`, `CONF_CLIENT_ID = "client_id"`, `CONF_CLIENT_SECRET = "client_secret"`, `CONF_DEFAULT_PROFILE = "default_profile"`, `CONF_AREA_PROFILES = "area_profiles"`, `CLIENT_NAME = "home-assistant"`, `TURN_TIMEOUT = 60.0`, `SHORT_TIMEOUT = 10.0`.
- Produces (`__init__.py`): `type HeyClaudeConfigEntry = ConfigEntry[HeyClaudeData]`; `@dataclass class HeyClaudeData: client: RelayClient` (Task 2 defines `RelayClient`; in this task `PLATFORMS: list[Platform] = []`).
- Produces (`tests/conftest.py`): autouse `auto_enable_custom_integrations`; fixture `mock_config_entry() -> MockConfigEntry` with data `{url: "https://relay.example.com", client_id: "test-client-id.access", client_secret: "TEST-SECRET-6f1c"}` and `unique_id="https://relay.example.com"`; constants `TEST_URL`, `TEST_CLIENT_ID`, `TEST_SECRET`.

- [ ] **Step 1:** `pyproject.toml`: `requires-python = ">=3.14"`; dev group `pytest-homeassistant-custom-component==0.13.375`, `ruff`, `mypy`; `[tool.pytest.ini_options] asyncio_mode = "auto"`, `testpaths = ["tests"]`; ruff `select = ["E","F","I","UP","B","SIM","RUF","ASYNC"]`; mypy `strict = true` over `custom_components`. Run `uv sync`. Expected: resolves with `homeassistant==2026.10.4`.
- [ ] **Step 2: Write the failing test** `tests/test_init.py::test_setup_and_unload`: add `mock_config_entry`, `await hass.config_entries.async_setup(entry_id)`, assert `entry.state is ConfigEntryState.LOADED`; unload; assert `NOT_LOADED`. Run `uv run pytest tests/test_init.py -v`. Expected: FAIL (integration not found).
- [ ] **Step 3:** Write `manifest.json` (Global Constraints values, `codeowners: ["@SDNick484"]`, `documentation` and `issue_tracker` pointing at the GitHub repo, `config_flow: true`), `hacs.json` (`name: "Hey Claude"`, `render_readme: true`, `homeassistant: "2026.10.0"`), `const.py`, `__init__.py` with `async_setup_entry` (store `HeyClaudeData`, forward `PLATFORMS`) and `async_unload_entry`. No network I/O in setup: failures surface per turn as spoken lines. A minimal `config_flow.py` stub may be needed for hassfest; Task 3 replaces it.
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** `validate.yml` on push and pull_request: job `hassfest` (`home-assistant/actions/hassfest@master`), job `hacs` (`hacs/action@main`, `category: integration`). `tests.yml`: `astral-sh/setup-uv`, Python 3.14, `uv sync --locked`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy custom_components`, `uv run pytest --cov=custom_components.hey_claude --cov-report=term-missing`.
- [ ] **Step 6:** Set the GitHub description and topics HACS requires: `gh repo edit SDNick484/hey-claude-ha --description "Home Assistant conversation agent for a hey-claude-relay" --add-topic home-assistant --add-topic hacs --add-topic hacs-integration --add-topic voice-assistant`.
- [ ] **Step 7:** Commit ("Scaffold the integration, tooling and CI"). Push and open the draft PR so CI runs. If the HACS brands check fails even with the local `brand/` folder, add `ignore: brands` to the action and say so in the PR body.

### Task 2: Relay client

**Files:**
- Create: `custom_components/hey_claude/relay.py`
- Test: `tests/fake_relay.py`, `tests/test_relay.py`

**Interfaces:**
- Produces (`relay.py`, imports only aiohttp and stdlib):
  - `@dataclass(frozen=True, slots=True) class TurnReply: conversation_id: str; reply: str; expect_secret: bool; tools_used: tuple[str, ...]`
  - `class RelayError(Exception)` with attributes `code: str`, `spoken: str | None`, `status: int | None`; `__init__(self, code: str, spoken: str | None = None, status: int | None = None)`
  - `class RelayAuthError(RelayError)` — credentials refused (a 3xx; a 401/403 without a JSON error body; a JSON error with status 401)
  - `class RelayConnectionError(RelayError)` — code `"network"`
  - `class RelayTimeoutError(RelayError)` — code `"timeout"`
  - `class RelayClient: __init__(self, session: aiohttp.ClientSession, url: str, client_id: str, client_secret: str)`; `async def health(self) -> None`; `async def turn(self, text: str, *, conversation_id: str | None = None, profile: str | None = None) -> TurnReply`; `async def end_conversation(self, conversation_id: str) -> None`. Its `__repr__` must not contain the secret or the client ID.
  - `def normalize_url(url: str) -> str` — strip whitespace and trailing `/`; raise `ValueError` unless the scheme is `http` or `https` and there is a host.
- Produces (`tests/fake_relay.py`): `class FakeRelay` wrapping `aioclient_mock`, with `queue_turn(*outcomes)`, where an outcome is `Reply(reply: str, conversation_id: str = "relay-conv-1", expect_secret: bool = False)`, `Error(status: int, code: str, spoken: str | None = None)`, `Raw(status: int, body: str, content_type: str = "text/html", headers: dict | None = None)`, or `Raise(exc: BaseException)`; properties `turn_requests: list[dict]` (JSON bodies) and `turn_headers: list[dict]`; `health_ok: bool`; `ended: list[str]`. Unqueued turns return `Reply("ok")`. Fixture `fake_relay` in `conftest.py`.

- [ ] **Step 1: Write the failing tests** in `tests/test_relay.py`:
  - `test_turn_success`: the body has `turn_id` (a UUID string), `text`, `client == "home-assistant"`, no `conversation_id` or `profile` keys when they are `None`; the headers carry `CF-Access-Client-Id: TEST_CLIENT_ID` and `CF-Access-Client-Secret: TEST_SECRET`; returns `TurnReply`.
  - `test_turn_sends_conversation_and_profile`.
  - `test_turn_retries_once_on_connection_error_same_turn_id`: `Raise(aiohttp.ClientConnectionError())` then `Reply`; two requests with equal `turn_id`.
  - `test_turn_connection_error_twice_raises_network`: `RelayConnectionError`, exactly 2 requests.
  - `test_turn_gateway_html_retried_then_network_error`: `Raw(530, "<html>")` twice → `RelayConnectionError`, 2 requests; also parametrize 502/503/504.
  - `test_turn_timeout`: `Raise(TimeoutError())` → `RelayTimeoutError`, exactly 1 request (no retry after a timeout).
  - `test_turn_error_codes` parametrized over all six codes × spoken present/absent: `RelayError` with that `code`, `spoken`, `status`. Status 401 with JSON → `RelayAuthError`.
  - `test_turn_profile_forbidden_is_not_auth_error`: `Error(403, "unauthorized", "That room isn't allowed.")` → `RelayError`, not `RelayAuthError`.
  - `test_turn_access_redirect_is_auth_error`: `Raw(302, "", headers={"Location": "https://example.cloudflareaccess.com/..."})` → `RelayAuthError`.
  - `test_turn_access_html_403_is_auth_error`.
  - `test_turn_malformed_200_raises`: `Raw(200, "{}", "application/json")` → `RelayError(code="bad_response")`.
  - `test_health_ok`, `test_health_down_raises_connection_error`.
  - `test_end_conversation_posts_end` (URL `/v1/conversations/relay-conv-1/end`).
  - `test_repr_hides_credentials`.
  - `test_normalize_url` (trailing slash, whitespace, `ftp://` and `relay.example.com` rejected).
- [ ] **Step 2:** Run `uv run pytest tests/test_relay.py -v`. Expected: FAIL (import error).
- [ ] **Step 3:** Implement `relay.py`. The turn budget is a deadline (`loop.time() + TURN_TIMEOUT`); each attempt runs under `asyncio.timeout(remaining)`. Retry only on `aiohttp.ClientConnectionError` or a 502/503/504/530 response whose body is not a JSON error, and at most once. Map failures to exceptions as the Interfaces block says; any other non-JSON response is `RelayError("unexpected_response", status=...)`. No logging of bodies or headers. Debug logs only status codes, attempt count and elapsed time.
- [ ] **Step 4:** Run `uv run pytest tests/test_relay.py -v`. Expected: PASS.
- [ ] **Step 5:** Commit ("Add the relay client").

### Task 3: Config flow, reauth, reconfigure, diagnostics

**Files:**
- Create: `custom_components/hey_claude/config_flow.py`, `diagnostics.py`; fill `translations/en.json`
- Modify: `custom_components/hey_claude/__init__.py` (build `RelayClient` with `async_get_clientsession(hass)`)
- Test: `tests/test_config_flow.py`, `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `RelayClient`, `normalize_url`, the exceptions (Task 2).
- Produces: `async def validate_relay(hass: HomeAssistant, url: str, client_id: str, client_secret: str) -> None` in `config_flow.py`, raising the Task 2 exceptions. It calls `health()`, then `turn(SETUP_TEST_TEXT)` with no profile, then `end_conversation()` (a failure on that last call is ignored). `SETUP_TEST_TEXT = "This is a connection test from Home Assistant. Reply with one word."` in `const.py`.
- Produces: `class HeyClaudeConfigFlow(ConfigFlow, domain=DOMAIN)` with `VERSION = 1`, steps `user`, `reauth` → `reauth_confirm`, `reconfigure`; `async_get_options_flow` is added in Task 4. Errors map `RelayAuthError` → `invalid_auth`; `RelayError` with `status == 403` → `not_allowed`; `RelayConnectionError` and `RelayTimeoutError` → `cannot_connect`; `ValueError` from `normalize_url` → `invalid_url`; any other `RelayError` → `relay_error`; anything else → `unknown` (logged with `_LOGGER.exception`, message only, no user input). Unique ID is the normalized URL; the title is `"Hey Claude"`.
- Fields: `url` uses `TextSelector(type=URL)`; `client_id` uses `TextSelector`; `client_secret` uses `TextSelector(type=PASSWORD)`. Reauth asks only for the ID and secret. Reconfigure pre-fills the URL and ID, and a blank secret keeps the stored one. Reconfigure may change the URL (it updates the unique ID through `async_update_reload_and_abort(..., unique_id=...)`, and aborts `already_configured` if another entry has that URL).
- Produces (`diagnostics.py`): `async_get_config_entry_diagnostics` returns `{"entry": async_redact_data(entry.as_dict(), TO_REDACT)}` with `TO_REDACT = {CONF_URL, CONF_CLIENT_ID, CONF_CLIENT_SECRET, "unique_id"}`. Task 5 adds `"conversations_tracked"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_config_flow.py`: `test_user_flow_success` (entry data equals the inputs with the URL normalized; `fake_relay.ended == ["relay-conv-1"]`); `test_user_flow_errors` parametrized: health down → `cannot_connect`, `Raw(302)` → `invalid_auth`, `Error(401, "unauthorized")` → `invalid_auth`, `Error(403, "unauthorized")` → `not_allowed`, `Raise(TimeoutError())` → `cannot_connect`, `Error(500, "internal")` → `relay_error`, URL `relay.example.com` → `invalid_url`; each case recovers to `CREATE_ENTRY` on resubmission. Also `test_user_flow_duplicate_aborts`, `test_reauth_flow` (secret updated, entry reloaded), `test_reauth_flow_invalid_auth`, `test_reconfigure_flow_changes_url`, `test_reconfigure_blank_secret_keeps_secret`. In `tests/test_diagnostics.py`, `test_diagnostics_redacted`: `TEST_SECRET`, `TEST_CLIENT_ID` and `relay.example.com` do not appear in `json.dumps(result)`.
- [ ] **Step 2:** Run `uv run pytest tests/test_config_flow.py tests/test_diagnostics.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the config flow, diagnostics and `translations/en.json`: `config.step.{user,reauth_confirm,reconfigure}` with `data` and `data_description` (say the ID and secret come from a Cloudflare Access service token); `config.error.{cannot_connect,invalid_auth,not_allowed,invalid_url,relay_error,unknown}`; `config.abort.{already_configured,reauth_successful,reconfigure_successful}`.
- [ ] **Step 4:** Run `uv run pytest -v` and `uv run mypy custom_components`. Expected: PASS, no mypy errors.
- [ ] **Step 5:** README: what it is; requirements (Home Assistant 2026.10+, a relay, a Cloudflare Access service token that the relay allows); **Install** (HACS → ⋮ → Custom repositories → this repo URL, category Integration → install → restart); **Set up** (Settings → Devices & services → Add integration → Hey Claude, fields explained); reauth and reconfigure; **Diagnostics** (what is redacted); **Privacy** (what the integration never logs, and why passphrases must not go through Home Assistant, from the spec). Commit ("Add setup, reauth, reconfigure and diagnostics").
- [ ] **Step 6: Milestone gate.** Push, mark the PR ready, wait for green CI (`gh pr checks --watch`). Give Nick checklist M1 (below) and wait for the results before merging.

**Checklist M1 (Nick):** (1) Add the repo in HACS as a custom repository, install, restart. (2) Add Hey Claude with a wrong secret: the form says the credentials were refused. (3) Add it with the right token: the entry is created, and the relay shows one test turn. (4) Use Reconfigure and Reauthenticate on the entry and confirm both save. (5) Download diagnostics: no URL, client ID or secret in it.

---

## Milestone 2 — talking (PR 2, branch `m2-conversation` from the merged `main`)

### Task 4: Area→profile resolution and options flow

**Files:**
- Create: `custom_components/hey_claude/profile.py`
- Modify: `config_flow.py` (add `HeyClaudeOptionsFlow`), `translations/en.json`
- Test: `tests/test_profile.py`, `tests/test_options_flow.py`

**Interfaces:**
- Produces (`profile.py`):
  - `def area_for_turn(hass: HomeAssistant, device_id: str | None, satellite_id: str | None) -> str | None` — the satellite entity's registry `area_id`; else that entity's device's `area_id`; else `device_id`'s device's `area_id`; else `None`.
  - `def resolve_profile(options: Mapping[str, Any], area_id: str | None) -> str | None` — `options[CONF_AREA_PROFILES][area_id]` if present, else `options.get(CONF_DEFAULT_PROFILE)`, else `None`. Empty strings count as unset.
- Produces: `class HeyClaudeOptionsFlow(OptionsFlow)` with one step `init`. Its schema is `CONF_DEFAULT_PROFILE` (optional text) plus `section("rooms", ...)` holding one optional text field per area in the area registry, keyed by **area name** with the current profile as `suggested_value`. On save, names map back to area IDs; blank fields are dropped; values are stripped; IDs no longer in the registry are dropped. Stored options: `{CONF_DEFAULT_PROFILE: str, CONF_AREA_PROFILES: dict[str, str]}` (area_id → profile). No reload needed, because the entity reads `entry.options` on every turn.

- [ ] **Step 1: Write the failing tests:** `test_area_from_satellite_entity`, `test_area_from_satellite_device` (the entity has no area), `test_area_from_device_id` (no satellite), `test_area_none`; `test_resolve_profile_area_then_default_then_none`; `test_profile_survives_area_rename`; `test_options_flow_saves_by_area_id`; `test_options_flow_blank_removes`; `test_options_drop_deleted_areas`.
- [ ] **Step 2:** Run `uv run pytest tests/test_profile.py tests/test_options_flow.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. Translations: `options.step.init.data.default_profile`, `options.step.init.sections.rooms.name` ("Profile per area"), with descriptions saying names are free text that the relay owns, and blank means "use the default".
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit ("Add per-area profiles").

### Task 5: Conversation entity

**Files:**
- Create: `custom_components/hey_claude/conversation.py`
- Modify: `__init__.py` (`PLATFORMS = [Platform.CONVERSATION]`), `const.py` (spoken lines), `diagnostics.py`
- Test: `tests/test_conversation.py`

**Interfaces:**
- Consumes: `RelayClient.turn`, `RelayClient.end_conversation`, the exceptions (Task 2); `area_for_turn` and `resolve_profile` (Task 4); `HeyClaudeConfigEntry` (Task 1).
- Produces: `class HeyClaudeConversationEntity(conversation.ConversationEntity)`. `_attr_has_entity_name = True`, `_attr_name = None`, `_attr_unique_id = entry.entry_id`, `DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="Claude", entry_type=DeviceEntryType.SERVICE)`, `supported_languages = "*"`, no `CONTROL` feature. Attribute `relay_conversations: LimitedSizeDict[str, str]` (`size_limit=100`), mapping a Home Assistant conversation ID to a relay conversation ID; `diagnostics.py` reports its `len` as `"conversations_tracked"`.
- Spoken lines in `const.py`, exact copy:
  - `FALLBACK_LINES = {"unauthorized": "Claude isn't letting this speaker in right now.", "bad_request": "Claude couldn't make sense of that.", "upstream_timeout": "Claude ran out of time on that one.", "upstream_error": "Something went wrong on Claude's side.", "rate_limited": "Claude is busy right now. Try again in a minute.", "internal": "Something went wrong on Claude's side.", "timeout": "I couldn't get an answer from Claude in time.", "network": "I couldn't reach Claude."}`
  - `DEFAULT_FALLBACK = "Sorry, something went wrong reaching Claude."`
  - `EMPTY_REPLY_LINE = "Claude didn't have anything to say."`
  - `SECRET_REFUSED_LINE = "That needs your passphrase, which I can't take here."`

`_async_handle_message(user_input, chat_log)`:
1. `profile = resolve_profile(entry.options, area_for_turn(hass, user_input.device_id, user_input.satellite_id))`; `relay_id = relay_conversations.get(chat_log.conversation_id)`.
2. Call `client.turn(user_input.text, conversation_id=relay_id, profile=profile)`.
3. On `RelayAuthError`, call `entry.async_start_reauth(hass)`; then, for every `RelayError`: speech = `err.spoken or FALLBACK_LINES.get(err.code, DEFAULT_FALLBACK)`, and the response is `async_set_error(IntentResponseErrorCode.UNKNOWN, speech)`.
4. On success: store `relay_conversations[ha_id] = reply.conversation_id`. If `reply.expect_secret`: `end_conversation` (suppress `RelayError`), pop the mapping, speech = `SECRET_REFUSED_LINE`. Otherwise speech = `reply.reply.strip() or EMPTY_REPLY_LINE`. Response: `async_set_speech(speech)`.
5. Add `AssistantContent(agent_id=user_input.agent_id, content=speech)` with `chat_log.async_add_assistant_content_without_tools`. Return `ConversationResult(response, conversation_id=chat_log.conversation_id, continue_conversation=<success and not expect_secret and chat_log.continue_conversation>)`.

- [ ] **Step 1: Write the failing tests** (drive them with `conversation.async_converse(hass, text, conversation_id, Context(), agent_id="conversation.claude", device_id=..., satellite_id=...)`):
  - `test_turn_speaks_reply` (speech equals the reply; the relay got `client == "home-assistant"`).
  - `test_profile_from_area`: a satellite entity in an area with a profile → `profile` sent; `test_profile_default`; `test_profile_omitted`.
  - `test_conversation_id_mapping`: the second turn on the returned Home Assistant `conversation_id` sends `"relay-conv-1"`; a fresh Home Assistant conversation sends none.
  - `test_relay_rotates_conversation_id`.
  - `test_retry_same_turn_id` (a connection error, then a reply → the reply is spoken).
  - `test_timeout_speaks_fallback`.
  - `test_error_codes_spoken` parametrized over the six codes × spoken present/absent: speech equals `spoken` or `FALLBACK_LINES[code]`; the response type is `error`.
  - `test_profile_forbidden_403_speaks_and_no_reauth`: `Error(403, "unauthorized", "That room isn't allowed.")` → that line spoken; no flow in `hass.config_entries.flow.async_progress()`.
  - `test_auth_failure_starts_reauth`: `Raw(302)` → `FALLBACK_LINES["unauthorized"]` spoken; one `reauth` flow in progress.
  - `test_empty_reply_speaks_fallback` (`""` and `"  "`).
  - `test_question_continues_conversation` (`"Which room?"` → `continue_conversation is True`); `test_statement_does_not_continue`.
  - `test_expect_secret_refused`: `Reply("What's the passphrase?", expect_secret=True)` → speech is `SECRET_REFUSED_LINE`, `continue_conversation is False`, `fake_relay.ended == ["relay-conv-1"]`, and the next turn on the same Home Assistant conversation sends no `conversation_id`.
  - `test_expect_secret_end_failure_still_refuses`.
  - `test_never_silent`: parametrized over every `FakeRelay` outcome type; speech is a non-empty string.
- [ ] **Step 2:** Run `uv run pytest tests/test_conversation.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `conversation.py` (`async_setup_entry` adds one entity) and the `const.py` lines. Debug logs carry only the profile, elapsed time, `tools_used` and error codes; never text or a reply.
- [ ] **Step 4:** Run `uv run pytest -v`, `uv run mypy custom_components`, `uv run ruff check`. Expected: all pass.
- [ ] **Step 5:** Commit ("Add the conversation agent").

### Task 6: Hygiene tests and the pipeline guide

**Files:**
- Test: `tests/test_hygiene.py`
- Modify: `README.md`

- [ ] **Step 1: Write the test** `test_secret_and_words_never_logged`. Use `caplog.set_level(logging.DEBUG)` on the root logger. Run the user flow, reauth, reconfigure, the options flow, a successful turn, an error turn, an auth-failure turn, an `expect_secret` turn, diagnostics and unload. Assert that `TEST_SECRET`, `TEST_CLIENT_ID`, the turn text (`"unique words for the log check"`) and the reply text (`"distinct reply for the log check"`) do not appear in `caplog.text`. Assert that `TEST_SECRET` and `TEST_CLIENT_ID` do not appear in `json.dumps(diagnostics)`. If Home Assistant core itself logs one of these, stop and report it rather than filtering the test.
- [ ] **Step 2:** Run `uv run pytest tests/test_hygiene.py -v`. Expected: PASS. Fix any leak in this integration.
- [ ] **Step 3:** README **Pipeline** section: Settings → Voice assistants → Add assistant "Claude"; conversation agent = Claude; speech-to-text and text-to-speech = your local engines; turn on "Prefer handling commands locally". Point the satellite's assistant setting (or second slot, if it has one) at "Claude". Put the satellite's device in an area, then set profiles under the integration's Configure. Continued conversation needs a satellite that honours `continue_conversation` (ESPHome `voice_assistant`, for example the Voice Preview Edition); Wyoming and VoIP satellites need the wake word again. **Passphrases**: set every Home Assistant-facing profile on the relay to refuse gated actions; this integration refuses `expect_secret` replies.
- [ ] **Step 4:** Commit ("Add hygiene tests and the pipeline guide"). Push, open PR 2, and wait for green CI. Give Nick checklist M2 and wait for the results before merging.

**Checklist M2 (Nick):** (1) Put the satellite's device in its area; set a default profile and that area's profile under Configure. (2) Create the "Claude" pipeline as in the README and point slot 2 at it. (3) Wake slot 2 and ask something only Claude can answer: a spoken reply, and the relay log shows the area's profile. (4) Say a simple home command ("turn on the office light"): it's handled locally, and the relay sees nothing. (5) Ask something that makes Claude ask back: the mic reopens with no wake word, and the answer continues the same relay conversation. (6) Stop the relay or tunnel and ask: you hear "I couldn't reach Claude." (7) Ask for a profile the token isn't allowed (temporarily set that area's profile to one): you hear the relay's refusal line. (8) Check that `/config/logs` shows neither your words nor the secret.
