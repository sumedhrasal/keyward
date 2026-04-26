# Security policy

## Reporting a vulnerability

If you believe you've found a security issue in keyward, please do **not** open
a public GitHub issue. Instead, email the maintainer at
**srasal3@gatech.edu** with:

- a description of the issue,
- the keyward version (`keyward --version`) and your OS,
- minimal reproduction steps,
- the impact you think it has.

You'll get an acknowledgement within a few days. Once a fix is shipped, the
disclosure will be credited unless you ask otherwise.

## Threat model

keyward is designed for a specific threat model — see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full table. Briefly:

- **In scope:** an attacker who can read the source tree, environment
  variables, and `~/.config/keyward/config.toml`. Such an attacker should see
  only opaque tokens, not real keys, and should not be able to use the tokens
  to reach a destination the user has not approved.
- **Out of scope:** an attacker with root, the ability to attach a debugger to
  the keyward daemon, or write access to `~/.config/keyward/config.toml`. The
  OS keychain is the trust boundary.

If you're unsure whether a behavior counts as a vulnerability, email anyway.
