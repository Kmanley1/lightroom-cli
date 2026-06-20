"""Coverage-equivalence + schema<->Lua handler reconciliation (fully offline).

This module is the *bijection* guard across the three surfaces that must stay in lockstep:

    COMMAND_SCHEMAS  (lightroom_sdk/schema.py, the SSOT)
        |  router:register("cmd", ...)        -> the Lua plugin handler table (PluginInit.lua)
        |  sanitize_tool_name(cmd)            -> the MCP tool name (mcp_server/tool_registry.py)
        |  cli_path.replace(".", " ")         -> a leaf in the click tree (cli.main.cli)

It deliberately COMPLEMENTS the existing tests rather than repeating them:

  * tests/test_mcp_connection.py::test_no_advertised_mcp_tool_is_dead already guards the
    *forward* direction "every advertised schema command is SERVICEABLE" (handler OR
    _AI_TOOL_REWRITE OR an explicit MCP-local handler). We do NOT duplicate that union.
    Instead we add the *reverse* direction that nothing else covers: every
    ``router:register("X", ...)`` in PluginInit.lua must have a COMMAND_SCHEMAS entry --
    a handler with no schema is an unreachable/undocumented command (no CLI verb, no MCP
    tool, invisible to ``lr docs reference``).

  * tests/test_mcp_tool_registry.py unit-tests ``sanitize_tool_name`` on a handful of
    examples; here we assert the *whole-corpus* property: the map command -> tool name is
    injective (no two schema commands collide on one MCP tool name).

  * tests/test_mcp_server.py asserts a tool *count*; here we assert exact *set equality*
    between the schemas and what FastMCP actually registers (every non-plugin command is
    registered; nothing extra is).

  * tests/test_docs_reference.py checks the rendered markdown; here we resolve against the
    *live* click command tree and the *live* FastMCP registry, not the doc generator.

ALLOWLISTS below capture genuine, verified inconsistencies in the *current* tree so the
suite stays green while the gap is reported (see this agent's ``violations``). They are not
a license to drift: each entry is specific and commented. If a future change removes a gap,
the corresponding ``test_allowlist_*_still_accurate`` test fails so the allowlist can't rot.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lightroom_sdk.schema import COMMAND_SCHEMAS
from mcp_server.connection import _AI_TOOL_REWRITE
from mcp_server.tool_registry import sanitize_tool_name

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_INIT = REPO_ROOT / "lightroom_sdk" / "plugin" / "PluginInit.lua"
CLI_DIR = REPO_ROOT / "cli"

# --- the non-handler service paths, mirrored from test_mcp_connection.py -------------------
# Schema commands that are intentionally serviced WITHOUT a same-name Lua handler:
#   * develop.ai.* mask verbs are rewritten to a real bridge command (connection._AI_TOOL_REWRITE)
#   * these three are handled locally in ConnectionManager.execute (no bridge round-trip / no handler)
MCP_LOCAL_COMMANDS = {"develop.ai.presets", "system.checkConnection", "system.reconnect"}
SCHEMA_WITHOUT_HANDLER_OK = set(_AI_TOOL_REWRITE) | MCP_LOCAL_COMMANDS


# ==========================================================================================
# ALLOWLISTS -- genuine, verified current-tree inconsistencies (reported in `violations`).
# ==========================================================================================

# Direction B -- Lua handlers (router:register) that have NO COMMAND_SCHEMAS entry.
# Effect: the handler is reachable over the raw TCP bridge but is invisible everywhere a user
# would find it -- no CLI verb, no MCP tool (register_all_tools iterates COMMAND_SCHEMAS), and
# absent from ``lr docs reference``. Either add a schema (to expose it) or drop the registration.
# These are the masking/selection-internal verbs plus preview.getPreviewChunk; verified absent
# from both COMMAND_SCHEMAS and every cli_path on 2026-06-20.
ORPHAN_LUA_HANDLERS_ALLOWLIST = {
    "develop.activateMaskingMode",
    "develop.addToCurrentMask",
    "develop.createAISelectionMask",
    "develop.createComplexMask",
    "develop.createNewMask",
    "develop.deleteMask",
    "develop.deleteMaskTool",
    "develop.getSelectedMaskTool",
    "develop.intersectWithCurrentMask",
    "develop.invertMask",
    "develop.selectMask",
    "develop.selectMaskTool",
    "develop.subtractFromCurrentMask",
    "preview.getPreviewChunk",
}

# CLI-path resolution -- a non-plugin schema command is "CLI-reachable" if its cli_path is a
# click leaf OR its bridge command string is referenced in cli/ source (a consolidated verb or
# a sentinel cli_path that dispatches the real command). This allowlist holds the ONE schema
# command that satisfies NEITHER: its advertised cli_path is not a leaf and no CLI command sends
# it. (It still ships an MCP tool + a Lua handler, so only the CLI surface is dead.)
#   (Resolved 2026-06-20: develop.batchApplySettings now has a `develop batch-apply` CLI verb, so the
#    allowlist is empty -- every non-plugin schema command is CLI-reachable.)
CLI_UNREACHABLE_SCHEMA_ALLOWLIST = set()


# ==========================================================================================
# Helpers -- all read source files as text; nothing here touches a live Lightroom / socket.
# ==========================================================================================

def _lua_registered_commands() -> set[str]:
    """Every command string passed to ``router:register("X", ...)`` in PluginInit.lua."""
    text = PLUGIN_INIT.read_text(encoding="utf-8")
    return set(re.findall(r'router:register\(\s*"([^"]+)"', text))


def _non_plugin_schema_commands() -> set[str]:
    return {c for c in COMMAND_SCHEMAS if not c.startswith("plugin.")}


def _click_command_paths() -> set[str]:
    """Every leaf command path in the live click tree, e.g. ``"catalog set-rating"``.

    Mirrors the recursive collector in tests/test_cli_help_all_commands.py so the notion of
    "a resolvable CLI path" is exactly the one the help suite already exercises.
    """
    from cli.main import cli

    def _collect(group, prefix: str = "") -> list[str]:
        out: list[str] = []
        for name in group.list_commands(None):
            cmd = group.get_command(None, name)
            full = f"{prefix} {name}".strip() if prefix else name
            if hasattr(cmd, "list_commands"):
                out.extend(_collect(cmd, full))
            else:
                out.append(full)
        return out

    return set(_collect(cli))


def _commands_referenced_in_cli_source() -> set[str]:
    """Bridge command strings (``"group.verb"``) that appear literally in cli/ source.

    Covers consolidated CLI verbs (one leaf dispatches several per-arg bridge commands, e.g.
    ``selection toggle-label --color red`` -> selection.toggleRedLabel) and sentinel cli_paths
    (e.g. develop.ai._bridge), where the cli_path itself is not a click leaf but the command is
    genuinely reachable from the CLI.
    """
    src = "\n".join(p.read_text(encoding="utf-8") for p in CLI_DIR.rglob("*.py"))
    return set(re.findall(r'"((?:catalog|develop|selection|preview|system)\.[A-Za-z]+)"', src))


# ==========================================================================================
# Direction A (reverse-framing sanity): every schema command IS registered or serviced.
# Forward serviceability is owned by test_mcp_connection.py; here we assert the narrower
# "same-name Lua handler" property for everything outside the documented local/rewrite set,
# which keeps the two directions symmetric and localises a missing-handler regression here.
# ==========================================================================================

def test_every_non_plugin_schema_command_has_a_handler_or_is_serviced_locally():
    handlers = _lua_registered_commands()
    advertised = _non_plugin_schema_commands()
    needing_handler = advertised - SCHEMA_WITHOUT_HANDLER_OK
    dead = sorted(needing_handler - handlers)
    assert not dead, (
        "Schema commands advertised with neither a router:register handler nor a documented "
        f"local/rewrite service path (advertised-but-dead): {dead}"
    )


# ==========================================================================================
# Direction B (the gap nothing else covers): every Lua handler has a schema.
# ==========================================================================================

def test_every_lua_handler_has_a_schema_entry():
    handlers = _lua_registered_commands()
    schema_cmds = set(COMMAND_SCHEMAS)  # plugin.* included: a handler may legitimately back one
    orphans = sorted(handlers - schema_cmds - ORPHAN_LUA_HANDLERS_ALLOWLIST)
    assert not orphans, (
        "router:register() handlers with no COMMAND_SCHEMAS entry "
        "(unreachable via CLI/MCP, undocumented): " + ", ".join(orphans)
    )


def test_allowlist_orphan_handlers_still_accurate():
    """Every allowlisted orphan must still be registered-in-Lua AND still schema-less.

    Guards against allowlist rot: if a schema is later added (or the registration removed) the
    entry is stale and must be pruned -- this fails so it can't silently mask a re-introduced gap.
    """
    handlers = _lua_registered_commands()
    schema_cmds = set(COMMAND_SCHEMAS)
    for cmd in sorted(ORPHAN_LUA_HANDLERS_ALLOWLIST):
        assert cmd in handlers, f"Allowlisted orphan '{cmd}' is no longer router:register'd -- prune it."
        assert cmd not in schema_cmds, (
            f"Allowlisted orphan '{cmd}' now HAS a schema -- the gap is fixed; prune the allowlist."
        )


# ==========================================================================================
# MCP tool-name bijection: command -> sanitize_tool_name is injective (no collisions).
# ==========================================================================================

def test_sanitize_tool_name_is_collision_free_across_all_schema_commands():
    by_tool: dict[str, list[str]] = {}
    for command in COMMAND_SCHEMAS:
        if command.startswith("plugin."):
            continue  # plugin.* are intentionally not exposed as MCP tools
        by_tool.setdefault(sanitize_tool_name(command), []).append(command)
    collisions = {tool: cmds for tool, cmds in by_tool.items() if len(cmds) > 1}
    assert not collisions, f"sanitize_tool_name collisions (distinct commands -> same MCP tool): {collisions}"


def test_sanitized_tool_names_are_valid_identifiers():
    """Each MCP tool name must be a clean snake_case identifier (no dots/spaces/dunders)."""
    bad = []
    for command in COMMAND_SCHEMAS:
        if command.startswith("plugin."):
            continue
        name = sanitize_tool_name(command)
        if not name.startswith("lr_") or not name.replace("_", "a").isalnum() or "__" in name:
            bad.append((command, name))
    assert not bad, f"Malformed MCP tool names: {bad}"


# ==========================================================================================
# CLI reachability: every non-plugin schema command resolves to a CLI surface.
# ==========================================================================================

def test_every_non_plugin_schema_command_is_cli_reachable():
    click_paths = _click_command_paths()
    referenced = _commands_referenced_in_cli_source()
    unreachable = []
    for command, schema in COMMAND_SCHEMAS.items():
        if command.startswith("plugin."):
            continue
        if command in CLI_UNREACHABLE_SCHEMA_ALLOWLIST:
            continue
        leaf = schema.cli_path.replace(".", " ")
        # Reachable if the cli_path is a real click leaf OR the bridge command string is
        # dispatched somewhere in cli/ (consolidated verb / sentinel cli_path).
        if leaf not in click_paths and command not in referenced:
            unreachable.append((command, schema.cli_path))
    assert not unreachable, (
        "Non-plugin schema commands with no resolvable CLI path "
        "(cli_path is not a click leaf and the command is dispatched by no CLI verb): "
        f"{unreachable}"
    )


def test_allowlist_cli_unreachable_still_accurate():
    """Each CLI-unreachable allowlist entry must still be genuinely unreachable from the CLI."""
    click_paths = _click_command_paths()
    referenced = _commands_referenced_in_cli_source()
    for command in sorted(CLI_UNREACHABLE_SCHEMA_ALLOWLIST):
        schema = COMMAND_SCHEMAS.get(command)
        assert schema is not None, f"Allowlisted '{command}' no longer exists in COMMAND_SCHEMAS -- prune it."
        leaf = schema.cli_path.replace(".", " ")
        assert leaf not in click_paths and command not in referenced, (
            f"Allowlisted CLI-unreachable '{command}' is now reachable "
            f"(leaf='{leaf}') -- the gap is fixed; prune the allowlist."
        )


# ==========================================================================================
# Registry truth: FastMCP registers exactly the non-plugin schema commands (set equality).
# Skipped if fastmcp is absent so a minimal CI image never blocks. Distinct from
# test_mcp_server.py, which only checks a count -- this asserts the exact name set.
# ==========================================================================================

def test_fastmcp_registers_exactly_the_non_plugin_schema_commands():
    fastmcp = pytest.importorskip("fastmcp")
    import asyncio
    import tempfile

    from mcp_server.connection import ConnectionManager
    from mcp_server.tool_registry import register_all_tools

    server = fastmcp.FastMCP(name="lightroom-cli-equivalence-test")
    # Registration is purely structural -- no bridge connection is opened, so a bogus port
    # file is fine and keeps this fully offline.
    connection = ConnectionManager(port_file=str(Path(tempfile.gettempdir()) / "nonexistent_equiv_port.txt"))
    count = register_all_tools(server, connection)

    async def _names() -> set[str]:
        tools = await server.list_tools()
        return {t.name for t in tools}

    registered = asyncio.run(_names())
    expected = {sanitize_tool_name(c) for c in COMMAND_SCHEMAS if not c.startswith("plugin.")}

    assert count == len(expected), f"register_all_tools returned {count}, expected {len(expected)}"
    assert registered == expected, (
        "FastMCP registry diverges from COMMAND_SCHEMAS. "
        f"Missing (schema but not registered): {sorted(expected - registered)}; "
        f"Extra (registered but not schema): {sorted(registered - expected)}"
    )


def test_no_plugin_command_is_exposed_as_an_mcp_tool():
    """plugin.* are local CLI verbs; they must never leak into the MCP registry."""
    fastmcp = pytest.importorskip("fastmcp")
    import asyncio
    import tempfile

    from mcp_server.connection import ConnectionManager
    from mcp_server.tool_registry import register_all_tools

    server = fastmcp.FastMCP(name="lightroom-cli-equivalence-plugin-test")
    connection = ConnectionManager(port_file=str(Path(tempfile.gettempdir()) / "nonexistent_equiv_plugin_port.txt"))
    register_all_tools(server, connection)

    async def _names() -> set[str]:
        tools = await server.list_tools()
        return {t.name for t in tools}

    registered = asyncio.run(_names())
    plugin_tool_names = {sanitize_tool_name(c) for c in COMMAND_SCHEMAS if c.startswith("plugin.")}
    leaked = sorted(plugin_tool_names & registered)
    assert not leaked, f"plugin.* commands leaked into the MCP tool registry: {leaked}"
