"""instructions のテスト。"""


def test_instructions_is_non_empty_string():
    from mcp_server.instructions import INSTRUCTIONS

    assert isinstance(INSTRUCTIONS, str)
    assert len(INSTRUCTIONS) > 100


def test_instructions_contains_ping():
    """接続確認フローが含まれること"""
    from mcp_server.instructions import INSTRUCTIONS

    assert "lr_system_ping" in INSTRUCTIONS


def test_instructions_contains_error_recovery():
    """エラー回復パターンが含まれること"""
    from mcp_server.instructions import INSTRUCTIONS

    assert "CONNECTION_ERROR" in INSTRUCTIONS


def test_instructions_contains_workflow():
    """主要ワークフローが含まれること"""
    from mcp_server.instructions import INSTRUCTIONS

    assert "lr_catalog" in INSTRUCTIONS
    assert "lr_develop" in INSTRUCTIONS


def test_instructions_mentions_lr_prefix():
    """ツール名が lr_ prefix であることが記載されていること"""
    from mcp_server.instructions import INSTRUCTIONS

    assert "lr_" in INSTRUCTIONS


def test_instructions_mentions_dry_run():
    """dry_run の説明が含まれること"""
    from mcp_server.instructions import INSTRUCTIONS

    assert "dry_run" in INSTRUCTIONS


def test_all_referenced_tool_names_are_real():
    """Every concrete `lr_*` tool name in the guide must be a registered MCP tool.

    Guards against drift: the guide previously named CLI-style tools (e.g. lr_catalog_list)
    that don't exist as MCP tools -- the real name derives from the command
    (catalog.getAllPhotos -> lr_catalog_get_all_photos).
    """
    import re

    from lightroom_sdk.schema import COMMAND_SCHEMAS
    from mcp_server.instructions import INSTRUCTIONS
    from mcp_server.tool_registry import sanitize_tool_name

    valid = {sanitize_tool_name(c) for c in COMMAND_SCHEMAS if not c.startswith("plugin.")}
    # Backtick-wrapped names ending in a letter; the `lr_preview_*` wildcard ends in '*' and is skipped.
    referenced = set(re.findall(r"`(lr_[a-z_]+[a-z])`", INSTRUCTIONS))
    missing = sorted(n for n in referenced if n not in valid)
    assert not missing, f"INSTRUCTIONS reference non-existent MCP tools: {missing}"
