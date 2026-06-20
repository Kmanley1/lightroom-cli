"""Tests for `lr completion` and develop-parameter shell completion."""

import pytest
from click.testing import CliRunner

from cli.commands.completion import complete_develop_param
from cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_completion_command_emits_activation(runner):
    result = runner.invoke(cli, ["completion", "bash"])
    assert result.exit_code == 0
    assert "_LR_COMPLETE=bash_source lr" in result.output


def test_completion_rejects_unknown_shell(runner):
    result = runner.invoke(cli, ["completion", "tcsh"])
    assert result.exit_code != 0


def test_complete_develop_param_prefix():
    assert "Exposure" in complete_develop_param(None, None, "Exp")


def test_complete_develop_param_case_insensitive():
    assert "Exposure" in complete_develop_param(None, None, "exp")


def test_complete_develop_param_empty_returns_many():
    assert len(complete_develop_param(None, None, "")) > 10


def test_complete_develop_param_never_raises():
    # a completion callback must be fail-soft
    assert isinstance(complete_develop_param(None, None, None), list)
