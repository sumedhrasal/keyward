# keyward

A local secret broker for developers who run AI coding agents on their own machines.

## The goal

Keep API keys out of any file an AI agent, co-pilot, or third-party tool can read,
without adding friction to normal development.

Your code never contains real keys. It contains opaque tokens like `kw_ab12cd34`.
A local daemon swaps the token for the real key only when the outbound request
goes to an allowlisted endpoint, and records every use.

If an agent reads your code, config, or environment, it sees tokens. Tokens are
useless off-host: they only resolve inside the daemon, which will not forward
them to destinations you have not explicitly approved.

## Why this is not just encryption

"One-way encryption you can decrypt" does not exist. What this package actually
provides is **tokenization plus a scoped, audited forward proxy**. The security
properties that matter are:

- real secrets live in the OS keychain, never on disk in plaintext
- code and config contain only tokens
- the daemon forwards to an allowlist, so a leaked token cannot exfiltrate data to a new host
- every resolution is logged
- new destinations require explicit user approval

## Intended user experience

Onboarding is the product. If any step feels heavier than `export KEY=...`,
it has failed its design goal.

```
# one-time setup
pip install keyward
keyward init

# add a key (prompts for the secret; never passed on the command line)
keyward add openai --endpoint api.openai.com

# run any program with tokens injected as env vars
keyward run -- python app.py
keyward run -- pytest
keyward run -- npm start

# rotate a key in place; tokens stay the same so no code changes
keyward rotate openai

# list, remove, inspect
keyward list
keyward rm openai
keyward log --since 1h
```

Your code stays boring:

```python
import os, openai
client = openai.OpenAI()   # reads OPENAI_API_KEY and OPENAI_BASE_URL from env
```

Under `keyward run`, those variables point at the local daemon with a token.
Outside `keyward run`, they are not set at all.

## What works today (v0.2)

| Area                  | Status                                                                 |
|-----------------------|------------------------------------------------------------------------|
| CLI commands          | `init`, `add`, `list`, `rm`, `rotate`, `restart`, `run` all functional |
| Keychain storage      | macOS Keychain, Windows Credential Manager, Linux libsecret via `keyring` |
| Proxy forwarding      | Authorization: Bearer and x-api-key, on both ingress and egress        |
| Streaming             | Server-Sent Events forwarded without buffering                         |
| Login agent           | macOS LaunchAgent install/uninstall/kickstart via `keyward init`       |
| Daemon reuse          | `keyward run` reuses a live daemon; else spawns ephemeral              |
| Audit log             | Stub only (prints TODO; no log is written yet)                         |
| Multi-endpoint allowlist | Stub only; each key is pinned to one endpoint in v0.2               |
| Linux systemd / Windows scheduled task | Not wired up yet                                      |
| Websocket proxying    | Returns 501; HTTP only for now                                         |
| Request body streaming| Buffered; fine for LLM chat, not for large uploads                     |
| Caller attestation    | Trust-anything on localhost; see ARCHITECTURE.md                       |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design, threat
model, and the list of deferred items.

## Verifying the key swap

The sharpest test is to point keyward at a request-echoing endpoint and look
for your raw secret (and the absence of the token) in the response.

```bash
# pick a distinctive fake secret so you can spot it in the echo
keyward add echotest --endpoint httpbin.org
# at the prompt, enter: sk-fake-secret-12345

keyward restart   # only needed if a LaunchAgent daemon is already running

keyward run -- curl -s "$ECHOTEST_BASE_URL/anything" \
    -H "Authorization: Bearer $ECHOTEST_API_KEY"
```

In the JSON response, under `headers.Authorization`:
- `Bearer sk-fake-secret-12345` means the swap worked.
- Anything starting with `Bearer kw_` means the swap did not happen (bug).

For the Anthropic-style (x-api-key):

```bash
keyward add echotestx --endpoint httpbin.org --auth-style x-api-key
keyward restart
keyward run -- curl -s "$ECHOTESTX_BASE_URL/anything" \
    -H "x-api-key: $ECHOTESTX_API_KEY"
```

Check `headers.X-Api-Key` in the response.

Clean up with `keyward rm echotest -y && keyward rm echotestx -y`.

## License

MIT. See [LICENSE](LICENSE).
