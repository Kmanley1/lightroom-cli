"""The e2e tests run only when Lightroom has the named test catalog open (toolkit-lightroom, 2026-10-20).

In June the e2e suite ran against the live Photos catalog: it skipped only when Lightroom was unreachable, so its
writes landed in whatever photo it picked, and "E2E Test Title" plus snapshot e2e_test_snap stayed in one family
photo for four months. tests/e2e/conftest.py now asks the plugin which catalog is open -- through
batch-add-keywords' catalogPath check, with the pair (0, 0) that can never write -- and skips every e2e test unless
it is the one --e2e-catalog / LR_E2E_CATALOG names. These tests never talk to Lightroom.
"""
from unittest.mock import AsyncMock, patch

import pytest

from tests.e2e import conftest as e2e

TEST_CATALOG = r"C:\_\main\LightRoom\Catalogs\Test\Test.lrcat"
PHOTOS_CATALOG = r"C:\_\main\LightRoom\Catalogs\Photos\Photos.lrcat"


def _wrong_catalog(open_path, expected):
    return {"exit_code": 1, "output": "", "data": {"error": {
        "code": "WRONG_CATALOG",
        "message": f"Open catalog is '{open_path}', expected '{expected}' -- nothing changed"}}}


def _matched():
    # What the plugin answers for the pair (0, 0) when the catalog check passes: no such photo, no write.
    return {"exit_code": 0, "output": "", "data": {
        "requested": 1, "added": 0, "photoNotFound": 1, "keywordNotFound": 0, "complete": False,
        "writeRan": False, "results": [{"photoId": 0, "keywordId": 0, "status": "photo_not_found"}]}}


class FakeLightroom:
    """Answers the probe as a plugin with `open_path` open would; records every path it was asked about."""

    def __init__(self, open_path, honours_catalog_path=True, matched=None):
        self.open_path = open_path
        self.honours_catalog_path = honours_catalog_path
        self.matched = matched or _matched()
        self.asked = []

    def __call__(self, path):
        self.asked.append(path)
        if self.honours_catalog_path and path.lower() != self.open_path.lower():
            return _wrong_catalog(self.open_path, path)
        return self.matched


# --- catalog_guard_reason: the decision ---


def test_photos_open_is_refused():
    lr = FakeLightroom(PHOTOS_CATALOG)
    reason = e2e.catalog_guard_reason(TEST_CATALOG, lr)
    assert reason is not None
    assert PHOTOS_CATALOG in reason   # the refusal names the catalog that is open


def test_the_named_test_catalog_open_is_allowed():
    lr = FakeLightroom(TEST_CATALOG)
    assert e2e.catalog_guard_reason(TEST_CATALOG, lr) is None
    assert lr.asked[-1] == TEST_CATALOG


@pytest.mark.parametrize("expected", [None, "", "   "])
def test_no_catalog_named_is_refused_without_asking_lightroom(expected):
    lr = FakeLightroom(TEST_CATALOG)
    reason = e2e.catalog_guard_reason(expected, lr)
    assert reason is not None and "LR_E2E_CATALOG" in reason
    assert lr.asked == []


def test_a_plugin_that_ignores_catalog_path_is_refused():
    # An older plugin answers every path as a match; the negative control has to come back WRONG_CATALOG first.
    lr = FakeLightroom(PHOTOS_CATALOG, honours_catalog_path=False)
    reason = e2e.catalog_guard_reason(TEST_CATALOG, lr)
    assert reason is not None and "cannot tell" in reason
    assert lr.asked == [e2e.NEGATIVE_CONTROL_PATH]   # stops before asking about the real path


@pytest.mark.parametrize("matched", [
    {"exit_code": 0, "output": "", "data": {"photoNotFound": 1, "writeRan": True}},      # a write ran
    {"exit_code": 0, "output": "", "data": {"photoNotFound": 0, "writeRan": False}},     # photo 0 was found
    {"exit_code": 0, "output": "", "data": {"photoNotFound": 1}},                        # writeRan missing
    {"exit_code": 0, "output": "not json", "data": None},
    {"exit_code": 3, "output": "", "data": {"error": {"code": "CONNECTION_ERROR", "message": "refused"}}},
    {"exit_code": 4, "output": "", "data": {"error": {"code": "TIMEOUT_ERROR", "message": "slow"}}},
])
def test_an_answer_that_is_not_a_clean_match_is_refused(matched):
    lr = FakeLightroom(TEST_CATALOG, matched=matched)
    assert e2e.catalog_guard_reason(TEST_CATALOG, lr) is not None


