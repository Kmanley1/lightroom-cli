"""lr docs -- generate documentation from the command schema (the single source of truth)."""

from pathlib import Path

import click


def render_reference(schemas: dict) -> str:
    """Render the full CLI/MCP reference markdown from COMMAND_SCHEMAS.

    Deterministic (groups + commands sorted) so regeneration produces a stable diff.
    """
    from mcp_server.tool_registry import sanitize_tool_name

    groups: dict[str, list] = {}
    for schema in schemas.values():
        group = schema.cli_path.split(".")[0]
        groups.setdefault(group, []).append(schema)
    for cmds in groups.values():
        cmds.sort(key=lambda s: s.cli_path)

    lines: list[str] = []
    lines.append("# lr CLI Reference")
    lines.append("")
    lines.append("> Generated from `lightroom_sdk/schema.py` via `lr docs reference`. Do not edit by hand --")
    lines.append("> regenerate after any schema change.")
    lines.append("")
    lines.append(
        f"**{len(schemas)} commands** across {len(groups)} groups. Every command is reachable both as a CLI "
        "verb and as an MCP tool."
    )
    lines.append("")
    lines.append("## Groups")
    lines.append("")
    for group in sorted(groups):
        lines.append(f"- [`{group}`](#{group}) -- {len(groups[group])} commands")
    lines.append("")

    for group in sorted(groups):
        lines.append(f"## {group}")
        lines.append("")
        for s in groups[group]:
            lines.append(f"### `lr {s.cli_path.replace('.', ' ')}`")
            lines.append("")
            if s.description:
                lines.append(s.description)
                lines.append("")
            meta = [
                f"**MCP tool:** `{sanitize_tool_name(s.command)}`",
                f"**bridge:** `{s.command}`",
                f"**risk:** {s.risk_level}",
                f"**timeout:** {s.timeout:g}s",
            ]
            if s.supports_dry_run:
                meta.append("dry-run")
            if s.requires_confirm:
                meta.append("**requires --confirm**")
            lines.append("  -  ".join(meta))
            lines.append("")
            if s.params:
                lines.append("| Param | Type | Required | Default | Notes |")
                lines.append("|---|---|---|---|---|")
                for p in s.params:
                    notes = (p.description or "")
                    if p.enum_values:
                        notes += f" (one of: {', '.join(p.enum_values)})"
                    rng = []
                    if p.min is not None:
                        rng.append(f"min {p.min:g}")
                    if p.max is not None:
                        rng.append(f"max {p.max:g}")
                    if rng:
                        notes += f" [{', '.join(rng)}]"
                    notes = notes.replace("|", "\\|").strip()
                    default = "" if p.default is None else f"`{p.default}`"
                    req = "yes" if p.required else ""
                    lines.append(f"| `{p.name}` | {p.type.value} | {req} | {default} | {notes} |")
                lines.append("")
            else:
                lines.append("_No parameters._")
                lines.append("")
            if s.response_fields:
                lines.append("**Response fields:** " + ", ".join(f"`{f}`" for f in s.response_fields))
                lines.append("")
    return "\n".join(lines) + "\n"


@click.group()
def docs():
    """Documentation generators."""
    pass


@docs.command("reference")
@click.option("--out", "out_path", default=None, help="Output path (default: docs/CLI_REFERENCE.md)")
@click.pass_context
def reference(ctx, out_path):
    """Generate the CLI/MCP reference markdown from the command schema."""
    from lightroom_sdk.schema import get_all_schemas

    schemas = get_all_schemas()
    md = render_reference(schemas)
    if out_path:
        dest = Path(out_path)
    else:
        dest = Path(__file__).resolve().parents[2] / "docs" / "CLI_REFERENCE.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(md, encoding="utf-8")
    click.echo(f"Wrote {dest} ({len(schemas)} commands)")
