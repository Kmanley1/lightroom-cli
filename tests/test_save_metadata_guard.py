"""catalog.saveMetadata refuses to run without photo ids (toolkit-lightroom risk A4, Ken's decision 2026-10-12).

An empty or missing photoIds makes the plugin save whatever Lightroom has selected (CatalogModule.lua), the one
unguarded bulk-save path. The guard sits in validate_params, which both the CLI (after any --json merge) and the
MCP server call before sending, so neither reaches Lightroom without ids -- unless selection=true says so on purpose.
(Python code calling LightroomClient or the bridge directly is not guarded.)
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from cli.main import cli
from lightroom_sdk.validation import ValidationError, validate_params


@pytest.fixture
def runner():
    return CliRunner()


def _bridge(mock_get_bridge):
    b = AsyncMock()
    b.send_command.return_value = {"id": "x", "success": True,
                                   "result": {"total": 1, "succeeded": 1, "failed": 0, "results": []}}
    mock_get_bridge.return_value = b
    return b


@pytest.mark.parametrize("args", [
    ["catalog", "save-metadata"],                                         # no ids
    ["catalog", "save-metadata", "--json", "{}"],                         # --json replaces the parameters
    ["catalog", "save-metadata", "--json", '{"photoIds": []}'],           # an empty list means "selection"
    ["catalog", "save-metadata", "1", "--selection"],                     # ids AND selection: ambiguous
    ["catalog", "save-metadata", "--json", '{"photoIds": ["1"], "selection": true}'],
])
@patch("cli.helpers.get_bridge")
def test_cli_refuses_a_save_without_ids(mock_get_bridge, runner, args):
    b = _bridge(mock_get_bridge)
    result = runner.invoke(cli, args)
    assert result.exit_code == 2, result.output
    assert "photoIds" in result.output or "selection" in result.output
    b.send_command.assert_not_called()


@patch("cli.helpers.get_bridge")
def test_cli_selection_flag_saves_the_selection_on_purpose(mock_get_bridge, runner):
    b = _bridge(mock_get_bridge)
    result = runner.invoke(cli, ["catalog", "save-metadata", "--selection"])
    assert result.exit_code == 0, result.output
    b.send_command.assert_called_once_with("catalog.saveMetadata", {}, timeout=120.0)   # 'selection' never sent


@patch("cli.helpers.get_bridge")
def test_cli_selection_via_json(mock_get_bridge, runner):
    b = _bridge(mock_get_bridge)
    result = runner.invoke(cli, ["catalog", "save-metadata", "--json", '{"selection": true}'])
    assert result.exit_code == 0, result.output
    b.send_command.assert_called_once_with("catalog.saveMetadata", {}, timeout=120.0)


@patch("cli.helpers.get_bridge")
def test_cli_ids_unchanged(mock_get_bridge, runner):
    b = _bridge(mock_get_bridge)
    result = runner.invoke(cli, ["catalog", "save-metadata", "1", "2"])
    assert result.exit_code == 0, result.output
    b.send_command.assert_called_once_with("catalog.saveMetadata", {"photoIds": ["1", "2"]}, timeout=120.0)


def test_validate_params_rules():
    assert validate_params("catalog.saveMetadata", {"photoIds": ["1"]}) == {"photoIds": ["1"]}
    assert validate_params("catalog.saveMetadata", {"selection": True}) == {}
    for bad in ({}, {"photoIds": []}, {"selection": False}, {"photoIds": ["1"], "selection": True}):
        with pytest.raises(ValidationError):
            validate_params("catalog.saveMetadata", bad)


def test_mcp_path_refuses_without_ids():
    from mcp_server.connection import ConnectionManager
    cm = ConnectionManager.__new__(ConnectionManager)
    cm._lock = asyncio.Lock()
    cm._client = None
    cm._get_client = AsyncMock(side_effect=AssertionError("must not reach Lightroom"))
    out = asyncio.run(cm.execute("catalog.saveMetadata", {}, timeout=5, mutating=True))
    assert out.get("isError") and out.get("code") == "VALIDATION_ERROR"


# ---------- refute 2026-10-12: dry-run validates; ids must be real ids; MCP sends the validated params ----------

@pytest.mark.parametrize("bad", [[None], [""], [[]], ["abc"], [0], ["-1"], [1.5]])
def test_ids_must_be_real_ids(bad):
    with pytest.raises(ValidationError):
        validate_params("catalog.saveMetadata", {"photoIds": bad})
    assert validate_params("catalog.saveMetadata", {"photoIds": [7, "12"]}) == {"photoIds": [7, "12"]}


@patch("cli.helpers.get_bridge")
def test_cli_dry_run_is_refused_like_the_real_run(mock_get_bridge, runner):
    b = _bridge(mock_get_bridge)
    result = runner.invoke(cli, ["catalog", "save-metadata", "--dry-run"])
    assert result.exit_code == 2 and "photoIds" in result.output
    result = runner.invoke(cli, ["catalog", "save-metadata", "--selection", "--dry-run"])
    assert result.exit_code == 0 and '"selection"' not in result.output        # previews what would be sent
    b.send_command.assert_not_called()


def test_mcp_dry_run_is_refused_like_the_real_run():
    from lightroom_sdk.schema import get_schema
    from mcp_server.tool_registry import create_tool_function
    fn = create_tool_function(get_schema("catalog.saveMetadata"), connection=object())
    out = asyncio.run(fn(dry_run=True))
    assert out.get("isError") and out.get("code") == "VALIDATION_ERROR"
    ok = asyncio.run(fn(selection=True, dry_run=True))
    assert ok["dry_run"] and ok["params"] == {}


def test_mcp_sends_the_validated_params():
    from mcp_server.connection import ConnectionManager
    cm = ConnectionManager.__new__(ConnectionManager)
    cm._lock = asyncio.Lock()
    client = AsyncMock()
    client.execute_command.return_value = {"ok": True}
    cm._client = client
    cm._get_client = AsyncMock(return_value=client)
    asyncio.run(cm.execute("catalog.saveMetadata", {"selection": True}, timeout=5, mutating=True))
    client.execute_command.assert_called_once_with("catalog.saveMetadata", {}, timeout=5)
