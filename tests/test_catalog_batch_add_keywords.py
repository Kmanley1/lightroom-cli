"""catalog.batchAddKeywords -- add EXISTING keywords (by id) to photos, up to 200 pairs in one write (2026-10-06).

The mirror of batchRemoveKeywords. Lua handler tests run the real plugin code against a stub catalog that models
LrC: a keyword TREE (nested keywords are found by id), photo:addKeyword edits the photo's keyword list; a write can
run, abort or throw; an add can be silently ignored; the read-back can fail. Every pair's status must come from the
reads, so none of those can report "added". It must never create a keyword. Plus CLI mapping (--dry-run, also for
batch-remove-keywords, which now shares the CLI body) and schema validation.
"""
import json

import pytest
from click.testing import CliRunner

from cli.main import cli

lupa = pytest.importorskip("lupa")
from tests.test_plugin_lua_unit import _load, _make_runtime  # noqa: E402

STUB = """
    unpack = unpack or table.unpack
    writes, reads, add_calls, create_calls = 0, 0, 0, 0
    write_mode = 'run'          -- 'abort' | 'throw'
    ignore_add = false          -- addKeyword runs but LrC keeps the photo as it was
    read_fail_after_write = false
    vanish_on_write = nil       -- a photo id removed from the catalog during the write
    collateral = false          -- addKeyword also adds K[4] (a hypothetical LrC side effect)
    nil_for = nil               -- a photo id whose getRawMetadata('keywords') is always nil
    nil_once_for = nil          -- a photo id whose FIRST keywords read is nil, later reads fine
    open_path = [[C:\\_\\main\\LightRoom\\Catalogs\\Carolyn\\Carolyn.lrcat]]
    local function mkkw(id, name)
        local k = { localIdentifier = id, _name = name, _children = {} }
        function k:getName() return self._name end
        function k:getChildren() local c = {} for i, x in ipairs(self._children) do c[i] = x end return c end
        return k
    end
    K = { [1] = mkkw(1, 'shared:with-ken'), [2] = mkkw(2, 'shared:with-ethan'), [3] = mkkw(3, 'People'),
          [4] = mkkw(4, 'Wedding') }
    SHARED = mkkw(10, 'Shared')
    SHARED._children = { K[1], K[2] }            -- nested: found only by walking the tree
    TREE = { SHARED, K[3], K[4] }
    local function mkphoto(kws)
        local p = { _kws = kws }
        function p:getRawMetadata(key)
            if key ~= 'keywords' then return nil end
            if nil_for and PHOTOS[nil_for] == self then return nil end
            if nil_once_for and PHOTOS[nil_once_for] == self then nil_once_for = nil; return nil end
            if read_fail_after_write and writes > 0 then error('read busy') end
            local c = {}
            for i, k in ipairs(self._kws) do c[i] = k end
            return c
        end
        function p:addKeyword(kw)
            add_calls = add_calls + 1
            if ignore_add then return end
            for _, k in ipairs(self._kws) do if k == kw then return end end
            table.insert(self._kws, kw)
            if collateral then
                local has = false
                for _, k in ipairs(self._kws) do if k == K[4] then has = true end end
                if not has then table.insert(self._kws, K[4]) end
            end
        end
        return p
    end
    PHOTOS = { [100] = mkphoto({ K[3] }), [101] = mkphoto({ K[1] }) }
    function names(id)
        local out = {}
        for _, k in ipairs(PHOTOS[id]._kws) do table.insert(out, k:getName()) end
        return table.concat(out, ',')
    end
    CATALOG = {}
    function CATALOG:getPath() return open_path end
    function CATALOG:getPhotoByLocalId(id) return PHOTOS[id] end
    function CATALOG:getKeywords() local c = {} for i, x in ipairs(TREE) do c[i] = x end return c end
    function CATALOG:createKeyword() create_calls = create_calls + 1 end
    function CATALOG:withReadAccessDo(fn) reads = reads + 1; fn() end
    function CATALOG:withWriteAccessDo(_name, fn, _opts)
        writes = writes + 1
        if write_mode == 'throw' then error('write lock timeout') end
        if write_mode == 'abort' then return 'aborted' end
        fn()
        if vanish_on_write then PHOTOS[vanish_on_write] = nil end
        return 'executed'
    end
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


def _lua_pairs(pairs):
    return "{" + ", ".join(f"{{photoId = {p}, keywordId = {k}}}" for p, k in pairs) + "}"


def _call(cat, pairs_lua, extra=""):
    rt, module = cat
    captured = []
    params = rt.eval("{ pairs = " + pairs_lua + extra + " }") if pairs_lua is not None else rt.eval("{}")
    module["batchAddKeywords"](params, lambda r: captured.append(r))
    assert len(captured) == 1  # exactly one response, always
    assert cat[0].eval("create_calls") == 0  # never creates a keyword
    return captured[0]


def _statuses(resp):
    res = resp["result"]["results"]
    return {(int(res[i]["photoId"]), int(res[i]["keywordId"])): res[i]["status"] for i in range(1, len(res) + 1)}


def _r(resp, *keys):
    return tuple(resp["result"][k] for k in keys)


# ---- validation --------------------------------------------------------------------------------------------------

def test_missing_pairs(cat):
    assert _call(cat, None)["error"]["code"] == "MISSING_PARAM"
    assert _call(cat, "{}")["error"]["code"] == "MISSING_PARAM"


def test_non_numeric_pair(cat):
    assert _call(cat, "{ {photoId = 100, keywordId = 'x'} }")["error"]["code"] == "INVALID_PARAM_VALUE"
    assert cat[0].eval("writes") == 0


def test_more_than_200_distinct_pairs(cat):
    assert _call(cat, _lua_pairs([(100, k) for k in range(1, 202)]))["error"]["code"] == "BATCH_SIZE_EXCEEDED"
    assert cat[0].eval("writes") == 0


# ---- outcomes ----------------------------------------------------------------------------------------------------

def test_adds_nested_keywords_by_id_in_one_write(cat):
    resp = _call(cat, _lua_pairs([(100, 1), (100, 2), (101, 2)]))
    assert _r(resp, "added", "notAdded", "unverified", "complete", "writeRan") == (3, 0, 0, True, True)
    assert set(_statuses(resp).values()) == {"added"}
    assert cat[0].eval("names(100)") == "People,shared:with-ken,shared:with-ethan"
    assert cat[0].eval("names(101)") == "shared:with-ken,shared:with-ethan"
    assert cat[0].eval("writes") == 1


def test_already_on_photo_needs_no_write(cat):
    resp = _call(cat, _lua_pairs([(101, 1)]))
    assert _statuses(resp) == {(101, 1): "already_on_photo"}
    assert _r(resp, "alreadyOnPhoto", "complete", "writeRan") == (1, True, False)
    assert cat[0].eval("writes") == 0 and cat[0].eval("add_calls") == 0


def test_unknown_keyword_id_is_reported_never_created(cat):
    resp = _call(cat, _lua_pairs([(100, 999), (100, 1)]))
    st = _statuses(resp)
    assert st[(100, 999)] == "keyword_not_found" and st[(100, 1)] == "added"
    assert _r(resp, "keywordNotFound", "added", "complete") == (1, 1, False)


def test_only_unknown_keywords_means_no_write(cat):
    resp = _call(cat, _lua_pairs([(100, 999)]))
    assert _r(resp, "keywordNotFound", "writeRan") == (1, False) and cat[0].eval("writes") == 0


def test_photo_not_found_makes_the_run_incomplete(cat):
    resp = _call(cat, _lua_pairs([(999, 1), (100, 1)]))
    st = _statuses(resp)
    assert st[(999, 1)] == "photo_not_found" and st[(100, 1)] == "added"
    assert resp["result"]["complete"] is False


def test_ids_from_another_catalog_are_never_complete(cat):
    # review 2026-10-06: no photo found at all must not read as "complete"
    resp = _call(cat, _lua_pairs([(998, 1), (999, 2)]))
    assert _r(resp, "photoNotFound", "added", "writeRan", "complete") == (2, 0, False, False)


def test_a_keyword_on_the_photo_but_missed_by_the_tree_walk_is_already_on_photo(cat):
    cat[0].execute("SHARED._children = { K[2] }")       # the walk no longer reaches K[1], which photo 101 carries
    resp = _call(cat, _lua_pairs([(101, 1)]))
    assert _statuses(resp) == {(101, 1): "already_on_photo"} and resp["result"]["complete"] is True


def test_aborted_write_reports_not_added(cat):
    cat[0].execute("write_mode = 'abort'")
    resp = _call(cat, _lua_pairs([(100, 1), (100, 2)]))
    assert _r(resp, "added", "notAdded", "complete", "writeRan") == (0, 2, False, False)
    assert cat[0].eval("names(100)") == "People"


def test_throwing_write_reports_not_added_and_the_error(cat):
    cat[0].execute("write_mode = 'throw'")
    resp = _call(cat, _lua_pairs([(100, 1)]))
    assert _r(resp, "added", "notAdded", "complete") == (0, 1, False)
    assert "write lock timeout" in resp["result"]["writeError"]


def test_an_add_lightroom_ignores_reports_not_added(cat):
    cat[0].execute("ignore_add = true")
    resp = _call(cat, _lua_pairs([(100, 1)]))
    assert _r(resp, "added", "notAdded", "complete", "writeRan") == (0, 1, False, True)
    assert cat[0].eval("add_calls") == 1


def test_failed_read_back_reports_unverified(cat):
    cat[0].execute("read_fail_after_write = true")
    resp = _call(cat, _lua_pairs([(100, 1), (101, 1)]))
    st = _statuses(resp)
    assert st[(100, 1)] == "unverified" and st[(101, 1)] == "already_on_photo"
    assert resp["result"]["complete"] is False


def test_photo_gone_after_the_write_reports_unverified(cat):
    cat[0].execute("vanish_on_write = 101")
    resp = _call(cat, _lua_pairs([(100, 1), (101, 2)]))
    st = _statuses(resp)
    assert st[(100, 1)] == "added" and st[(101, 2)] == "unverified"
    assert resp["result"]["complete"] is False


def test_collateral_change_is_reported_and_not_complete(cat):
    cat[0].execute("collateral = true")
    resp = _call(cat, _lua_pairs([(100, 1)]))
    assert _statuses(resp)[(100, 1)] == "added"
    assert list(resp["result"]["collateralPhotos"].values()) == [100]
    assert resp["result"]["complete"] is False


def test_unreadable_keywords_before_the_write_leaves_that_photo_alone(cat):
    cat[0].execute("nil_for = 100")
    resp = _call(cat, _lua_pairs([(100, 1), (101, 2)]))
    st = _statuses(resp)
    assert st[(100, 1)] == "unverified" and st[(101, 2)] == "added"
    assert cat[0].eval("names(100)") == "People"


def test_unreadable_before_stays_unverified_even_if_readable_after(cat):
    cat[0].execute("nil_once_for = 100")
    resp = _call(cat, _lua_pairs([(100, 1), (101, 2)]))
    st = _statuses(resp)
    assert st[(100, 1)] == "unverified" and st[(101, 2)] == "added"   # never "not_added": it was not attempted
    assert cat[0].eval("names(100)") == "People"


def test_wrong_catalog_is_refused_before_any_read_or_write(cat):
    resp = _call(cat, _lua_pairs([(100, 1)]), ", catalogPath = [[C:\\other\\Photos.lrcat]]")
    assert resp["error"]["code"] == "WRONG_CATALOG"
    assert cat[0].eval("reads") == 0 and cat[0].eval("writes") == 0


def test_right_catalog_matches_ignoring_case_and_slashes(cat):
    resp = _call(cat, _lua_pairs([(100, 1)]), ", catalogPath = 'c:/_/main/lightroom/catalogs/carolyn/carolyn.lrcat'")
    assert resp["result"]["added"] == 1


def test_keywords_in_tree_by_id_finds_nested_ones(cat):
    rt, module = cat
    found = module["_keywordsInTreeById"](rt.eval("CATALOG:getKeywords()"), rt.eval("{ [1] = true, [4] = true }"))
    assert sorted(found.keys()) == [1, 4] and found[1]["_name"] == "shared:with-ken"


# ---- CLI + schema --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cmd,bridge", [("batch-add-keywords", "catalog.batchAddKeywords"),
                                        ("batch-remove-keywords", "catalog.batchRemoveKeywords")])
def test_cli_reads_the_pairs_file_and_names_the_right_command(tmp_path, cmd, bridge):
    f = tmp_path / "pairs.json"
    f.write_text(json.dumps([[100, 1], {"photoId": 101, "keywordId": 2}]), encoding="utf-8")
    res = CliRunner().invoke(cli, ["-o", "json", "catalog", cmd, "--pairs-file", str(f), "--catalog-path", "C:\\x.lrcat",
                                   "--dry-run"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert out["command"] == bridge
    assert out["params"] == {"pairs": [{"photoId": 100, "keywordId": 1}, {"photoId": 101, "keywordId": 2}],
                             "catalogPath": "C:\\x.lrcat"}


def test_cli_refuses_more_than_200_pairs_before_sending(tmp_path):
    f = tmp_path / "pairs.json"
    f.write_text(json.dumps([[100, k] for k in range(1, 202)]), encoding="utf-8")
    res = CliRunner().invoke(cli, ["-o", "json", "catalog", "batch-add-keywords", "--pairs-file", str(f)])
    assert res.exit_code != 0 and "BATCH_SIZE_EXCEEDED" in res.output


def test_schema_accepts_the_params():
    from lightroom_sdk.validation import validate_params

    out = validate_params("catalog.batchAddKeywords", {"pairs": [{"photoId": 1, "keywordId": 2}], "catalogPath": "x"})
    assert out["catalogPath"] == "x"
