"""catalog.removeKeyword + the CLI's error output (2026-10-06).

1. `lr catalog remove-keyword 0 x` crashed with OPERATION_FAILED "?:0: attempt to index a nil value": for an id that
   is not in the catalog LrC's getPhotoByLocalId returns a DUD object, not nil (measured live 2026-10-07 with
   `catalog probe-photo`: uuid and path read back nil, flag/keywords/file name throw), so the handler's own
   `if not photo` never ran. Now no uuid = PHOTO_NOT_FOUND; a lookup that fails any other way stays OPERATION_FAILED
   (a busy catalog is not a missing photo).
2. Every error printed a second line, {"error": {"code": "ERROR", "message": "1"}}: ctx.exit() raises click's Exit,
   a RuntimeError subclass, and execute_command's `except Exception` caught it and printed str(Exit(1)) == "1".
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from cli.main import cli

lupa = pytest.importorskip("lupa")
from tests.test_plugin_lua_unit import _load, _make_runtime  # noqa: E402

STUB = """
    unpack = unpack or table.unpack     -- LrC is Lua 5.1 (global unpack); the test runtime is 5.4
    writes = 0
    lookup_fail = false
    local function mkkw(name)
        local k = { _name = name }
        function k:getName() return self._name end
        return k
    end
    local function mkphoto(kws)
        local p = { _kws = kws }
        function p:getRawMetadata(key)
            if key == 'keywords' then return self._kws end
            if key == 'uuid' then return 'UUID-1' end
        end
        function p:getFormattedMetadata(key) return 'a.jpg' end
        function p:removeKeyword(kw)
            for i, k in ipairs(self._kws) do if k == kw then table.remove(self._kws, i) return end end
        end
        return p
    end
    PHOTOS = { [100] = mkphoto({ mkkw('Wedding'), mkkw('People') }) }
    function names(id)
        local out = {}
        for _, k in ipairs(PHOTOS[id]._kws) do table.insert(out, k:getName()) end
        return table.concat(out, ',')
    end
    throw_for_missing = false   -- unknown id: throw at the lookup (NOT what LrC does; kept to test the error path)
    DUD = {}                    -- what LrC returns for an unknown id (measured live 2026-10-07 with probe-photo)
    function DUD:getRawMetadata(key)
        if key == 'uuid' or key == 'path' then return nil end
        error('?:0: attempt to index a nil value')
    end
    function DUD:getFormattedMetadata() error('?:0: attempt to index a nil value') end
    reads = 0
    CATALOG = {}
    function CATALOG:withReadAccessDo(fn) reads = reads + 1; fn() end
    function CATALOG:getPhotoByLocalId(id)
        if lookup_fail then error('catalog busy') end
        local p = PHOTOS[id]
        if p == nil then
            if throw_for_missing then error('?:0: attempt to index a nil value') end   -- not seen live
            return DUD       -- what LrC does (live 2026-10-07): a dud object, uuid/path nil, other reads throw
        end
        return p
    end
    function CATALOG:withWriteAccessDo(_name, fn, _opts) writes = writes + 1; fn(); return 'executed' end
    local real_import = import
    function import(name)
        if name == 'LrApplication' then return { activeCatalog = function() return CATALOG end } end
        if name == 'LrTasks' then return { pcall = pcall, sleep = function() end } end
        return real_import(name)
    end
