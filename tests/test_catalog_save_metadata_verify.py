"""catalog.saveMetadata counts a photo as saved only when its file changes on disk (2026-10-21).

Live in the Test catalog, photo:saveMetadata() on a read-only file returned normally, the file stayed untouched, and
Lightroom showed "Some save metadata operations were not performed" -- while the bridge said success: true. A real
photo had failed the same way the day before, with no message. Lua handler tests run the real plugin code against a
stub that models a disk (file -> modification time), a clock that LrTasks.sleep advances, and photos whose save
writes the file, a sidecar, nothing, late, or throws. Plus the CLI's exit code.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from cli.main import cli

lupa = pytest.importorskip("lupa")
from tests.test_plugin_lua_unit import _load, _make_runtime  # noqa: E402

STUB = r"""
    unpack = unpack or table.unpack
    CLOCK = 1000.0
    FILES = {}                  -- path -> modification time (seconds); absent = no file
    SCHEDULED = {}              -- { at = time, path = p }: a write that lands later
    save_calls, dud_saves, slept = 0, 0, 0
    attrs_mode = 'ok'           -- 'nokey': fileAttributes has no time | 'throw'
    attrs_fail = {}             -- path -> true: fileAttributes throws for that file only
    whole_seconds = false       -- the disk keeps whole-second times
    save_cost = 0               -- seconds each saveMetadata call takes
    lookup_fail_for = nil

    local function stamp() if whole_seconds then return math.floor(CLOCK) end return CLOCK end
    local function land()
        for i = #SCHEDULED, 1, -1 do
            local s = SCHEDULED[i]
            if CLOCK >= s.at then FILES[s.path] = stamp(); table.remove(SCHEDULED, i) end
        end
    end
    function stem(p) return (p:gsub('%.[^.\\/]*$', '')) end
    -- Lightroom's fileFormat values (Ken's catalogs, 2026-10-21: JPG, RAW, DNG, TIFF, HEIC, PNG, VIDEO)
    local FORMATS = { jpg = 'JPG', cr2 = 'RAW', nef = 'RAW', dng = 'DNG', tif = 'TIFF', heic = 'HEIC', png = 'PNG',
                      mp4 = 'VIDEO' }

    local function mkphoto(id, path, mode, delay, fmt)
        local ext = path and path:match('%.([^.\\/]*)$')
        local p = { localIdentifier = id, _path = path, _mode = mode, _delay = delay,
                    _format = fmt or (ext and FORMATS[ext:lower()]), _vc = false }
        function p:getRawMetadata(key)
            if key == 'uuid' then return 'UUID' end
            if key == 'path' then return self._path end
            if key == 'fileFormat' then return self._format end
            if key == 'isVirtualCopy' then return self._vc end
            return nil
        end
        function p:saveMetadata()
            save_calls = save_calls + 1
            local m = self._mode
            if m == 'throw' then error('boom') end
            if m ~= 'silent' then                                             -- silent: the bug, no write, no error
                local target = self._path
                if m == 'sidecar' then target = stem(self._path) .. '.xmp' end
                if m == 'sidecar_ext' then target = self._path .. '.xmp' end
                if self._delay then
                    table.insert(SCHEDULED, { at = CLOCK + self._delay, path = target })
                else
                    FILES[target] = stamp()
                end
            end
            CLOCK = CLOCK + save_cost
            land()
        end
        return p
    end
    PHOTOS = {}
    function add(id, path, mode, delay, mtime, fmt)
        PHOTOS[id] = mkphoto(id, path, mode, delay, fmt)
        if path and mtime ~= false then FILES[path] = mtime or 500 end
    end
    function add_vc(id, master, mode)   -- a virtual copy: same file as its master
        PHOTOS[id] = mkphoto(id, PHOTOS[master]._path, mode or 'write')
        PHOTOS[id]._vc = true
    end
    DUD = {}
    function DUD:getRawMetadata(key)
        if key == 'uuid' or key == 'path' then return nil end
        error('?:0: attempt to index a nil value')
    end
    function DUD:saveMetadata() dud_saves = dud_saves + 1 end
    TARGET_PHOTO, TARGET_PHOTOS = nil, {}
    CATALOG = {}
    function CATALOG:getPhotoByLocalId(id)
        if lookup_fail_for and id == lookup_fail_for then error('catalog busy') end
        return PHOTOS[id] or DUD
    end
    function CATALOG:withReadAccessDo(fn) fn() end
    function CATALOG:getTargetPhoto() return TARGET_PHOTO end
    function CATALOG:getTargetPhotos() return TARGET_PHOTOS end

    local real_import = import
    function import(name)
        if name == 'LrApplication' then return { activeCatalog = function() return CATALOG end } end
        if name == 'LrTasks' then
            return { pcall = pcall, yield = function() end,
                     sleep = function(s) slept = slept + s; CLOCK = CLOCK + s; land() end }
        end
        if name == 'LrDate' then return { currentTime = function() return CLOCK end } end
        if name == 'LrFileUtils' then
            return {
                exists = function(p) return FILES[p] ~= nil and 'file' or false end,
                fileAttributes = function(p)
                    if attrs_mode == 'throw' or attrs_fail[p] then error('attributes busy') end
                    if attrs_mode == 'nokey' then return { fileSize = 1 } end
                    return { fileModificationDate = FILES[p], fileSize = 1 }
                end,
            }
        end
        if name == 'LrPathUtils' then return { removeExtension = stem } end
        return real_import(name)
    end
