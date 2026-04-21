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

## Status

Design stage. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design,
threat model, and component breakdown. No implementation yet.

## License

TBD.
