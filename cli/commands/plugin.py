"""lr plugin — Lightroom プラグインの管理コマンド"""

import shutil

import click

from cli.output import OutputFormatter
from lightroom_sdk.paths import (
    PLUGIN_NAME,
    get_lightroom_modules_dir,
    get_plugin_source_dir,
)


def _emit(ctx, text_msg: str, data: dict) -> None:
    """Echo human text in text mode, structured JSON when -o json is set (honors --output)."""
    fmt = ctx.obj.get("output", "text") if ctx.obj else "text"
    if fmt == "json":
        click.echo(OutputFormatter.format(data, "json"))
    else:
        click.echo(text_msg)


@click.group()
def plugin():
    """Manage Lightroom plugin installation."""
    pass


@plugin.command()
@click.option("--dev", is_flag=True, help="Use symlink instead of copy (development mode)")
@click.option("--quiet", "-q", is_flag=True, help="Suppress output")
@click.pass_context
def install(ctx, dev, quiet):
    """Install the Lightroom plugin."""
    source = get_plugin_source_dir()
    dest_dir = get_lightroom_modules_dir()
    dest = dest_dir / PLUGIN_NAME

    if not source.exists():
        fmt = ctx.obj.get("output", "text") if ctx.obj else "text"
        click.echo(
            OutputFormatter.format_error(f"Plugin source not found at {source}", fmt, code="SOURCE_NOT_FOUND"),
            err=True,
        )
        raise SystemExit(1)

    dest_dir.mkdir(parents=True, exist_ok=True)

    if dest.exists() or dest.is_symlink():
        if dest.is_symlink():
            dest.unlink()
        else:
            shutil.rmtree(dest)

    if dev:
        try:
            dest.symlink_to(source)
        except OSError:
            # Windows で symlink 権限がない場合は copytree にフォールバック
            click.echo("Warning: Symlink creation failed. Falling back to copy.", err=True)
            shutil.copytree(source, dest)
            if not quiet:
                _emit(
                    ctx,
                    f"Plugin installed (copy fallback) to {dest}",
                    {"status": "installed", "mode": "copy", "fallback": True, "path": str(dest)},
                )
        else:
            if not quiet:
                _emit(
                    ctx,
                    f"Plugin symlinked: {dest} -> {source}",
                    {"status": "installed", "mode": "symlink", "path": str(dest), "source": str(source)},
                )
    else:
        shutil.copytree(source, dest)
        if not quiet:
            _emit(ctx, f"Plugin installed to {dest}", {"status": "installed", "mode": "copy", "path": str(dest)})


@plugin.command()
@click.option("--quiet", "-q", is_flag=True, help="Suppress output")
@click.pass_context
def uninstall(ctx, quiet):
    """Uninstall the Lightroom plugin."""
    dest = get_lightroom_modules_dir() / PLUGIN_NAME

    if not dest.exists() and not dest.is_symlink():
        if not quiet:
            _emit(ctx, "Plugin is not installed.", {"status": "not installed"})
        return

    if dest.is_symlink():
        dest.unlink()
    else:
        shutil.rmtree(dest)

    if not quiet:
        _emit(ctx, "Plugin uninstalled.", {"status": "uninstalled"})


@plugin.command()
@click.pass_context
def status(ctx):
    """Show plugin installation status."""
    dest = get_lightroom_modules_dir() / PLUGIN_NAME
    source = get_plugin_source_dir()

    if dest.is_symlink():
        target = dest.resolve()
        data = {
            "status": "installed",
            "mode": "symlink",
            "source": str(source),
            "installTarget": str(dest),
            "target": str(target),
        }
        text = f"Plugin source:  {source}\nInstall target: {dest}\nStatus:         Installed (symlink -> {target})"
    elif dest.exists():
        data = {"status": "installed", "mode": "copy", "source": str(source), "installTarget": str(dest)}
        text = f"Plugin source:  {source}\nInstall target: {dest}\nStatus:         Installed (copy)"
    else:
        data = {"status": "not installed", "source": str(source), "installTarget": str(dest)}
        text = f"Plugin source:  {source}\nInstall target: {dest}\nStatus:         Not installed"

    _emit(ctx, text, data)
