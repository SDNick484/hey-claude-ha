# Hey Claude for Home Assistant

A Home Assistant conversation agent that sends what you say to a
[hey-claude-relay](https://github.com/SDNick484) and speaks its reply.

A voice satellite hears you, Home Assistant turns speech into text, this
integration posts the text to the relay, and Home Assistant speaks the
reply. Simple home commands stay local: leave "Prefer handling commands
locally" on in the pipeline and they never reach the relay.

## Requirements

- Home Assistant 2026.10 or later.
- A running hey-claude-relay behind Cloudflare Access.
- A Cloudflare Access service token that the relay allows.

## Install

1. In Home Assistant, open **HACS**.
2. Open the **⋮** menu, then **Custom repositories**.
3. Add `https://github.com/SDNick484/hey-claude-ha` with the type
   **Integration**.
4. Find **Hey Claude** in HACS and download it.
5. Restart Home Assistant.

## Set up

1. Go to **Settings → Devices & services → Add integration** and pick
   **Hey Claude**.
2. Fill in:
   - **Relay URL**: the relay's base URL, such as `https://relay.example.com`.
   - **Access client ID** and **Access client secret**: the service token's
     two halves, from the Cloudflare Zero Trust dashboard.
3. Submit. Home Assistant checks `/healthz`, then sends one real test turn
   (and ends that conversation), so a refused token shows up now and not the
   first time you speak.

The secret is stored with the config entry, like every integration's
credentials, and is never written to the log.

### Replace the token or move the relay

- If Access or the relay starts refusing the token, Home Assistant shows a
  **Reauthenticate** prompt on the integration. Enter the new token there.
- To change the URL or token yourself, open the integration's **⋮** menu and
  pick **Reconfigure**. Leave the secret blank to keep the stored one.

## Diagnostics

**⋮ → Download diagnostics** on the integration gives a file you can share
when reporting a problem. It leaves out the relay URL, the Access client ID
and the Access client secret.

## Privacy

This integration never logs what you said, what Claude replied, or the
Access credentials.

Home Assistant itself does keep what you say: the speech-to-text server's
log, the pipeline debug view, the conversation's chat log, conversation
traces, and anything the satellite shows or reports. This integration cannot
prevent that. So **never say a passphrase through Home Assistant**: set
every relay profile that Home Assistant uses to refuse actions gated behind
a passphrase. If the relay still asks for one, this integration ends that
conversation and says it can't take a passphrase here.