def test_a_negative_control_that_errors_otherwise_is_refused():
    def probe(path):
        return {"exit_code": 3, "output": "", "data": {"error": {"code": "CONNECTION_ERROR", "message": "refused"}}}

    assert e2e.catalog_guard_reason(TEST_CATALOG, probe) is not None


def test_the_negative_control_path_can_never_be_an_open_catalog():
    assert e2e.NEGATIVE_CONTROL_PATH.lower() not in (TEST_CATALOG.lower(), PHOTOS_CATALOG.lower())
    assert e2e.NEGATIVE_CONTROL_PATH.endswith(".lrcat")


# --- _probe_catalog: the real CLI call it sends ---


def _bridge(mock_get_bridge, reply):
    b = AsyncMock()
    b.send_command.return_value = reply
    mock_get_bridge.return_value = b
    return b


@patch("cli.helpers.get_bridge")
def test_the_probe_sends_the_pair_that_cannot_write(mock_get_bridge):
    b = _bridge(mock_get_bridge, {"id": "x", "success": True, "result": _matched()["data"]})
    result = e2e._probe_catalog(TEST_CATALOG)
    assert result["exit_code"] == 0, result["output"]
    command, params = b.send_command.call_args.args
    assert command == "catalog.batchAddKeywords"
    assert params == {"pairs": [{"photoId": 0, "keywordId": 0}], "catalogPath": TEST_CATALOG}
    # This mock answers every path as a match, like a plugin that ignores catalogPath: through the real CLI, refused.
    assert e2e.catalog_guard_reason(TEST_CATALOG, e2e._probe_catalog) is not None


@patch("cli.helpers.get_bridge")
def test_the_probe_reads_a_wrong_catalog_refusal_from_the_cli(mock_get_bridge):
    _bridge(mock_get_bridge, {"id": "x", "success": False, "error": {
        "code": "WRONG_CATALOG",
        "message": f"Open catalog is '{PHOTOS_CATALOG}', expected '{TEST_CATALOG}' -- nothing changed"}})
    result = e2e._probe_catalog(TEST_CATALOG)
    assert result["exit_code"] == 1
    assert result["data"]["error"]["code"] == "WRONG_CATALOG"
    reason = e2e.catalog_guard_reason(TEST_CATALOG, e2e._probe_catalog)
    assert reason is not None


# --- pytest_collection_modifyitems: every e2e test skips when refused ---


class FakeItem:
    def __init__(self, *keywords):
        self.keywords = set(keywords)
        self.markers = []

    def add_marker(self, marker):
        self.markers.append(marker)

    def skip_reasons(self):
        return [m.kwargs.get("reason", "") for m in self.markers if m.name == "skip"]


class FakeConfig:
    def __init__(self, catalog=None, run_destructive=False):
        self.options = {"--e2e-catalog": catalog, "--run-destructive": run_destructive}

    def getoption(self, name):
        return self.options[name]


def _collect(monkeypatch, open_path, catalog, reachable=True, run_destructive=False):
    lr = FakeLightroom(open_path)
    monkeypatch.setattr(e2e, "_lightroom_reachable", lambda: reachable)
    monkeypatch.setattr(e2e, "_probe_catalog", lr)
    items = [FakeItem("e2e"), FakeItem("e2e", "destructive"), FakeItem("unit")]
    e2e.pytest_collection_modifyitems(FakeConfig(catalog, run_destructive), items)
    return items, lr


def test_photos_open_skips_every_e2e_test_and_no_other(monkeypatch):
    items, _ = _collect(monkeypatch, PHOTOS_CATALOG, TEST_CATALOG, run_destructive=True)
    read, destructive, unit = items
    assert read.skip_reasons() and PHOTOS_CATALOG in read.skip_reasons()[0]
    assert destructive.skip_reasons() and PHOTOS_CATALOG in destructive.skip_reasons()[0]
    assert unit.markers == []


def test_test_catalog_open_skips_nothing_but_destructive(monkeypatch):
    items, _ = _collect(monkeypatch, TEST_CATALOG, TEST_CATALOG)
    read, destructive, unit = items
    assert read.markers == []
    assert destructive.skip_reasons() == ["Destructive test (use --run-destructive)"]
    assert unit.markers == []


def test_test_catalog_open_with_run_destructive_skips_nothing(monkeypatch):
    items, _ = _collect(monkeypatch, TEST_CATALOG, TEST_CATALOG, run_destructive=True)
    assert all(item.markers == [] for item in items)


def test_unreachable_lightroom_skips_without_probing(monkeypatch):
    items, lr = _collect(monkeypatch, TEST_CATALOG, TEST_CATALOG, reachable=False)
    assert "not reachable" in items[0].skip_reasons()[0]
    assert lr.asked == []


