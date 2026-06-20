"""CLI -> schema -> Lua PARAM-KEY contract (the #136 / #147 bug class).

A single command's parameters cross three independent layers:

    CLI command module  ->  COMMAND_SCHEMAS (validate_params)  ->  Lua handler (params.<name>)

If a param *key* differs across those layers, nothing fails at import or build time --
it is a silent *runtime* failure:

  * #136 class -- the CLI builds a params dict using a key the schema does not declare.
    ``execute_command`` runs ``validate_params`` before sending, so the extra key is
    rejected with exit code 2 and the bridge is never called. The user sees
    "unknown parameter" for a flag the CLI itself produced.

  * #147 class -- the schema declares a *required* param, but the Lua handler reads a
    different key (e.g. ``params.photo_id`` vs the schema's ``photoId``). Validation
    passes, the command is sent, and the handler silently sees ``nil`` for the value
    the user supplied.

This module pins all three edges *offline* -- no live Lightroom:

  1. Schema hygiene -- every ParamSchema.name is camelCase and unique within its command
     (a non-camelCase or duplicated key is the seed of a cross-layer mismatch).
  2. schema <-> Lua -- parse ``router:register("cmd", Module.fn, ...)`` out of
     PluginInit.lua, then statically assert every *required* schema param is read as
     ``params.<name>`` somewhere in that handler's Module .lua (the #147 class).
  3. CLI -> schema -- drive a representative set of CLI commands through click's
     CliRunner with a mocked bridge; assert the command exits 0 and every key actually
     sent to ``send_command`` is a declared schema param for that command (the #136
     class -- a stray key would have been rejected by ``validate_params`` first).

Complements (does NOT duplicate):
  * test_param_schema_min_max.py  -- only min/max on a few params.
  * test_schema_plugin.py         -- only plugin.* registration/fields.
  * test_mcp_tool_registry.py     -- MCP Field() construction, not the Lua/CLI edges.
  * test_mcp_cli_equivalence.py   -- validate_params semantics, not per-command keys.
  * test_plugin_lua_unit.py       -- JSON-escape / socket flags, not param-key wiring.
  * integration/test_cli_*.py     -- each asserts ONE command's exact dict; this asserts
                                     the *contract* (every sent key is schema-valid) across
                                     a representative spread, and would catch a new command
                                     that ships a key the schema never declared.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from cli.main import cli
from lightroom_sdk.schema import COMMAND_SCHEMAS, get_schema

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "lightroom_sdk" / "plugin"
PLUGIN_INIT = PLUGIN_DIR / "PluginInit.lua"

# ---------------------------------------------------------------------------
# Verified-violation allowlist.
#
# If a check below surfaces a GENUINE cross-layer mismatch in non-test code, do NOT
# weaken the assertion -- record the exact case here (so the suite stays green) and
# report it verbatim. As of this writing every check passes with an EMPTY allowlist,
# i.e. the #136/#147 contract currently holds and these tests are regression guards.
# ---------------------------------------------------------------------------

# (command, paramName) pairs where the Lua handler legitimately never reads a *required*
# schema param via params.<name> (e.g. consumed only through a dynamic dispatch we cannot
# statically follow). Keep empty unless a real, verified case is found.
ALLOWLIST_SCHEMA_LUA_UNREAD_REQUIRED: set[tuple[str, str]] = set()

# camelCase: first char lower, then letters/digits. Covers single-letter names (x, y).
_CAMEL_CASE = re.compile(r"^[a-z][a-zA-Z0-9]*$")


# ---------------------------------------------------------------------------
# Helpers -- static parse of the Lua plugin (text analysis, no Lua execution)
# ---------------------------------------------------------------------------

# router:register("cmd.name", ModuleVar.fnName, ...)  -- only the Module.fn form (the
# system.* handlers are inline closures and have no schema params, so they're irrelevant).
_REGISTER_RE = re.compile(
    r'router:register\(\s*"([^"]+)"\s*,\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)'
)


def _parse_router_registrations() -> dict[str, tuple[str, str]]:
    """Map ``command -> (ModuleVar, fnName)`` from every router:register(...) in PluginInit.lua."""
    src = PLUGIN_INIT.read_text(encoding="utf-8")
    reg: dict[str, tuple[str, str]] = {}
    for m in _REGISTER_RE.finditer(src):
        reg[m.group(1)] = (m.group(2), m.group(3))
    return reg


def _module_source(module_var: str) -> str | None:
    """Source text of a plugin module given its require/var name (CatalogModule -> CatalogModule.lua)."""
    f = PLUGIN_DIR / f"{module_var}.lua"
    return f.read_text(encoding="utf-8") if f.exists() else None


def _reads_param(src: str, name: str) -> bool:
    """True if the module source reads ``params.<name>`` or ``params["name"]`` / ``params['name']``.

    Scans the WHOLE module (not a single function body) on purpose: handlers routinely
    delegate to private helpers in the same file -- e.g. addPhotosToCollection ->
    _mutateCollectionMembership reads params.photoIds. A function-body-only grep would
    raise false positives on those. A required key read by NO function in the entire
    module is the real #147 signal.
    """
    pat = re.compile(
        r"params\.%s\b|params\[\s*[\"']%s[\"']\s*\]" % (re.escape(name), re.escape(name))
    )
    return bool(pat.search(src))


# Build the registration map once at import.
_ROUTER_REG = _parse_router_registrations()

# Schema commands that have a registered Lua handler AND at least one required param.
_SCHEMA_LUA_REQUIRED_CASES: list[tuple[str, str, str]] = []  # (command, paramName, moduleVar)
for _cmd, _schema in COMMAND_SCHEMAS.items():
    if _cmd.startswith("plugin."):  # local-only, no bridge handler
        continue
    if _cmd not in _ROUTER_REG:
        continue
    _modvar = _ROUTER_REG[_cmd][0]
    for _p in _schema.params:
        if _p.required:
            _SCHEMA_LUA_REQUIRED_CASES.append((_cmd, _p.name, _modvar))


# ---------------------------------------------------------------------------
# 1. Schema hygiene -- camelCase + uniqueness for EVERY ParamSchema
# ---------------------------------------------------------------------------


class TestSchemaParamNameHygiene:
    """Every schema param key must be camelCase and unique within its command."""

    @pytest.mark.parametrize("command", sorted(COMMAND_SCHEMAS.keys()))
    def test_param_names_are_camel_case(self, command):
        schema = COMMAND_SCHEMAS[command]
        offenders = [p.name for p in schema.params if not _CAMEL_CASE.match(p.name)]
        assert offenders == [], (
            f"{command}: non-camelCase param name(s) {offenders}. A snake_case or "
            f"PascalCase key here is the typical seed of a CLI<->schema<->Lua mismatch."
        )

    @pytest.mark.parametrize("command", sorted(COMMAND_SCHEMAS.keys()))
    def test_param_names_unique_within_command(self, command):
        names = [p.name for p in COMMAND_SCHEMAS[command].params]
        dupes = sorted({n for n in names if names.count(n) > 1})
        assert dupes == [], f"{command}: duplicate param name(s) {dupes}"

    def test_no_param_name_is_bridge_internal(self):
        """Schema must not expose bridge-internal keys (``_requestId``/``_command``/``_stream``).

        Those underscore keys are injected by the bridge, not user params; declaring one
        as a schema param would let it leak into validate_params/CLI surface.
        """
        leaked = []
        for cmd, schema in COMMAND_SCHEMAS.items():
            for p in schema.params:
                if p.name.startswith("_"):
                    leaked.append((cmd, p.name))
        assert leaked == [], f"schema exposes bridge-internal param keys: {leaked}"


# ---------------------------------------------------------------------------
# 2. schema <-> Lua -- required params must be read by the registered handler
# ---------------------------------------------------------------------------


class TestSchemaToLuaRequiredParams:
    """For each schema command with a registered Lua handler, every REQUIRED param must
    be read as ``params.<name>`` somewhere in that handler's module (the #147 class)."""

    def test_router_registrations_were_parsed(self):
        """Sanity: the static parse found the registration table (guards a refactor that
        renames router:register or moves it out of PluginInit.lua, which would silently
        empty every case list below and make this whole class vacuously pass)."""
        assert PLUGIN_INIT.exists(), f"missing {PLUGIN_INIT}"
        assert len(_ROUTER_REG) > 100, (
            f"expected >100 router:register(...) Module.fn entries, found {len(_ROUTER_REG)}. "
            f"Did the registration syntax change?"
        )
        # A few well-known commands must be present and point at the expected module.
        assert _ROUTER_REG.get("catalog.setRating") == ("CatalogModule", "setRating")
        assert _ROUTER_REG.get("develop.setValue") == ("DevelopModule", "setValue")
        assert _ROUTER_REG.get("selection.setRating") == ("SelectionModule", "setRating")

    def test_has_required_param_cases_to_check(self):
        """Guard against the suite silently checking nothing."""
        assert len(_SCHEMA_LUA_REQUIRED_CASES) > 20, (
            f"only {len(_SCHEMA_LUA_REQUIRED_CASES)} schema/Lua required-param cases discovered; "
            f"expected many. Registration parse or schema may have regressed."
        )

    @pytest.mark.parametrize(
        "command,param,module_var",
        _SCHEMA_LUA_REQUIRED_CASES,
        ids=[f"{c}:{p}" for c, p, _ in _SCHEMA_LUA_REQUIRED_CASES],
    )
    def test_required_param_read_in_handler_module(self, command, param, module_var):
        if (command, param) in ALLOWLIST_SCHEMA_LUA_UNREAD_REQUIRED:
            pytest.skip(f"allowlisted verified violation: {command}.{param}")
        src = _module_source(module_var)
        assert src is not None, f"{command}: handler module {module_var}.lua not found"
        assert _reads_param(src, param), (
            f"#147 contract: schema '{command}' declares REQUIRED param '{param}', but "
            f"{module_var}.lua never reads params.{param} (nor params[\"{param}\"]). The "
            f"handler will see nil for a value the user supplied."
        )


