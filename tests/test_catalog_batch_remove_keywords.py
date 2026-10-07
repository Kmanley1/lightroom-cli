"""catalog.batchRemoveKeywords -- remove keywords (by id) from photos, up to 200 pairs in one write.

Lua handler tests run the real plugin code against a stub catalog that models LrC: photo:removeKeyword edits the
photo's keyword list; a write can run, abort (LrC returns without running the closure on a lock timeout) or throw;
a removal can be silently ignored; the read-back can fail. Every pair's status must come from the reads, so none of
those can report "removed". Plus SDK round-trip tests via mock_lr_server.
"""
import pytest

from lightroom_sdk.client import LightroomClient

lupa = pytest.importorskip("lupa")
from tests.test_plugin_lua_unit import _load, _make_runtime  # noqa: E402

STUB = """
    unpack = unpack or table.unpack
    writes, reads = 0, 0
    write_mode = 'run'          -- 'abort' | 'throw'
    ignore_remove = false       -- removeKeyword runs but LrC keeps the keyword
    read_fail_after_write = false
    vanish_on_write = nil       -- a photo id removed from the catalog during the write
    collateral = false          -- removeKeyword also takes the photo's next keyword (a hypothetical LrC side effect)
    nil_after_write = false     -- getRawMetadata('keywords') returns nil once a write has run
    nil_for = nil               -- a photo id whose getRawMetadata('keywords') is always nil
    open_path = [[C:\\_\\main\\LightRoom\\Catalogs\\Carolyn\\Carolyn.lrcat]]
    remove_calls = 0
    local function mkkw(id, name)
        local k = { localIdentifier = id, _name = name }
        function k:getName() return self._name end
        return k
    end
    K = { [1] = mkkw(1, '2013_11_14'), [2] = mkkw(2, '2013'), [3] = mkkw(3, 'WP_x.jpg'), [4] = mkkw(4, 'Wedding') }
    local function mkphoto(id, kws)
        local p = { _kws = kws }
        function p:getRawMetadata(key)
            if key == 'uuid' then return 'UUID' end      -- every real photo has one
            if key ~= 'keywords' then return nil end
            if nil_after_write and writes > 0 then return nil end
            if nil_for and PHOTOS[nil_for] == self then return nil end
            local c = {}
            for i, k in ipairs(self._kws) do c[i] = k end
            return c
        end
        function p:removeKeyword(kw)
            remove_calls = remove_calls + 1
            if ignore_remove then return end
            for i, k in ipairs(self._kws) do
                if k == kw then
                    table.remove(self._kws, i)
                    if collateral and self._kws[i] then table.remove(self._kws, i) end
                    return
                end
            end
        end
        return p
    end
    PHOTOS = { [100] = mkphoto(100, { K[1], K[2], K[4] }), [101] = mkphoto(101, { K[1], K[3] }) }
    function names(id)
        local out = {}
        for _, k in ipairs(PHOTOS[id]._kws) do table.insert(out, k:getName()) end
        return table.concat(out, ',')
    end
    CATALOG = {}
    function CATALOG:getPath() return open_path end
    throw_for_missing = false   -- unknown id: throw at the lookup (NOT what LrC does; kept to test the error path)
    DUD = {}                    -- what LrC returns for an unknown id (measured live 2026-10-07 with probe-photo)
    function DUD:getRawMetadata(key)
        if key == 'uuid' or key == 'path' then return nil end
        error('?:0: attempt to index a nil value')
    end
    function DUD:getFormattedMetadata() error('?:0: attempt to index a nil value') end
    lookup_fail_for = nil       -- a photo id whose lookup fails for a reason OTHER than not-found
    function CATALOG:getPhotoByLocalId(id)
        -- an id that is not in the catalog: LrC returns a DUD object (measured live 2026-10-07 with probe-photo),
        -- not nil; the 10-06 note that it THROWS was wrong (the throw came from the first read of the dud)
        if lookup_fail_for and id == lookup_fail_for then error('catalog busy') end
        local p = PHOTOS[id]
        if p == nil then
            if throw_for_missing then error('?:0: attempt to index a nil value') end   -- not seen live
            return DUD       -- what LrC does (live 2026-10-07): a dud object, uuid/path nil, other reads throw
        end
        return p
    end
    function CATALOG:withReadAccessDo(fn)
        reads = reads + 1
        if read_fail_after_write and writes > 0 then error('read busy') end
        fn()
    end
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
    module["batchRemoveKeywords"](params, lambda r: captured.append(r))
    assert len(captured) == 1  # exactly one response, always
    return captured[0]


def _statuses(resp):
    res = resp["result"]["results"]
    return {(int(res[i]["photoId"]), int(res[i]["keywordId"])): res[i]["status"] for i in range(1, len(res) + 1)}


# ---- validation --------------------------------------------------------------------------------------------------

def test_missing_pairs(cat):
    assert _call(cat, None)["error"]["code"] == "MISSING_PARAM"
    assert _call(cat, "{}")["error"]["code"] == "MISSING_PARAM"


def test_non_numeric_pair(cat):
    resp = _call(cat, "{ {photoId = 100, keywordId = 'x'} }")
    assert resp["error"]["code"] == "INVALID_PARAM_VALUE"
    assert cat[0].eval("writes") == 0


def test_more_than_200_distinct_pairs(cat):
    resp = _call(cat, _lua_pairs([(100, k) for k in range(1, 202)]))
    assert resp["error"]["code"] == "BATCH_SIZE_EXCEEDED"
    assert cat[0].eval("writes") == 0


def test_duplicates_collapse_and_200_is_allowed(cat):
    resp = _call(cat, _lua_pairs([(100, 1)] * 5 + [(100, k) for k in range(1000, 1199)]))
    assert resp["success"] is True
    assert resp["result"]["requested"] == 200


# ---- outcomes ----------------------------------------------------------------------------------------------------

def test_removes_only_the_requested_keywords(cat):
    resp = _call(cat, _lua_pairs([(100, 1), (100, 2), (101, 1)]))
    r = resp["result"]
    assert (r["removed"], r["stillPresent"], r["unverified"], r["complete"], r["writeRan"]) == (3, 0, 0, True, True)
    assert cat[0].eval("names(100)") == "Wedding"
    assert cat[0].eval("names(101)") == "WP_x.jpg"
    assert set(_statuses(resp).values()) == {"removed"}


def test_not_on_photo_and_photo_not_found(cat):
    resp = _call(cat, _lua_pairs([(100, 3), (999, 1), (101, 3)]))
    st = _statuses(resp)
    assert st[(100, 3)] == "not_on_photo"
    assert st[(999, 1)] == "photo_not_found"
    assert st[(101, 3)] == "removed"
    r = resp["result"]
    # complete is False since 2026-10-07: "not found" rests on LrC's error text, so it may never read as done
    assert (r["removed"], r["notOnPhoto"], r["photoNotFound"], r["complete"]) == (1, 1, 1, False)


def test_aborted_write_reports_still_present(cat):
    cat[0].execute("write_mode = 'abort'")
    resp = _call(cat, _lua_pairs([(100, 1), (101, 1)]))
    r = resp["result"]
    assert (r["removed"], r["stillPresent"], r["complete"], r["writeRan"]) == (0, 2, False, False)
    assert cat[0].eval("names(100)") == "2013_11_14,2013,Wedding"


def test_throwing_write_reports_still_present_and_the_error(cat):
    cat[0].execute("write_mode = 'throw'")
    resp = _call(cat, _lua_pairs([(100, 1)]))
    r = resp["result"]
    assert (r["removed"], r["stillPresent"], r["complete"]) == (0, 1, False)
    assert "write lock timeout" in r["writeError"]


def test_removal_lrc_ignores_reports_still_present(cat):
    cat[0].execute("ignore_remove = true")
    resp = _call(cat, _lua_pairs([(100, 1)]))
    r = resp["result"]
    assert (r["removed"], r["stillPresent"], r["complete"], r["writeRan"]) == (0, 1, False, True)
    assert cat[0].eval("remove_calls") == 1


def test_failed_read_back_reports_unverified(cat):
    cat[0].execute("read_fail_after_write = true")
    resp = _call(cat, _lua_pairs([(100, 1), (100, 3)]))
    st = _statuses(resp)
    assert st[(100, 1)] == "unverified"
    assert st[(100, 3)] == "not_on_photo"
    assert resp["result"]["complete"] is False


def test_photo_gone_after_the_write_reports_unverified(cat):
    cat[0].execute("vanish_on_write = 101")
    resp = _call(cat, _lua_pairs([(100, 1), (101, 1)]))
    st = _statuses(resp)
    assert st[(100, 1)] == "removed"
    assert st[(101, 1)] == "unverified"
    assert resp["result"]["complete"] is False


@pytest.mark.parametrize("throws,status", [(False, "photo_not_found"), (True, "unverified")])
def test_a_stale_id_does_not_fail_the_whole_batch(cat, throws, status):
    # LrC returns a dud object for an unknown id (live 2026-10-07): photo_not_found. A lookup that THROWS was never
    # seen; it must stay unverified, never photo_not_found. Either way the other pair goes through.
    cat[0].execute(f"throw_for_missing = {'true' if throws else 'false'}")
    resp = _call(cat, _lua_pairs([(0, 1), (100, 1)]))
    st = _statuses(resp)
    assert st[(0, 1)] == status and st[(100, 1)] == "removed"


def test_a_lookup_that_fails_otherwise_is_unverified_never_photo_not_found(cat):
    # photo_not_found counts as done for a removal; a busy catalog must not
    cat[0].execute("lookup_fail_for = 100")
    resp = _call(cat, _lua_pairs([(100, 1), (101, 1)]))
    st = _statuses(resp)
    assert st[(100, 1)] == "unverified" and st[(101, 1)] == "removed"
    assert resp["result"]["complete"] is False
    assert cat[0].eval("names(100)") == "2013_11_14,2013,Wedding"


def test_wrong_catalog_is_refused_before_any_read_or_write(cat):
    resp = _call(cat, _lua_pairs([(100, 1)]), ", catalogPath = 'C:/_/main/LightRoom/Catalogs/Ethan/Ethan.lrcat'")
    assert resp["error"]["code"] == "WRONG_CATALOG"
    assert (cat[0].eval("writes"), cat[0].eval("reads")) == (0, 0)
    assert cat[0].eval("names(100)") == "2013_11_14,2013,Wedding"


def test_right_catalog_matches_ignoring_case_and_slashes(cat):
    resp = _call(cat, _lua_pairs([(100, 1)]), ", catalogPath = 'c:/_/MAIN/LightRoom/Catalogs/Carolyn/Carolyn.lrcat'")
    assert resp["result"]["removed"] == 1


def test_collateral_removal_is_reported_and_not_complete(cat):
    cat[0].execute("collateral = true")
    resp = _call(cat, _lua_pairs([(100, 1)]))
    r = resp["result"]
    assert r["removed"] == 1
    assert [int(x) for x in r["collateralPhotos"].values()] == [100]
    assert r["complete"] is False


def test_unreadable_keywords_after_the_write_is_unverified_not_removed(cat):
    cat[0].execute("nil_after_write = true")
    resp = _call(cat, _lua_pairs([(100, 1), (101, 1)]))
    r = resp["result"]
    assert (r["removed"], r["unverified"], r["complete"]) == (0, 2, False)


def test_unreadable_keywords_before_the_write_leaves_that_photo_alone(cat):
    cat[0].execute("nil_for = 101")
    resp = _call(cat, _lua_pairs([(100, 1), (101, 1)]))
    st = _statuses(resp)
    assert st[(100, 1)] == "removed"
    assert st[(101, 1)] == "unverified"
    assert resp["result"]["complete"] is False
    cat[0].execute("nil_for = nil")
    assert cat[0].eval("names(101)") == "2013_11_14,WP_x.jpg"  # untouched


def test_no_write_when_nothing_requested_is_on_a_photo(cat):
    resp = _call(cat, _lua_pairs([(100, 3), (999, 1)]))
    r = resp["result"]
    assert (r["writeRan"], r["complete"]) == (False, False)      # 999 not found: never "complete" (2026-10-07)
    assert cat[0].eval("writes") == 0
    resp = _call(cat, _lua_pairs([(100, 3)]))                    # only not_on_photo: nothing to do, complete
    assert (resp["result"]["writeRan"], resp["result"]["complete"]) == (False, True)


def test_one_write_transaction_for_the_whole_batch(cat):
    _call(cat, _lua_pairs([(100, 1), (100, 2), (101, 1), (101, 3)]))
    assert cat[0].eval("writes") == 1


# ---- pure helpers ------------------------------------------------------------------------------------------------

def test_group_keyword_pairs_keeps_first_seen_order(cat):
    rt, module = cat
    groups, n = module["_groupKeywordPairs"](rt.eval(_lua_pairs([(5, 9), (3, 1), (5, 2), (5, 9)])), 200)
    assert n == 3
    assert [int(groups[i]["photoId"]) for i in range(1, len(groups) + 1)] == [5, 3]
    ids5 = groups[1]["keywordIds"]
    assert [int(ids5[i]) for i in range(1, len(ids5) + 1)] == [9, 2]


def test_keywords_by_id(cat):
    rt, module = cat
    found = module["_keywordsById"](rt.eval("{ K[1], K[3] }"), rt.eval("{ 3, 4 }"))
    assert found[3] is not None and found[4] is None and found[1] is None


# ---- SDK round trip ----------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sdk_round_trip(mock_lr_server):
    mock_lr_server.register_response(
        "catalog.batchRemoveKeywords",
        {"requested": 2, "removed": 2, "notOnPhoto": 0, "photoNotFound": 0, "stillPresent": 0, "unverified": 0,
         "complete": True, "writeRan": True,
         "results": [{"photoId": 1, "keywordId": 7, "status": "removed"},
                     {"photoId": 2, "keywordId": 7, "status": "removed"}]},
    )
    async with LightroomClient(port_file=str(mock_lr_server.port_file)) as client:
        result = await client.execute_command(
            "catalog.batchRemoveKeywords", {"pairs": [{"photoId": 1, "keywordId": 7}, {"photoId": 2, "keywordId": 7}]}
        )
    assert result["complete"] is True and result["removed"] == 2
