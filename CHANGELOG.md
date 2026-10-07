# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed
- **Every error printed a second line** `{"error": {"code": "ERROR", "message": "1"}}` (2026-10-06): `ctx.exit()`
  raises click's `Exit`, a `RuntimeError` subclass in Click 8, and `execute_command`'s `except Exception` caught it
  and printed `str(Exit(1))`. `Exit` now passes through; exit codes were already right and are unchanged.
- **A photo id that is not in the catalog crashed `remove-keyword`** and failed a whole `batch-add-keywords` /
  `batch-remove-keywords` call ("?:0: attempt to index a nil value"). Measured live 2026-10-07 with the new
  `catalog probe-photo` diagnostic: for an unknown id Lightroom's `getPhotoByLocalId` neither throws nor returns
  nil -- it returns a DUD object whose `uuid` and `path` read back nil and whose other reads (flag, keywords, file
  name) throw. Two earlier attempts guessed wrong: both still treated only an ERROR as "not there" (first around
  the lookup, then around the lookup plus a uuid read), and the dud raises none. The fix: a photo exists only if
  it has a uuid -- a nil uuid, not an error, means absent. These three commands now report `PHOTO_NOT_FOUND` /
  `photo_not_found` per pair; a lookup that fails any other way is `OPERATION_FAILED` / `unverified`, never
  "not found".
  **`batch-remove-keywords` `complete` now also requires every photo to be found**, matching `batch-add-keywords`.
  The other 24 `getPhotoByLocalId` call sites (23 handlers: 16 catalog, 4 develop, 3 preview) still mis-handle an
  unknown id -- backlog.

### Added (diagnostics)
- **`catalog probe-photo <id>`** (2026-10-07) -- read-only: runs each step of looking a photo up and reading it, each
  in its own protected call, and reports which step fails and how. `system ping` now also returns a `build` marker,
  bumped with every plugin change, so a Reload Plug-in that did not take is visible.
- **`catalog probe-api [--keyword-id N]`** (2026-10-07) -- read-only: lists the methods Lightroom exposes on the
  catalog and on a keyword (own and inherited), and looks up named candidates (`deleteKeyword`, `delete`,
  `setParent`, ...) without calling anything. Built to settle whether the SDK can delete or move a keyword before
  building `delete-keyword`. Self-certifying after an independent review: `blind` names anything the walk could
  not see (a computed `__index` or hidden metatable at any depth, the depth cap), `knownMissing` lists documented
  methods absent from the listing, and `listingComplete` is true only when both are empty -- read "no such
  method" only from a complete listing; otherwise only the looked-up candidates are conclusive.

### Added
- **`catalog move-keyword <id> --parent-id N | --parent <exact name> | --to-top [--catalog-path P]`** (2026-10-07)
  -- move a keyword inside another keyword or to the top level, keeping its id, photos and child keywords. Uses
  `LrKeyword:setParent`, which `catalog probe-api` found on LrC 15 although Adobe documents no way to move a
  keyword -- so nothing about it is trusted: afterwards the keyword is re-read BY ID, and only the same keyword,
  directly in the target, with the same photo and child counts and no second keyword of its name, counts as
  moved; anything else is an error naming where it really is (`PLACEMENT_MISMATCH`, `MOVE_CHANGED_KEYWORD`,
  `KEYWORD_LOST`, `OPERATION_FAILED` with the read-back). Refuses a target inside the keyword itself
  (`INVALID_MOVE`) or one already holding a keyword of the same name, any capitals (`NAME_EXISTS_IN_TARGET`);
  already there = `moved: false`, no write.
  Verified live 2026-10-07 (Madelyn's catalog, LrC 15, build 2026-10-07f), each step checked in the catalog FILE
  (whole keyword table diffed; only the moved keyword's parent and genealogy and its descendants' genealogy may
  change): a throwaway with a child moved into a nested keyword, then `--to-top` (setParent(nil) = top level,
  parent = the root row -- not detached), then back with one photo tagged (the same photo stayed tagged); then
  `shared:cross-library` moved into `Shared`. Every child's genealogy was rewritten by Lightroom itself.
- **`catalog batch-add-keywords --pairs-file F [--catalog-path P]`** (2026-10-06) -- the mirror of
  `batch-remove-keywords`: add EXISTING keywords, by id, to photos -- up to 200 photo/keyword pairs in one write.
  Never creates a keyword (an id not in the catalog is `keyword_not_found`), unlike `batch-set --keyword`, which
  matches by name and, when the name is missing, creates a keyword with Include on Export off wherever Lightroom
  puts a parentless one. Each pair's status (`added` / `already_on_photo` / `photo_not_found` / `keyword_not_found` /
  `not_added` / `unverified`) comes from reading the photo before and after the write; a photo whose keyword count
  changed by anything else is in `collateralPhotos`. Nested keywords are found by walking the tree.
  `complete` also requires every photo to be found (a tag that was asked for and did not land is never
  "complete"; ids from another catalog would otherwise read as done) -- pass `--catalog-path` anyway.
  `batch-remove-keywords` and `batch-add-keywords` now share one CLI body. Reviewed independently; verified live
  that a photo with no keywords reads back as an empty list (so it can be tagged), via batch-remove on Carolyn's
  catalog (`not_on_photo`, no write).

### Changed
- **`catalog create-keyword` can create a keyword INSIDE a parent: `--parent-id <id>` or `--parent <exact name>`**
  (2026-10-06). Lightroom's `createKeyword` with no parent does not create at the top level — it lands under
  whatever keyword was last selected in the Keyword List; with an explicit parent it places correctly. The command
  now reads back where the keyword actually landed (`parentId`, `parentName`, `placement` in the response) and
  returns `PLACEMENT_MISMATCH` if it is not inside the requested parent. Also `--no-export` (Include on Export off)
  and `--catalog-path` (refuse unless that catalog is open).
- **Stricter:** `create-keyword` refuses (`KEYWORD_EXISTS_ELSEWHERE`) when a keyword with the same name — in any
  capitals — already exists elsewhere in the tree; `--allow-duplicate-name` overrides. If the keyword already
  exists exactly where asked, it is returned with `created: false` and nothing is written. A parent name that
  matches more than one keyword is `PARENT_AMBIGUOUS` (use `--parent-id`); one that exists only in other
  capitals is named in the `PARENT_NOT_FOUND` message. `includeOnExport` in the response is READ from the keyword
  (`includeOnExportRequested` echoes the request); `duplicatesElsewhere` lists same-named keywords elsewhere when the
  keyword already existed. Names containing `,` or `|` (Lightroom's separators) are refused. A write Lightroom
  queues instead of running is reported as such (re-run: the command is idempotent).
- Verified live 2026-10-06 (Carolyn's catalog): `shared:with-ken`, `shared:with-ethan`, `shared:with-madelyn`
  created inside a top-level `Shared` via `--parent Shared`; placement confirmed in the catalog's SQLite; a repeat
  returned `created: false` with no write; `includeOnExport` read back `true` (it needs `LrTasks.pcall` -- plain
  `pcall` around `getAttributes()` read back nothing).

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