# ---------------------------------------------------------------------------
# 3. CLI -> schema -- every key the CLI sends is a declared schema param
# ---------------------------------------------------------------------------

# Representative CLI invocations chosen to exercise NON-trivial param mapping -- the
# places most likely to drift: key remaps (search query->criteria, set-flag pick->1),
# SCALAR coercion (develop set / set-metadata), multi-arg arrays, the AI bridge alias,
# and conditional/optional keys (develop apply --photo-id, create-collection --parent).
# Each entry: (argv, expected_command). The test asserts exit 0 AND every sent key is a
# valid schema param for `expected_command`.
_CLI_CASES: list[tuple[list[str], str]] = [
    (["catalog", "get-selected"], "catalog.getSelectedPhotos"),
    (["catalog", "list", "--limit", "10", "--offset", "5"], "catalog.getAllPhotos"),
    (["catalog", "search", "sunset", "--limit", "3"], "catalog.searchPhotos"),
    (["catalog", "get-info", "123"], "catalog.getPhotoMetadata"),
    (["catalog", "set-rating", "123", "4"], "catalog.setRating"),
    (["catalog", "add-keywords", "123", "landscape", "sunset"], "catalog.addKeywords"),
    (["catalog", "set-flag", "123", "pick"], "catalog.setFlag"),
    (["catalog", "set-metadata", "123", "rating", "5"], "catalog.setMetadata"),
    (["catalog", "set-title", "123", "My Title"], "catalog.setTitle"),
    (["catalog", "set-caption", "123", "A caption"], "catalog.setCaption"),
    (["catalog", "set-color-label", "123", "red"], "catalog.setColorLabel"),
    (["catalog", "add-to-collection", "42", "1", "2"], "catalog.addPhotosToCollection"),
    (["catalog", "remove-from-collection", "42", "7"], "catalog.removePhotosFromCollection"),
    (["catalog", "create-collection", "Trip 2026"], "catalog.createCollection"),
    (["catalog", "create-collection", "Japan", "--parent", "3"], "catalog.createCollection"),
    (["catalog", "create-keyword", "birds"], "catalog.createKeyword"),
    (["catalog", "remove-keyword", "123", "birds"], "catalog.removeKeyword"),
    (["catalog", "collection-photos", "42", "--limit", "10"], "catalog.getCollectionPhotos"),
    (["catalog", "find-by-path", "C:\\photos\\a.jpg"], "catalog.findPhotoByPath"),
    # develop -- key remaps + SCALAR coercion + tool enum
    (["develop", "set", "Exposure", "0.5"], "develop.setValue"),
    (["develop", "get", "Contrast"], "develop.getValue"),
    (["develop", "apply", "--settings", '{"Exposure": 0.5}'], "develop.applySettings"),
    (["develop", "apply", "--settings", '{"Exposure": 0.5}', "--photo-id", "9"], "develop.applySettings"),
    (["develop", "tool", "crop"], "develop.selectTool"),
    (["develop", "range", "Exposure"], "develop.getRange"),
    (["develop", "reset-param", "Exposure"], "develop.resetToDefault"),
    (["develop", "snapshot", "Snap A"], "catalog.createDevelopSnapshot"),
    (["develop", "preset", "Vivid"], "catalog.applyDevelopPreset"),
    (["develop", "set-process-version", "6.7"], "develop.setProcessVersion"),
    (["develop", "curve", "s-curve", "--channel", "RGB"], "develop.setCurveSCurve"),
    # AI mask -- the bridge-alias command name + selectionType key
    (["develop", "ai", "subject"], "develop.createAIMaskWithAdjustments"),
    (["develop", "ai", "people", "--part", "eyes"], "develop.createAIMaskWithAdjustments"),
    (["develop", "ai", "batch", "subject", "--photos", "1,2"], "develop.batchAIMask"),
    # selection
    (["selection", "set-rating", "4"], "selection.setRating"),
    (["selection", "color-label", "blue"], "selection.setColorLabel"),
    (["selection", "extend", "--direction", "left", "--amount", "2"], "selection.extendSelection"),
    (["selection", "flag"], "selection.flagAsPick"),
    # preview
    (["preview", "generate-current", "123"], "preview.generatePreview"),
    # export (catalog.exportPhotos via export group)
    (["export", "files", "--dest", "C:\\out", "--format", "JPEG", "--quality", "80"], "catalog.exportPhotos"),
]