"""

JPG = r"C:\photos\a.jpg"
JPG2 = r"C:\photos\b.jpg"
RAW = r"C:\photos\c.cr2"
RAW_XMP = r"C:\photos\c.xmp"


@pytest.fixture
def cat():
    rt = _make_runtime()
    rt.execute(STUB)
    rt.execute("_G.LightroomPythonBridge = { ErrorUtils = require('ErrorUtils') }")
    return rt, _load(rt, "CatalogModule")


def _lua(s):
    return "[[" + s + "]]"


def _add(cat, pid, path, mode="write", delay=None, mtime=None):
    d = "nil" if delay is None else str(delay)
    m = "nil" if mtime is None else ("false" if mtime is False else str(mtime))
    p = "nil" if path is None else _lua(path)
    cat[0].execute(f"add({pid}, {p}, '{mode}', {d}, {m})")


def _call(cat, ids=None):
    rt, module = cat
    captured = []
    params = rt.eval("{ photoIds = {" + ", ".join(str(i) for i in ids) + "} }") if ids is not None else rt.eval("{}")
    module["saveMetadata"](params, lambda r: captured.append(r))
    assert len(captured) == 1  # exactly one response, always
    return captured[0]


def _results(resp):
    res = resp["result"]["results"]
    out = []
    for i in range(1, len(res) + 1):
        r = res[i]
        out.append({k: r[k] for k in ("photoId", "success", "status", "file", "error") if r[k] is not None})
    return out


def _counts(resp):
    return tuple(resp["result"][k] for k in ("total", "succeeded", "failed"))


def _ev(cat, expr):
    return cat[0].eval(expr)


# ---- the outcomes --------------------------------------------------------------------------------------------------

def test_a_file_that_changes_is_written(cat):
    _add(cat, 100, JPG)
    resp = _call(cat, [100])
    assert _results(resp) == [{"photoId": "100", "success": True, "status": "written", "file": JPG}]
    assert _counts(resp) == (1, 1, 0)
    assert _ev(cat, "slept") < 1   # nothing to wait for


def test_a_save_lightroom_does_not_perform_is_not_written(cat):
    # the read-only file in Test (2026-10-21): saveMetadata returns, the file never changes
    _add(cat, 100, JPG, "silent")
    resp = _call(cat, [100])
    (r,) = _results(resp)
    assert r["success"] is False and r["status"] == "not_written" and "file" not in r
    assert "Some save metadata operations were not performed" in r["error"]
    assert _counts(resp) == (1, 0, 1)
    assert 30 <= _ev(cat, "slept") < 31   # gave up 30 s after the save, with nothing written
    assert "within 30 s of the save" in r["error"]


def test_one_silent_photo_does_not_spoil_the_others(cat):
    _add(cat, 100, JPG)
    _add(cat, 101, JPG2, "silent")
    st = {r["photoId"]: r["status"] for r in _results(_call(cat, [100, 101]))}
    assert st == {"100": "written", "101": "not_written"}


def test_a_raw_photo_counts_when_its_sidecar_changes(cat):
    _add(cat, 100, RAW, "sidecar")
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "written" and r["file"] == RAW_XMP


def test_an_existing_sidecar_rewritten_counts(cat):
    _add(cat, 100, RAW, "sidecar")
    cat[0].execute(f"FILES[ {_lua(RAW_XMP)} ] = 400")
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "written" and r["file"] == RAW_XMP


def test_a_name_ext_xmp_is_not_lightroom_s(cat):
    # darktable and digiKam write name.ext.xmp; Lightroom writes name.xmp, so a change there proves nothing
    _add(cat, 100, RAW, "sidecar_ext")
    assert _results(_call(cat, [100]))[0]["status"] == "not_written"


def test_a_jpeg_next_to_a_raw_does_not_take_the_raw_s_sidecar(cat):
    # refuter 2026-10-21: RAW+JPEG as separate photos share the stem; the JPEG's own file never changed
    _add(cat, 100, RAW, "sidecar")
    _add(cat, 101, r"C:\photos\c.jpg", "silent")
    st = {r["photoId"]: (r["status"], r.get("file")) for r in _results(_call(cat, [100, 101]))}
    assert st == {"100": ("written", RAW_XMP), "101": ("not_written", None)}


@pytest.mark.parametrize("fmt,expected", [
    ("JPG", [JPG]), ("TIFF", [JPG]), ("PSD", [JPG]), ("DNG", [JPG]),
    ("RAW", [r"C:\photos\a.xmp"]), ("HEIC", [r"C:\photos\a.xmp"]),
    ("VIDEO", [JPG, r"C:\photos\a.xmp"]), ("PNG", [JPG, r"C:\photos\a.xmp"]), (None, [JPG, r"C:\photos\a.xmp"]),
])
def test_which_files_each_format_watches(cat, fmt, expected):
    _call(cat)   # loads the Lr modules, as every real call does first
    targets = cat[1]["_metadataTargets"](JPG, fmt)
    assert [targets[i] for i in range(1, len(targets) + 1)] == expected


@pytest.mark.parametrize("mode", ["write", "sidecar"])
def test_a_video_counts_by_its_file_or_its_sidecar(cat, mode):
    _add(cat, 100, r"C:\photos\v.mp4", mode)
    assert _results(_call(cat, [100]))[0]["status"] == "written"


def test_an_unreadable_sidecar_time_is_skipped_and_not_saved(cat):
    # refuter 2026-10-21: a "?" before and a real time after must not read as a write
    _add(cat, 100, RAW, "silent")
    cat[0].execute(f"FILES[ {_lua(RAW_XMP)} ] = 400; attrs_fail[ {_lua(RAW_XMP)} ] = true")
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "skipped" and RAW_XMP in r["error"] and _ev(cat, "save_calls") == 0


def test_a_virtual_copy_is_not_saved(cat):
    # its metadata lives only in the catalog; the master's save changes the same file
    _add(cat, 100, JPG)
    cat[0].execute("add_vc(101, 100)")
    st = {r["photoId"]: r["status"] for r in _results(_call(cat, [100, 101]))}
    assert st == {"100": "written", "101": "virtual_copy"} and _ev(cat, "save_calls") == 1


def test_a_save_that_throws_is_an_error(cat):
    _add(cat, 100, JPG, "throw")
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "error" and "boom" in r["error"] and r["success"] is False


def test_a_missing_file_is_reported_and_not_saved(cat):
    _add(cat, 100, JPG, mtime=False)
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "file_missing" and JPG in r["error"]
    assert _ev(cat, "save_calls") == 0


def test_an_unknown_id_is_not_found_and_never_saved(cat):
    # Lightroom returns a dud object for an unknown id (live 2026-10-07); the old code saved it and said success
    _add(cat, 100, JPG)
    resp = _call(cat, [100, 999])
    st = {r["photoId"]: r["status"] for r in _results(resp)}
    assert st == {"100": "written", "999": "photo_not_found"}
    assert _ev(cat, "dud_saves") == 0 and _counts(resp) == (2, 1, 1)


def test_only_unknown_ids_still_report_per_id(cat):
    resp = _call(cat, [998, 999])
    assert [r["status"] for r in _results(resp)] == ["photo_not_found", "photo_not_found"]
    assert _counts(resp) == (2, 0, 2)


def test_a_failed_lookup_is_skipped(cat):
    _add(cat, 100, JPG)
    _add(cat, 101, JPG2)
    cat[0].execute("lookup_fail_for = 101")
    st = {r["photoId"]: r["status"] for r in _results(_call(cat, [100, 101]))}
    assert st == {"100": "written", "101": "skipped"}


@pytest.mark.parametrize("mode", ["nokey", "throw"])
def test_an_unreadable_file_time_is_skipped_and_not_saved(cat, mode):
    _add(cat, 100, JPG)
    cat[0].execute(f"attrs_mode = '{mode}'")
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "skipped" and r["error"].startswith("Not saved") and _ev(cat, "save_calls") == 0


def test_no_path_from_lightroom_is_skipped(cat):
    _add(cat, 100, None)
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "skipped" and _ev(cat, "save_calls") == 0


def test_the_same_id_twice_is_reported_twice(cat):
    _add(cat, 100, JPG)
    assert [r["status"] for r in _results(_call(cat, [100, 100]))] == ["written", "written"]


def test_the_selection_is_checked_the_same_way(cat):
    _add(cat, 100, JPG)
    _add(cat, 101, JPG2, "silent")
    cat[0].execute("TARGET_PHOTO = PHOTOS[100]; TARGET_PHOTOS = { PHOTOS[100], PHOTOS[101] }")
    st = {r["photoId"]: r["status"] for r in _results(_call(cat))}
    assert st == {"100": "written", "101": "not_written"}


def test_an_empty_selection_is_still_refused(cat):
    assert _call(cat)["error"]["code"] == "PHOTO_NOT_FOUND"
    assert _ev(cat, "save_calls") == 0


# ---- waiting -------------------------------------------------------------------------------------------------------

def test_a_write_that_lands_later_is_waited_for(cat):
    _add(cat, 100, JPG, delay=3)
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "written" and 3 <= _ev(cat, "slept") < 4


def test_the_wait_goes_on_while_lightroom_keeps_writing(cat):
    # a batch whose writes trickle in 8 s apart: more than 10 s in all, never 10 s without a write
    for i, d in enumerate([1, 9, 17, 25]):
        _add(cat, 100 + i, rf"C:\photos\t{i}.jpg", delay=d)
    assert {r["status"] for r in _results(_call(cat, [100, 101, 102, 103]))} == {"written"}


def test_a_write_after_ten_quiet_seconds_is_too_late(cat):
    _add(cat, 100, JPG, delay=1)
    _add(cat, 101, JPG2, delay=12)
    res = {r["photoId"]: r for r in _results(_call(cat, [100, 101]))}
    assert {k: r["status"] for k, r in res.items()} == {"100": "written", "101": "not_written"}
    assert "within 10 s of the last write" in res["101"]["error"]


def test_lightroom_s_first_write_may_lag_past_ten_seconds(cat):
    # mm save's bulk runs (2026-10-07..20): a chunk's first file landed 10-12 s after mm's last step before the save,
    # once 21 s, then about 12 files a second. A 10 s window from the save gave up just as the writes began.
    _add(cat, 100, JPG, delay=21)
    _add(cat, 101, JPG2, delay=21.5)
    assert {r["status"] for r in _results(_call(cat, [100, 101]))} == {"written"}


def test_the_first_write_window_starts_when_the_saves_end(cat):
    # refuter 2026-10-22: with free saves, "the saves end" and "the command starts" were the same instant
    cat[0].execute("save_cost = 10")
    _add(cat, 100, JPG, delay=35)     # saved during 0-10 s; the write lands 25 s after the saves end
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "written"


def test_a_first_write_after_thirty_seconds_is_too_late(cat):
    _add(cat, 100, JPG, delay=31)
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "not_written" and "within 30 s of the save" in r["error"]


def test_once_writing_has_begun_ten_quiet_seconds_end_the_wait(cat):
    _add(cat, 100, JPG, delay=12)
    _add(cat, 101, JPG2, delay=23)
    st = {r["photoId"]: r["status"] for r in _results(_call(cat, [100, 101]))}
    assert st == {"100": "written", "101": "not_written"}


def test_the_wait_never_passes_sixty_seconds(cat):
    for i in range(10):
        _add(cat, 100 + i, rf"C:\photos\t{i}.jpg", delay=1 + 9 * i)   # one write every 9 s, the last at 82 s
    res = _results(_call(cat, list(range(100, 110))))
    assert [r["status"] for r in res[:7]] == ["written"] * 7
    assert {r["status"] for r in res[7:]} == {"not_written"} and all("60 s ran out" in r["error"] for r in res[7:])
    assert _ev(cat, "slept") <= 60.5


def test_the_sixty_seconds_count_the_saves_too(cat):
    # refuter 2026-10-21: the limit started after the save loop, so slow saves pushed past the CLI's 120 s
    cat[0].execute("save_cost = 30")
    _add(cat, 100, JPG, "silent")
    _add(cat, 101, JPG2, "silent")
    res = _results(_call(cat, [100, 101]))
    assert [r["status"] for r in res] == ["not_written", "not_written"]
    assert all("60 s ran out" in r["error"] for r in res)   # not "within 30 s of the save": the cap ended it
    assert _ev(cat, "CLOCK") - 1000 <= 60.5


def test_photos_not_reached_in_sixty_seconds_are_skipped_and_not_saved(cat):
    cat[0].execute("save_cost = 25")
    for i in range(4):
        _add(cat, 100 + i, rf"C:\photos\t{i}.jpg")   # saves start at 0, 25, 50 -- the fourth would start at 75
    res = _results(_call(cat, [100, 101, 102, 103]))
    assert [r["status"] for r in res] == ["written", "written", "written", "skipped"]
    assert "ran out" in res[3]["error"] and _ev(cat, "save_calls") == 3


# ---- whole-second file times -------------------------------------------------------------------------------------

def test_a_file_written_this_second_is_let_age_before_the_save(cat):
    # whole-second times: the file was written at 1000 and the save at 1000.3 would stamp 1000 again
    cat[0].execute("whole_seconds = true; CLOCK = 1000.3")
    _add(cat, 100, JPG, mtime=1000)
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "written"
    assert 1.6 < _ev(cat, "slept") < 2.1


def test_without_the_pause_that_save_would_read_as_not_written(cat):
    # calibration: the guard above is what makes the difference
    cat[0].execute("whole_seconds = true; CLOCK = 1000.3")
    _add(cat, 100, JPG, mtime=1000)
    cat[1]["SAVE_SETTLE_SECONDS"] = 0
    assert _results(_call(cat, [100]))[0]["status"] == "not_written"


def test_a_file_time_in_the_future_waits_at_most_the_settle_time(cat):
    _add(cat, 100, JPG, mtime=5000)   # a clock mismatch must not mean a long sleep
    (r,) = _results(_call(cat, [100]))
    assert r["status"] == "written" and _ev(cat, "slept") <= 2.0


def test_old_files_need_no_pause(cat):
    _add(cat, 100, JPG, mtime=900)
    _call(cat, [100])
    assert _ev(cat, "slept") == 0


# ---- CLI ---------------------------------------------------------------------------------------------------------

def _bridge_result(result):
    b = AsyncMock()
    b.send_command.return_value = {"id": "x", "success": True, "result": result}
    return b


@pytest.mark.parametrize("result,code", [
    ({"total": 1, "succeeded": 1, "failed": 0, "results": [{"photoId": "1", "success": True, "status": "written"}]}, 0),
    ({"total": 2, "succeeded": 1, "failed": 1, "results": [{"photoId": "2", "status": "not_written"}]}, 1),
    ({"total": 1, "succeeded": 1, "results": []}, 1),     # no failed count: not proof of a save
    ([], 1),
])
@patch("cli.helpers.get_bridge")
def test_cli_exits_1_when_any_photo_was_not_written(mock_get_bridge, result, code):
    mock_get_bridge.return_value = _bridge_result(result)
    res = CliRunner().invoke(cli, ["-o", "json", "catalog", "save-metadata", "1", "2"])
    assert res.exit_code == code, res.output
    assert json.loads(res.stdout) == result   # the full result is printed either way


@patch("cli.helpers.get_bridge")
def test_other_commands_keep_exit_0_on_partial_results(mock_get_bridge):
    mock_get_bridge.return_value = _bridge_result({"total": 2, "succeeded": 1, "failed": 1, "results": []})
    res = CliRunner().invoke(cli, ["-o", "json", "catalog", "batch-set", "1", "2", "--rating", "3"])
    assert res.exit_code == 0, res.output
