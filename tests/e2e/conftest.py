# tests/e2e/conftest.py
"""E2E test fixtures and configuration.

The tests write into whatever photo they pick, so they run only when Lightroom has a throwaway catalog open, the
one LR_E2E_CATALOG names. With any other catalog open, or none named, every e2e test skips. --e2e-catalog does the
same, but only when tests/e2e is on the command line (pytest parses this file's options only then).

Run: LR_E2E_CATALOG=/path/to/Test.lrcat pytest tests/e2e/ -v -m e2e
Run destructive: LR_E2E_CATALOG=/path/to/Test.lrcat pytest tests/e2e/ -v -m e2e --run-destructive
"""

import json
import os
import warnings
from dataclasses import dataclass, field
from typing import Any

import pytest
from click.testing import CliRunner

from lightroom_sdk.paths import get_port_file

# --- State container shared across entire session ---


@dataclass
class E2EState:
    """Mutable state shared across all E2E test phases.

    Populated by early phases, consumed by later ones.
    """

    photo_id: str | None = None
    photo_ids: list[str] = field(default_factory=list)
    original_rating: int | None = None
    original_flag: str | None = None
    original_color_label: str | None = None
    original_title: str | None = None
    original_caption: str | None = None
    original_develop_settings: dict[str, Any] | None = None
    created_collection_name: str | None = None
    created_keyword: str | None = None
    created_snapshot_name: str | None = None
    created_mask_id: str | None = None


_state = E2EState()


# --- CLI Command Options ---


def pytest_addoption(parser):
    parser.addoption(
        "--run-destructive",
        action="store_true",
        default=False,
        help="Run destructive E2E tests",
    )
    parser.addoption(
        "--e2e-catalog",
        default=os.environ.get("LR_E2E_CATALOG"),
        help="The throwaway .lrcat the E2E tests may write to; they skip unless Lightroom has it open "
        "(default: $LR_E2E_CATALOG)",
    )


# --- Skip Logic ---


def _lightroom_reachable() -> bool:
    """Check if Lightroom is actually reachable by attempting TCP connections to both ports."""
    import socket

    port_file = get_port_file()
    if not port_file.exists():
        return False
    try:
        ports = port_file.read_text().strip().split(",")
        if len(ports) < 2:
            return False
        for port_str in ports:
            sock = socket.create_connection(("127.0.0.1", int(port_str)), timeout=2)
            sock.close()
        return True
    except (OSError, ValueError, IndexError):
        return False


# The catalog guard (2026-10-20). In June these tests ran against the live Photos catalog and left "E2E Test Title"
# and snapshot e2e_test_snap in a family photo. The plugin has no read command that returns the open catalog's path;
# batch-add-keywords' catalogPath check is where it compares one. The probe sends the pair (0, 0): Lightroom ids start
# at 1, so no photo or keyword matches and no write transaction starts, whichever catalog is open. A path that cannot
# be open must come back WRONG_CATALOG first, so a plugin that ignores catalogPath is refused instead of passed.
NEGATIVE_CONTROL_PATH = "Z:/lr-e2e-guard/no-such-catalog.lrcat"
_PROBE_PAIRS = [{"photoId": 0, "keywordId": 0}]


def _probe_catalog(path: str) -> dict:
    """Ask the plugin whether `path` is the catalog Lightroom has open; returns invoke()'s dict."""
    from cli.main import cli

    params = {"pairs": _PROBE_PAIRS, "catalogPath": path}
    return invoke(CliRunner(), cli, ["catalog", "batch-add-keywords", "--json", json.dumps(params)])


def _error(result: dict) -> dict:
    data = result.get("data")
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        return data["error"]
    return {}


def catalog_guard_reason(expected: str | None, probe) -> str | None:
    """None when the e2e tests may write to the open catalog; otherwise why they must not."""
    if not expected or not expected.strip():
        return "no test catalog named: set LR_E2E_CATALOG to a throwaway .lrcat"
    control = probe(NEGATIVE_CONTROL_PATH)
    code = _error(control).get("code")
    if code != "WRONG_CATALOG":
        if code:
            return f"could not ask Lightroom which catalog is open: {code}: {_error(control).get('message')}"
        return f"the plugin did not refuse a catalog that cannot be open, so it cannot tell which one is: {control}"
    answer = probe(expected)
    if _error(answer).get("code") == "WRONG_CATALOG":
        return f"Lightroom has another catalog open: {_error(answer).get('message')}"
    data = answer.get("data")
    if (answer.get("exit_code") != 0 or not isinstance(data, dict) or data.get("writeRan") is not False
            or data.get("photoNotFound") != 1):
        return f"could not confirm that {expected} is open: {answer}"
    return None