class TestCliToSchemaParamContract:
    """Every key a CLI command sends to the bridge must be a declared schema param.

    ``execute_command`` runs ``validate_params`` *before* ``send_command``; a key the
    schema doesn't declare is rejected (exit 2) and ``send_command`` is never reached.
    So asserting exit 0 + "send_command was called + all sent keys are schema params"
    is a genuine CLI->schema contract gate (the #136 class).
    """

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def _run(self, runner, argv):
        """Invoke `argv` with a mocked bridge; return (result, sent_command, sent_params)."""
        mock_bridge = AsyncMock()
        mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {}}
        with patch("cli.helpers.get_bridge", return_value=mock_bridge):
            result = runner.invoke(cli, argv)
        if mock_bridge.send_command.call_args is None:
            return result, None, None
        args, kwargs = mock_bridge.send_command.call_args
        sent_command = args[0] if args else kwargs.get("command")
        sent_params = args[1] if len(args) > 1 else kwargs.get("params", {})
        return result, sent_command, sent_params

    def test_cli_case_coverage_is_meaningful(self):
        """Guard: representative set spans every CLI group and a healthy count."""
        assert len(_CLI_CASES) >= 30
        groups = {argv[0] for argv, _ in _CLI_CASES}
        assert {"catalog", "develop", "selection", "preview", "export"} <= groups

    @pytest.mark.parametrize(
        "argv,expected_command",
        _CLI_CASES,
        ids=[" ".join(a) for a, _ in _CLI_CASES],
    )
    def test_sent_keys_are_valid_schema_params(self, runner, argv, expected_command):
        result, sent_command, sent_params = self._run(runner, argv)

        # exit 0: if validate_params had rejected a CLI-produced key, exit would be 2.
        assert result.exit_code == 0, (
            f"`lr {' '.join(argv)}` exited {result.exit_code} (expected 0). "
            f"Output: {result.output!r}"
        )
        assert sent_command == expected_command, (
            f"`lr {' '.join(argv)}` sent command {sent_command!r}, expected {expected_command!r}"
        )

        schema = get_schema(expected_command)
        assert schema is not None, f"no schema registered for {expected_command}"
        valid = {p.name for p in schema.params}
        sent_keys = set(sent_params.keys())
        unknown = sent_keys - valid
        assert unknown == set(), (
            f"#136 contract: `lr {' '.join(argv)}` sent key(s) {sorted(unknown)} that are "
            f"not declared params of schema '{expected_command}' (valid: {sorted(valid)}). "
            f"validate_params would reject these against a real bridge."
        )

    @pytest.mark.parametrize(
        "argv,expected_command",
        _CLI_CASES,
        ids=[" ".join(a) for a, _ in _CLI_CASES],
    )
    def test_required_schema_params_are_supplied(self, runner, argv, expected_command):
        """Beyond 'no stray keys', a successful invocation must also supply every required
        schema param (except those the schema marks required=False because Lightroom -- not
        the CLI -- supplies them, e.g. applySettings.photoId)."""
        result, sent_command, sent_params = self._run(runner, argv)
        assert result.exit_code == 0, f"`lr {' '.join(argv)}` exited {result.exit_code}: {result.output!r}"

        schema = get_schema(expected_command)
        required = {p.name for p in schema.params if p.required}
        sent_keys = set(sent_params.keys())
        # The CLI may legitimately omit an OPTIONAL key; it must never omit a REQUIRED one.
        missing = required - sent_keys
        assert missing == set(), (
            f"`lr {' '.join(argv)}` omitted required schema param(s) {sorted(missing)} for "
            f"'{expected_command}'. send_command got keys {sorted(sent_keys)}."
        )
