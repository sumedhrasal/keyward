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
  LaunchAgent so it starts on login.
- **Linux**: libsecret via `keyring`; daemon as a user systemd unit.
- **Windows**: Credential Manager; daemon as a scheduled task at logon.

## Open design questions

1. Should the daemon require per-request attestation of the caller (e.g. PID
   namespace checks) or trust anything on localhost? The former raises the bar
   but adds friction and is OS-dependent.
2. How do we handle streaming APIs (SSE, websockets) in the proxy path?
3. Should `keyward run` scrub the token from `/proc/<pid>/environ` after the
   child has read it, or is that overkill given the token is not itself a
   secret?
4. How is the daemon bootstrapped the first time without the user hitting a
   keychain password prompt mid-command?