def test_the_hook_runs_after_m_and_k_deselection():
    # trylast: a `-m "not e2e"` or `-k unit` run must not see the deselected e2e tests, or it would probe Lightroom.
    assert getattr(e2e.pytest_collection_modifyitems, "pytest_impl", {}).get("trylast") is True


# --- the session fixture checks again: at its start and before the cleanup writes ---
# The collection-time skip does nothing under `-p no:skipping`, and the open catalog can change during a run;
# the cleanup resets develop, flag, rating and label on whatever photo is selected.


def test_the_session_start_skips_when_photos_is_open():
    with pytest.raises(pytest.skip.Exception, match="Photos.lrcat"):
        e2e._require_test_catalog(TEST_CATALOG, FakeLightroom(PHOTOS_CATALOG))


def test_the_session_start_passes_when_the_test_catalog_is_open():
    e2e._require_test_catalog(TEST_CATALOG, FakeLightroom(TEST_CATALOG))


class RecordingRun:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        return {"exit_code": 0, "output": "", "data": {}}


def test_the_cleanup_writes_nothing_when_photos_is_open_by_then():
    run = RecordingRun()
    state = e2e.E2EState(photo_id="11772")
    with pytest.warns(UserWarning, match="Photos.lrcat"):
        assert e2e._final_cleanup(run, state, TEST_CATALOG, FakeLightroom(PHOTOS_CATALOG)) is False
    assert run.calls == []


def test_the_cleanup_resets_the_selection_when_the_test_catalog_is_open():
    run = RecordingRun()
    state = e2e.E2EState(photo_id="2229")
    assert e2e._final_cleanup(run, state, TEST_CATALOG, FakeLightroom(TEST_CATALOG)) is True
    assert run.calls == [("develop", "reset"), ("selection", "unflag"), ("selection", "set-rating", "0"),
                         ("selection", "color-label", "none"), ("catalog", "select", "2229")]


def test_the_session_skips_at_its_start_when_photos_is_open():
    run = RecordingRun()
    session = e2e._guarded_session(run, e2e.E2EState(), TEST_CATALOG, FakeLightroom(PHOTOS_CATALOG))
    with pytest.raises(pytest.skip.Exception, match="Photos.lrcat"):
        next(session)
    assert run.calls == []


def test_the_session_runs_and_cleans_up_in_the_test_catalog():
    run = RecordingRun()
    session = e2e._guarded_session(run, e2e.E2EState(photo_id="2229"), TEST_CATALOG, FakeLightroom(TEST_CATALOG))
    next(session)   # the tests run here
    assert run.calls == []
    with pytest.raises(StopIteration):
        next(session)
    assert run.calls[0] == ("develop", "reset") and run.calls[-1] == ("catalog", "select", "2229")


def test_photos_opened_during_the_run_gets_no_cleanup_writes():
    run = RecordingRun()
    lr = FakeLightroom(TEST_CATALOG)
    session = e2e._guarded_session(run, e2e.E2EState(photo_id="2229"), TEST_CATALOG, lr)
    next(session)
    lr.open_path = PHOTOS_CATALOG   # Ken switched catalogs mid-run
    with pytest.warns(UserWarning, match="Photos.lrcat"), pytest.raises(StopIteration):
        next(session)
    assert run.calls == []


def test_without_the_skipping_plugin_the_real_fixture_still_skips(tmp_path):
    # The real conftest, end to end. Safe: the port file does not exist and no catalog is named, so nothing can
    # reach Lightroom even if the guard failed.
    import os
    import pathlib
    import subprocess
    import sys

    repo = pathlib.Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "LR_E2E_CATALOG"}
    env["LR_PORT_FILE"] = str(tmp_path / "no-such-ports.txt")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/e2e/test_phase01_system.py", "-q", "-p", "no:cacheprovider",
         "-p", "no:skipping"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=300,
    )
    summary = proc.stdout.strip().splitlines()[-1]
    assert proc.returncode == 0, proc.stdout[-2000:]
    assert "4 skipped" in summary and "passed" not in summary and "failed" not in summary, summary


def test_a_run_without_e2e_tests_never_talks_to_lightroom(monkeypatch):
    def unreachable():
        raise AssertionError("asked whether Lightroom is reachable")

    monkeypatch.setattr(e2e, "_lightroom_reachable", unreachable)
    monkeypatch.setattr(e2e, "_probe_catalog", FakeLightroom(TEST_CATALOG))
    items = [FakeItem("unit")]
    e2e.pytest_collection_modifyitems(FakeConfig(TEST_CATALOG), items)
    assert items[0].markers == []
