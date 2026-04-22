# keyward architecture

## Main goal

Let a developer run untrusted code-reading tools (AI agents, linters, third-party
IDE plugins) on a machine where API keys must also live, without exposing those
keys to the tools. The design target is: if an attacker can read every file in
the repo and every environment variable in the process, they still cannot use
the key against a service the developer did not authorize.

Secondary goal: onboarding must be so cheap that a user will adopt it for a
single script. Every operation below must finish in one short command.

## Non-goals

- Team-scale secret sharing (use Doppler, 1Password service accounts, Vault).
- Production runtime secret injection (use your cloud's secret manager).
- Defense against an attacker with root on the developer machine. That attacker
  wins regardless; the OS keychain is the effective boundary.

## Threat model

| Attacker capability                              | Outcome                                 |
|--------------------------------------------------|-----------------------------------------|
| Reads source files, .env, config                 | Sees tokens only, no real keys          |
| Reads process environment of the app             | Sees tokens only                        |
| Calls the local daemon with a token              | Only allowlisted destinations forwarded |
| Calls daemon, picks a new destination            | Blocked pending user approval           |
| Reads the OS keychain (requires user auth)       | Wins; this is the trust boundary        |
| Has root / can ptrace the daemon                 | Wins; out of scope                      |

The core insight: a local proxy on its own does not help, because a local agent
can call the proxy too. The value comes from the **allowlist** and the
**approval prompt on new destinations**. Those turn the proxy from a lookup
table into a policy enforcement point.

## System overview

```
+------------------------------------------------------------------+
|                      Developer Machine                           |
|                                                                  |
|   +-----------+        +----------------+       +-------------+  |
|   |  keyward  | -----> |  keyward       | <---> |     OS      |  |
|   |    CLI    |        |  daemon        |       |   Keychain  |  |
|   +-----------+        |  (127.0.0.1)   |       +-------------+  |
|                        |                |                        |
|   +-----------+        |                |       +-------------+  |
|   |  User     | -----> |                | ----> |   Audit     |  |
|   |  app /    |        |                |       |    log      |  |
|   |  agent    |        |                |       +-------------+  |
|   +-----------+        +-------+--------+                        |
|                                |                                 |
|                                | allowlisted egress only         |
+--------------------------------+---------------------------------+
                                 |
                                 v
                     +-----------------------+
                     |   api.openai.com      |
                     |   api.anthropic.com   |
                     |   ... (per-key)       |
                     +-----------------------+
```

## Components

**CLI (`keyward`)** - thin front-end. Never prints, logs, or accepts secrets on
the command line; prompts via hidden stdin. Talks to the daemon over a
unix socket.

**Daemon** - long-running local HTTP proxy bound to `127.0.0.1` on a port
written to `~/.config/keyward/daemon.json`. Responsibilities:
- token to secret lookup
- per-key endpoint allowlist enforcement
- approval prompt on unknown destinations (desktop notification + TUI fallback)
- audit logging
- optional rate and budget caps per key

**Keystore** - OS keychain via `keyring` (macOS Keychain, Windows Credential
Manager, libsecret on Linux). The daemon is the only process that reads it.

**Config** - `~/.config/keyward/config.toml`. Plaintext is fine: it holds
tokens, allowlists, and metadata, but no secrets. Example entry:

```toml
[keys.openai]
token     = "kw_ab12cd34ef56"
endpoint  = "api.openai.com"
env_vars  = ["OPENAI_API_KEY"]
base_url  = "OPENAI_BASE_URL"
created   = 2026-04-21
```

**Audit log** - append-only JSONL at `~/.local/state/keyward/audit.log`.
One record per forwarded request: timestamp, key name, method, host, path,
status, byte counts, caller PID and argv[0]. No request or response bodies.

## Request flow

```
 App             Daemon          Keychain        api.openai.com
  |                |                |                 |
  |--POST /v1/... ->                |                 |
  |  Authorization: Bearer kw_ab12..|                 |
  |                |--lookup("openai")->              |
  |                |<--sk-real-key----                |
  |                |                                  |
  |                |--check allowlist (host ok)       |
  |                |--log request                     |
  |                |                                  |
  |                |--POST /v1/... Bearer sk-real ---->
  |                |<--200 {...}---------------------|
  |<--200 {...}----|                                  |
```

On a new destination:

```
 App             Daemon         Desktop
  |                |               |
  |--POST ...----->|               |
  |                |--notify("allow api.new.com for openai? [y/N]")->
  |                |<-- user clicks yes -------------|
  |                |--update allowlist               |
  |                |--forward                        |
  |<--200 {...}----|                                  
```

If no GUI is available (SSH session, CI), the daemon returns `403` with a
clear message telling the user to run `keyward approve openai api.new.com`.

## Key operations

Every operation must feel lighter than the `.env` workflow it replaces.

| Command                                   | Prompts       | Effect                             |
|-------------------------------------------|---------------|------------------------------------|
| `keyward add <name> --endpoint <host>`    | hidden stdin  | store secret, mint token           |
| `keyward rotate <name>`                   | hidden stdin  | replace secret, keep token         |
| `keyward rm <name>`                       | y/N           | delete secret, revoke token        |
| `keyward list`                            | none          | print names, tokens, endpoints     |
| `keyward run -- <cmd>`                    | none          | exec cmd with env vars injected    |
| `keyward approve <name> <host>`           | none          | add host to that key's allowlist   |
| `keyward log [--since 1h] [--key openai]` | none          | tail the audit log                 |

Rotation keeping the token stable is critical: rotating a key must not require
any code change.

## Trust boundaries

```
  +-- untrusted -----------+    +-- trusted ----------+
  | source tree            |    | OS keychain         |
  | env vars               |    | keyward daemon mem  |
  | config.toml            |    | local unix socket   |
  | shell history          |    +---------------------+
  | AI agents / plugins    |
  +------------------------+
```

A secret only ever crosses into the trusted side. Tokens move freely on the
untrusted side; that is the whole point.

## Platform notes

- **macOS**: keychain entries gated by the login keychain; daemon launched as a
  LaunchAgent so it starts at login and pre-warms the in-memory secret cache.
- **Linux**: libsecret via `keyring`; daemon as a user systemd unit with
  `WantedBy=default.target` for the same pre-warm behavior.
- **Windows**: Credential Manager; daemon as a scheduled task at logon.

## v1 design decisions

These were open questions during design; the resolutions below are the scope
for v1.

**Caller attestation: trust-anything on localhost.** Any process that holds a
token and can reach `127.0.0.1` can use it. The allowlist is the primary
defense; attestation is not. Rationale: the cross-platform story for PID
attestation is ugly (fine on Linux/macOS over unix sockets, awkward on
Windows, impossible over loopback TCP) and the marginal security is small
given the allowlist already blocks exfiltration. See Future improvements.

**Streaming protocol support: SSE yes, websockets no.** The daemon will proxy
`text/event-stream` responses without buffering, preserving chunked transfer
encoding and writing one audit entry per request (not per chunk). Websockets
(e.g. OpenAI Realtime) are explicitly unsupported in v1; the daemon returns
`501 Not Implemented` on HTTP Upgrade. Documented as a known limitation.

**Env scrubbing of the token after child exec: not done.** Tokens are not
themselves secrets; scrubbing them from `/proc/<pid>/environ` adds complexity
without changing the threat model.

**Daemon bootstrap: pre-warmed at login.** `keyward init` installs a user
LaunchAgent (macOS) / systemd user unit (Linux) / scheduled task (Windows)
that starts the daemon at login. The daemon reads all registered secrets
from the OS keychain on startup and caches them in memory for the session,
so any keychain authorization prompt fires once at login, never in the
middle of a `keyward run` invocation.

## Future improvements

- **Caller attestation.** Add an opt-in strict mode: `keyward run` registers
  its PID tree with the daemon over a unix socket; the daemon honors tokens
  only from registered ancestries. Good fit once the v1 surface is stable
  and a real user has been bitten by an in-repo token leak.
- **Websocket support.** HTTP Upgrade handshake plus bidirectional byte
  tunnel, needed once Realtime-style APIs become common in the user's
  workflow.
- **Signed/notarized macOS build.** Unsigned binaries prompt the keychain on
  every daemon restart. A signed `.app` or notarized binary makes
  "always allow" stick. Matters once a wider user base is onboarding.
- **Per-key rate and budget caps.** Stub exists in config; enforcement in the
  daemon is a v1.x item.
