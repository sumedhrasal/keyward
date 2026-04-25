# Changelog

All notable changes to keyward are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `keyward.activate()` — runtime API for in-process token activation, so apps
  can call into the daemon without going through `keyward run`.
- `keyward.DaemonNotRunning` exception, raised by `activate(strict=True)`.
- `scripts/verify_swap.py <name>` — standalone Python script for verifying that
  the daemon swaps a token for the real secret.
- `SECURITY.md`, `CHANGELOG.md`, `py.typed` marker, GitHub Actions CI matrix
  (Linux + macOS, Python 3.11 / 3.12 / 3.13), ruff lint+format config.

### Changed
- `CacheEntry` is now a `NamedTuple` with named fields rather than a positional
  tuple alias.
- Daemon discovery (`live_daemon_info`, `live_daemon_url`) extracted to
  `keyward.discovery` and reused by both the CLI and `activate()`.
- Endpoint scheme is validated at `keyward add` time and again in the daemon
  request handler. Only `http://` and `https://` are allowed; bare hostnames
  default to `https://`.

## [0.0.1] - 2026-04-21

Initial scaffold and v0.2 functionality.

### Added
- CLI: `init`, `add`, `list`, `rm`, `rotate`, `restart`, `run`.
- OS-keychain storage via `keyring`.
- Token format: `kw_` + 16 hex chars.
- Local aiohttp proxy with Bearer and `x-api-key` support, SSE streaming.
- macOS LaunchAgent install/uninstall via `keyward init`.
- Threat model and architecture documentation.
