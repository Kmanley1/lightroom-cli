"""lr completion -- shell-completion activation + develop-parameter name completion."""

import click

_ACTIVATION = {
    "bash": 'eval "$(_LR_COMPLETE=bash_source lr)"',
    "zsh": 'eval "$(_LR_COMPLETE=zsh_source lr)"',
    "fish": "_LR_COMPLETE=fish_source lr | source",
}


def complete_develop_param(ctx, param, incomplete):
    """Shell-completion callback: complete Lightroom develop parameter names.

    Sourced from DEVELOP_PARAMETER_RANGES (the develop param catalog), so it stays in
    sync with the supported parameters. Imported lazily and fail-soft -- a completion
    callback must never raise.
    """
    try:
        from lightroom_sdk.types.develop import DEVELOP_PARAMETER_RANGES
    except Exception:
        return []
    inc = (incomplete or "").lower()
    return [name for name in DEVELOP_PARAMETER_RANGES if name.lower().startswith(inc)]


@click.command("completion")
@click.argument("shell", type=click.Choice(sorted(_ACTIVATION)))
def completion(shell):
    """Print the shell-completion activation snippet for SHELL (bash, zsh, fish).

    Add the printed line to your shell startup file, e.g.:

      lr completion bash >> ~/.bashrc
      lr completion zsh  >> ~/.zshrc
      lr completion fish >> ~/.config/fish/config.fish

    Once activated, click completes commands/options automatically, and develop
    parameter names complete for `lr develop set/get/range/reset-param`.
    """
    click.echo(_ACTIVATION[shell])