def _require_test_catalog(expected: str | None, probe) -> None:
    """pytest.skip unless Lightroom has `expected` open. Works without the skipping plugin (-p no:skipping)."""
    refused = catalog_guard_reason(expected, probe)
    if refused:
        pytest.skip(f"Refused, nothing written: {refused}")


@pytest.hookimpl(trylast=True)   # after -m / -k deselection, so a run that drops every e2e test never probes
def pytest_collection_modifyitems(config, items):
    """Auto-skip e2e tests when Lightroom is not running, or has a catalog open other than --e2e-catalog.
    Auto-skip destructive tests unless --run-destructive is passed.
    """
    skip_e2e = None
    if any("e2e" in item.keywords for item in items):   # a run without e2e tests never talks to Lightroom
        if not _lightroom_reachable():
            skip_e2e = pytest.mark.skip(reason="Lightroom not reachable (port file missing or connection refused)")
        else:
            refused = catalog_guard_reason(config.getoption("--e2e-catalog"), _probe_catalog)
            if refused:
                skip_e2e = pytest.mark.skip(reason=f"Refused, nothing written: {refused}")

    skip_destructive = None
    if not config.getoption("--run-destructive"):
        skip_destructive = pytest.mark.skip(reason="Destructive test (use --run-destructive)")

    for item in items:
        if "e2e" in item.keywords:
            if skip_e2e:
                item.add_marker(skip_e2e)
            if "destructive" in item.keywords and skip_destructive:
                item.add_marker(skip_destructive)


# --- Fixtures ---


@pytest.fixture(scope="session")
def e2e_state():
    """Shared mutable state across the entire E2E session."""
    return _state


@pytest.fixture(scope="session")
def runner():
    """Click CliRunner for invoking CLI commands."""
    return CliRunner()


@pytest.fixture(scope="session")
def cli_app():
    """The CLI application."""
    from cli.main import cli

    return cli


def invoke(runner, cli_app, args: list[str], fmt: str = "json") -> dict:
    """Helper: invoke CLI command and return parsed result.

    Args:
        runner: CliRunner instance
        cli_app: Click CLI group
        args: Command arguments (e.g. ["system", "ping"])
        fmt: Output format ("json" for machine-parseable, "text" for display)

    Returns:
        dict with keys:
          - exit_code: int
          - output: str (raw output)
          - data: parsed JSON (if fmt="json") or None
    """
    full_args = ["-o", fmt] + args
    result = runner.invoke(cli_app, full_args)
    data = None
    if fmt == "json" and result.output.strip():
        try:
            data = json.loads(result.output)
        except json.JSONDecodeError:
            pass
    return {
        "exit_code": result.exit_code,
        "output": result.output,
        "data": data,
    }


@pytest.fixture(scope="session")
def run(runner, cli_app):
    """Convenience fixture: run("system", "ping") -> dict."""

    def _run(*args, fmt="json"):
        return invoke(runner, cli_app, list(args), fmt=fmt)

    return _run


# --- Session-level fallback cleanup ---


def _final_cleanup(run, e2e_state, expected: str | None, probe) -> bool:
    """Reset what the tests changed on the selected photo, only if Lightroom still has the test catalog open."""
    refused = catalog_guard_reason(expected, probe)
    if refused:
        warnings.warn(f"E2E session cleanup skipped, nothing written: {refused}", stacklevel=2)
        return False
    # Emergency cleanup: reset develop to defaults
    run("develop", "reset")
    # Unflag
    run("selection", "unflag")
    # Reset rating
    run("selection", "set-rating", "0")
    # Reset color label
    run("selection", "color-label", "none")
    # Restore original selection if we have the photo_id
    if e2e_state.photo_id:
        run("catalog", "select", e2e_state.photo_id)
    return True


def _guarded_session(run, e2e_state, expected: str | None, probe):
    """session_cleanup's body: check the open catalog at the start and again before the cleanup writes. The
    collection-time skip does nothing under -p no:skipping, and Lightroom can open another catalog during a run."""
    _require_test_catalog(expected, probe)
    yield
    _final_cleanup(run, e2e_state, expected, probe)


@pytest.fixture(scope="session", autouse=True)
def session_cleanup(run, e2e_state, pytestconfig):
    """Final cleanup at end of E2E session, guarded by the catalog check (see _guarded_session)."""
    yield from _guarded_session(run, e2e_state, pytestconfig.getoption("--e2e-catalog"), _probe_catalog)
