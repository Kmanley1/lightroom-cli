"""Tests for the `lr docs reference` generator."""

from cli.commands.docs import render_reference
from lightroom_sdk.schema import get_all_schemas
from mcp_server.tool_registry import sanitize_tool_name


def test_reference_covers_every_command():
    schemas = get_all_schemas()
    md = render_reference(schemas)
    assert md.startswith("# lr CLI Reference")
    for s in schemas.values():
        # every command surfaces both its MCP tool name and its CLI verb
        assert sanitize_tool_name(s.command) in md, f"missing MCP tool for {s.command}"
        assert f"lr {s.cli_path.replace('.', ' ')}" in md, f"missing CLI verb for {s.cli_path}"


def test_reference_lists_every_param():
    schemas = get_all_schemas()
    md = render_reference(schemas)
    for s in schemas.values():
        for p in s.params:
            assert f"`{p.name}`" in md, f"missing param {s.command}.{p.name}"


def test_reference_is_deterministic():
    schemas = get_all_schemas()
    assert render_reference(schemas) == render_reference(schemas)


def test_reference_includes_new_features():
    # the export + collection-populate commands shipped this cycle must be documented
    md = render_reference(get_all_schemas())
    assert "lr_catalog_export_photos" in md
    assert "lr_catalog_add_photos_to_collection" in md
    assert "lr_catalog_remove_photos_from_collection" in md