"""


@pytest.fixture
def cat():
    rt = _make_runtime()
    rt.execute(STUB)
    rt.execute("_G.LightroomPythonBridge = { ErrorUtils = require('ErrorUtils') }")
    return rt, _load(rt, "CatalogModule")


def _call(cat, params_lua):
    rt, module = cat
    captured = []
    module["removeKeyword"](rt.eval("{ " + params_lua + " }"), lambda r: captured.append(r))
    assert len(captured) == 1
    return captured[0]


@pytest.mark.parametrize("pid", ["0", "999999999", "-5"])
def test_a_missing_photo_is_photo_not_found_not_a_crash(cat, pid):
    resp = _call(cat, f"photoId = '{pid}', keyword = 'Wedding'")      # LrC hands back a dud: no uuid
    assert resp["error"]["code"] == "PHOTO_NOT_FOUND" and pid in resp["error"]["message"]


def test_a_lookup_that_throws_is_operation_failed_not_photo_not_found(cat):
    cat[0].execute("throw_for_missing = true")                          # never seen live; stay conservative
    assert _call(cat, "photoId = '0', keyword = 'Wedding'")["error"]["code"] == "OPERATION_FAILED"


def test_a_failed_lookup_is_not_reported_as_missing(cat):
    cat[0].execute("lookup_fail = true")
    resp = _call(cat, "photoId = '100', keyword = 'Wedding'")
    assert resp["error"]["code"] == "OPERATION_FAILED" and "catalog busy" in resp["error"]["message"]


def test_removes_a_keyword_by_name(cat):
    resp = _call(cat, "photoId = '100', keyword = 'Wedding'")
    assert resp["result"]["message"] == "Keyword removed" and cat[0].eval("names(100)") == "People"


def test_a_keyword_not_on_the_photo(cat):
    assert _call(cat, "photoId = '100', keyword = 'Nope'")["error"]["code"] == "KEYWORD_NOT_FOUND"


def test_photo_by_id_helper(cat):
    rt, module = cat
    photo, err = module["_photoById"](rt.eval("CATALOG"), 100)
    assert photo is not None and err is None
    photo, err = module["_photoById"](rt.eval("CATALOG"), 0)
    assert photo is None and err is None
    rt.execute("throw_for_missing = true")                   # a lookup that throws: an error, not "not there"
    photo, err = module["_photoById"](rt.eval("CATALOG"), 0)
    assert photo is None and "attempt to index a nil value" in err
    rt.execute("throw_for_missing = false")
    photo, err = module["_photoById"](rt.eval("CATALOG"), "x")
    assert photo is None and err is None
    rt.execute("lookup_fail = true")
    photo, err = module["_photoById"](rt.eval("CATALOG"), 100)
    assert photo is None and "catalog busy" in err


# ---- probe-photo: the read-only diagnostic (2026-10-07) ------------------------------------------------------------

def _probe(cat, pid):
    rt, module = cat
    captured = []
    module["probePhoto"](rt.eval(f"{{ photoId = '{pid}' }}"), lambda r: captured.append(r))
    assert len(captured) == 1 and cat[0].eval("writes") == 0      # never writes
    res = captured[0]["result"]
    return {res["steps"][i]["step"]: (res["steps"][i]["ok"], res["steps"][i]["result"], res["steps"][i]["error"])
            for i in range(1, len(res["steps"]) + 1)}


def test_probe_a_real_photo_reads_everything(cat):
    s = _probe(cat, 100)
    assert all(ok for ok, _, _ in s.values())
    assert s["getRawMetadata('uuid')"][1] == "string: UUID-1"
    assert s["getRawMetadata('keywords')"][1] == "table with 2 entries"
    assert s["getFormattedMetadata('fileName')"][1] == "string: a.jpg"


def test_probe_a_lookup_that_throws_stops_at_the_lookup(cat):
    cat[0].execute("throw_for_missing = true")
    s = _probe(cat, 0)
    ok, result, err = s["lookup, read txn, LrTasks.pcall"]
    assert (ok, result) == (False, None) and "attempt to index a nil value" in err
    assert s["lookup, read txn, plain pcall"][0] is False
    assert "getRawMetadata('keywords')" not in s


def test_probe_a_dud_object_shows_which_read_fails(cat):
    s = _probe(cat, 0)                                     # the default: what LrC really does
    assert s["lookup, read txn, LrTasks.pcall"][0] is True
    assert s["getRawMetadata('uuid')"] == (True, "nil", None)
    assert s["getRawMetadata('keywords')"][0] is False and "index a nil" in s["getRawMetadata('keywords')"][2]


def test_probe_needs_a_numeric_id(cat):
    rt, module = cat
    captured = []
    module["probePhoto"](rt.eval("{ photoId = 'x' }"), lambda r: captured.append(r))
    assert captured[0]["error"]["code"] == "MISSING_PARAM"


def test_probe_cli_and_schema():
    from lightroom_sdk.validation import validate_params

    res = CliRunner().invoke(cli, ["-o", "json", "catalog", "probe-photo", "0", "--help"])
    assert res.exit_code == 0 and "read-only" in res.output
    assert validate_params("catalog.probePhoto", {"photoId": "0"}) == {"photoId": "0"}


# ---- one error line, not two ---------------------------------------------------------------------------------------

def _error_lines(output):
    return [line for line in output.splitlines() if line.strip().startswith("{") and '"error"' in line]


@pytest.mark.parametrize("fmt", ["json", "text"])
def test_a_plugin_error_prints_one_error_and_exits_1(fmt):
    bridge = AsyncMock()
    bridge.send_command.return_value = {"success": False,
                                        "error": {"code": "PHOTO_NOT_FOUND", "message": "Photo 0 not found"}}
    with patch("cli.helpers.get_bridge", return_value=bridge):
        res = CliRunner().invoke(cli, ["-o", fmt, "catalog", "remove-keyword", "0", "x"])
    assert res.exit_code == 1
    assert '"message": "1"' not in res.output and "Error: 1" not in res.output
    if fmt == "json":
        lines = _error_lines(res.output)
        assert len(lines) == 1 and json.loads(lines[0])["error"]["code"] == "PHOTO_NOT_FOUND"
    else:
        assert res.output.count("Photo 0 not found") == 1


def test_a_connection_error_still_exits_3_with_one_line():
    bridge = AsyncMock()
    bridge.send_command.side_effect = ConnectionError("Failed to connect after 3 attempts")
    with patch("cli.helpers.get_bridge", return_value=bridge):
        res = CliRunner().invoke(cli, ["-o", "json", "catalog", "remove-keyword", "0", "x"])
    assert res.exit_code == 3 and len(_error_lines(res.output)) == 1
