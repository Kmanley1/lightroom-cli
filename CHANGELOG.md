# Changelog

All notable changes to this project will be documented in this file.

## [1.3.1] - 2026-10-01

### Added
- **`catalog collections` now reports each collection's `parentId` / `parentName`** (nil for a
  top-level collection). Previously only `{id, name, type}` — there was no way to tell from the
  CLI whether a collection was nested inside a collection set, only by looking at Lightroom's own
  panel. Verified live: correctly reported four real collections as nested under a named trip
  sub-set ("2026_04 Chicago Spring Break") after a manual drag-and-drop in Lightroom.

## [1.3.0] - 2026-10-01

Collection management: rename, delete, and nested collection sets.

### Added
- **`catalog rename-collection <id> <new_name>`** — rename an existing collection. Not previously
  possible via this CLI at all (not just an unexposed flag — the capability didn't exist).
- **`catalog delete-collection <id>`** — delete a collection or collection set by id (tries
  collection first, falls back to collection set). Never touches member photos — same scope as
  Lightroom's own right-click Delete on a collection.
- **`catalog create-collection-set --parent <id>`** — collection sets can now nest inside other
  collection sets, mirroring how `create-collection --parent` already worked for plain collections.
  `create-collection-set` previously hardcoded its parent to `nil` in the Lua implementation, so no
  CLI flag could have made this work before now.

### Fixed
- **`catalog create-collection-set` now returns the new set's `id`.** It previously returned only
  `{name, message}` — there was no way to reference a freshly created set as a `--parent` for
  anything, including the new nesting feature above.

All three verified live: created a throwaway nested collection set, confirmed visually in Lightroom's
Collections panel (not just trusting the API response), renamed a test collection and independently
re-queried it to confirm the name actually persisted, then deleted all test artifacts and confirmed
zero remained via a fresh catalog-wide query.

## [1.2.2] - 2026-04-06

### Fixed
- macOS でポートファイルが見つからず接続できない問題を修正 — `/tmp` ハードコードを `tempfile.gettempdir()` に変更（macOS の実際のテンポラリディレクトリは `/var/folders/...` であり `/tmp` と異なる）

## [1.2.0] - 2026-03-07

Stability improvements, batch develop, extended search filters, and new catalog commands.

### Added
- **Extended search filters** for `catalog find` — `--folder-path`, `--capture-date-from`, `--capture-date-to`, `--file-format`, `--keyword`, `--filename`
- **`develop batch-set`** — batch set a single develop parameter across multiple photos (`--photo-ids`)
- **`catalog collection-photos`** — get photos from a collection by ID with pagination
- **`catalog develop-presets`** — list/search develop presets by name or folder
- **NDJSON streaming** — `StreamAggregator` for chunked responses with progress callbacks
- **Command cancellation** — Lua-side `shouldAbort()` checks at chunk boundaries
- **Version sync** — `scripts/sync_version.py` + CI `check-version` job
- **`protocolVersion`** field in ping response

### Fixed
- `searchPhotos` backward compatibility — delegates to `findPhotos` with `hasMore` field preserved
- `captureDateTo` inclusive date handling — date-only input appends `T23:59:59`
- Keyword filter uses plain text matching (`string.find` with `plain=true`)
- Stream cleanup — `_pending_streams` entry removed after final event
- `getCommandRouter` uses correct global key (`commandRouter`, not `router`)
- Negative offset crash in `getCollectionPhotos` — clamped with `math.max`

### Changed
- `searchPhotos` deprecated in favor of `findPhotos`
- 814+ tests (was 750+)

## [1.1.0] - 2026-03-06

MCP Server support, Windows compatibility, and reliability improvements.

### Added
- **MCP Server** — `lr-mcp` entry point for Claude Desktop / Cowork integration
  - `lr mcp install` / `uninstall` / `status` / `test` commands
  - All 107 CLI commands available as MCP tools (`lr_` prefix + snake_case)
  - Auto-resolves absolute path for Claude Desktop's PATH-limited environment
- **Windows support** — platform-aware path resolution (`platformdirs`), CI matrix with `windows-latest`. Not yet tested on real hardware — [please report issues](https://github.com/znznzna/lightroom-cli/issues)
- **Input validation layer** — `lightroom_sdk/validation.py` with type coercion, range checks, enum validation, string sanitization
- **Schema-driven architecture** — `lightroom_sdk/schema.py` as single source of truth for all command parameters
- **`--json` / `--json-stdin`** — JSON input for all commands, enables pipe-based workflows
- **`--dry-run`** — preview command execution without sending to Lightroom

### Fixed
- Schema/Lua parameter name mismatches (14 commands fixed)
- `catalog set-rating 0` — Lua `and/or` idiom fails with `nil`; use explicit `if` statement
- `catalog remove-keyword` — pass keyword object instead of string to `photo:removeKeyword()`
- `catalog select` — `withWriteAccessDo` return value not propagated; use external variable
- `catalog batch-metadata` — iterate photo-keyed table instead of integer-indexed
- `develop range` — `math.abs()` for correct min/max when range is negative number
- `develop set` — unknown parameter detection changed from `getRange` to `getValue`
- Exit code 0 on Lightroom errors — added `success: false` check in `helpers.py`

### Changed
- `fastmcp` is now a required dependency (was optional `[mcp]` extra)
- `develop set` with multiple pairs uses individual `setValue` calls instead of `batchApplySettings`
- 750+ tests (was 680+)

## [1.0.0] - 2026-03-06

Initial public release — 107 CLI commands covering all Lightroom Classic Lua API operations.

### Highlights
- **CLI tool (`lr`)** with `system`, `catalog`, `develop`, `preview`, `selection`, `plugin` command groups
- **107 commands** for full Lightroom Classic control
- **AI Mask API** — subject/sky/background/people/landscape with adjustments and presets
- **Agent-first design** — `lr schema` for dynamic discovery, `--fields`, `--dry-run`, structured JSON errors
- **ResilientSocketBridge** with auto-reconnect, heartbeat, per-command timeouts
- **Lua plugin** bundled and installable via `lr plugin install`
- **3 output formats**: `text`, `json`, `table`
- **680+ tests** (unit + integration)
