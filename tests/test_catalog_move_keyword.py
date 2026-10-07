"""catalog.moveKeyword -- move a keyword inside another keyword or to the top level (2026-10-07).

LrKeyword:setParent was found by `catalog probe-api` on LrC 15, undocumented, never called before this command. So the
stub's setParent can be switched to every way it might misbehave (do nothing, throw, land elsewhere, lose the photos,
change the id, leave a duplicate, queue or skip the write) and each must come back as an error naming where the
keyword really is -- never as moved=true.
"""
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from cli.main import cli

lupa = pytest.importorskip("lupa")
from tests.test_plugin_lua_unit import _load, _make_runtime  # noqa: E402

STUB = """
    unpack = unpack or table.unpack     -- LrC is Lua 5.1 (global unpack); the test runtime is 5.4
    writes, setparent_calls, last_parent_arg = 0, 0, 'unset'
    -- what setParent does: move | noop | throw | wrong | drop_photos | new_id | dup | queue | skip | swap_child |
    -- swap_photo | copy (leaves the original, makes a copy in the target) | vanish (target gone before the write)
    mode = 'move'
    TOP, KW = {}, {}
    KeywordClass = {}
    KeywordClass.__index = KeywordClass
    function KeywordClass:getName() return self._name end
    function KeywordClass:getChildren() return self._kids end
    function KeywordClass:getPhotos() return self._photos end
    local function listOf(p) return p and p._kids or TOP end
    function detach(k)
        local l = listOf(k._parent)
        for i, x in ipairs(l) do if x == k then table.remove(l, i) return end end
    end
    local function attach(k, p) k._parent = p; table.insert(listOf(p), k) end
    function mk(id, name, parent, nphotos)
        local k = setmetatable({ localIdentifier = id, _name = name, _kids = {}, _photos = {} }, KeywordClass)
        for i = 1, (nphotos or 0) do table.insert(k._photos, { localIdentifier = id * 1000 + i }) end
        KW[id] = k
        attach(k, parent)
        return k
    end
    function parent_of(id) local p = KW[id]._parent; return p and p.localIdentifier or 'top' end
    function KeywordClass:setParent(p)
        setparent_calls = setparent_calls + 1
        last_parent_arg = p and p.localIdentifier or 'nil'
        if mode == 'noop' then return end
        if mode == 'throw' then error('setParent is not supported') end
        if mode == 'copy' then mk(7777, self._name, p) return end
        detach(self)
        if mode == 'wrong' then attach(self, KW[30]) return end
        attach(self, p)
        if mode == 'drop_photos' then self._photos = {} end
        if mode == 'new_id' then KW[self.localIdentifier] = nil; self.localIdentifier = 9999; KW[9999] = self end
        if mode == 'dup' then mk(7777, self._name, nil) end
        if mode == 'swap_child' then detach(self._kids[1]); mk(8888, 'Swapped', self) end
        if mode == 'swap_photo' then self._photos[1] = { localIdentifier = 424242 } end
    end
    mk(1, 'Holiday'); mk(2, 'Thanksgiving', KW[1], 3); mk(3, 'EMM', KW[1])
    mk(10, 'Shared'); mk(11, 'shared:with-ken', KW[10], 2)
    mk(20, 'shared:cross-library', nil, 12)
    mk(30, 'Trips'); mk(31, '2004', KW[30]); mk(32, 'Valley', KW[31])
    mk(40, 'People'); mk(41, 'Wedding', KW[40]); mk(61, 'wedding')
    mk(50, 'Events'); mk(51, 'Events', KW[30])
    CATALOG = {}
    function CATALOG:getKeywords() return TOP end
    function CATALOG:getPath() return 'C:/x/Madelyn.lrcat' end
    function CATALOG:withReadAccessDo(fn) fn() end
    function CATALOG:withWriteAccessDo(_n, fn, _o)
        writes = writes + 1
        if mode == 'vanish' then detach(KW[10]) end
        if mode == 'queue' then return 'queued' end
        if mode == 'skip' then return 'aborted' end
        fn()
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


def _call(cat, params_lua):
    rt, module = cat
    captured = []
    module["moveKeyword"](rt.eval("{ " + params_lua + " }"), lambda r: captured.append(r))
    assert len(captured) == 1
    return captured[0]


def _ev(cat, expr):
    return cat[0].eval(expr)


# ---- moves that work ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("target", ["parentId = 10", "parent = 'Shared'"])
def test_moves_inside_a_parent(cat, target):
    r = _call(cat, "keywordId = 20, " + target)["result"]
    assert r["moved"] is True and r["parentId"] == 10 and r["parentName"] == "Shared"
    assert r["fromParentId"] is None and r["photoCount"] == 12 and r["childCount"] == 0
    assert r["writeStatus"] == "executed" and _ev(cat, "parent_of(20)") == 10 and _ev(cat, "last_parent_arg") == 10


def test_moves_to_the_top_level(cat):
    r = _call(cat, "keywordId = 2, toTop = true")["result"]
    assert r["moved"] is True and r["parentId"] is None and r["fromParentId"] == 1 and r["fromParentName"] == "Holiday"
    assert _ev(cat, "parent_of(2)") == "top" and _ev(cat, "last_parent_arg") == "nil"


def test_a_parent_with_children_keeps_them(cat):
    r = _call(cat, "keywordId = 31, parentId = 40")["result"]           # '2004' (holding 'Valley') into People
    assert r["moved"] is True and r["childCount"] == 1 and _ev(cat, "parent_of(32)") == 31


@pytest.mark.parametrize("params", ["keywordId = 11, parentId = 10", "keywordId = 20, toTop = true"])
def test_already_there_writes_nothing(cat, params):
    r = _call(cat, params)["result"]
    assert r["moved"] is False and "nothing changed" in r["message"]
    assert _ev(cat, "writes") == 0 and _ev(cat, "setparent_calls") == 0


# ---- refusals: nothing written --------------------------------------------------------------------------------------

@pytest.mark.parametrize("params,code,text", [
    ("keywordId = 30, parentId = 32", "INVALID_MOVE", "own descendants"),      # into its own grandchild
    ("keywordId = 30, parentId = 30", "INVALID_MOVE", "into itself"),
    ("keywordId = 999, parentId = 10", "KEYWORD_NOT_FOUND", "999"),
    ("keywordId = 20, parentId = 999", "PARENT_NOT_FOUND", "id 999"),
    ("keywordId = 20, parent = 'Events'", "PARENT_AMBIGUOUS", "names 2 keywords (ids 51, 50)"),   # tree order
    ("keywordId = 20, parent = 'SHARED'", "PARENT_NOT_FOUND", "'Shared' (id 10)"),
    ("keywordId = 41, toTop = true", "NAME_EXISTS_IN_TARGET", "'wedding' (id 61)"),   # same name, other capitals
    ("keywordId = 20", "INVALID_PARAM", "exactly one"),
    ("keywordId = 20, parentId = 10, toTop = true", "INVALID_PARAM", "exactly one"),
    ("keywordId = 20, parentId = 'x'", "INVALID_PARAM", "number"),
    ("keywordId = 20, parent = ''", "INVALID_PARAM_VALUE", "non-empty"),
    ("keywordId = 'x', parentId = 10", "MISSING_PARAM", "keywordId"),
])
def test_refusals_write_nothing(cat, params, code, text):
    err = _call(cat, params)["error"]
    assert err["code"] == code and text in err["message"], err["message"]
    assert _ev(cat, "writes") == 0 and _ev(cat, "setparent_calls") == 0


def test_a_same_named_keyword_in_the_target_is_refused(cat):
    cat[0].execute("mk(60, 'SHARED:Cross-Library', KW[10])")
    err = _call(cat, "keywordId = 20, parentId = 10")["error"]
    assert err["code"] == "NAME_EXISTS_IN_TARGET" and "(id 60)" in err["message"] and _ev(cat, "writes") == 0


def test_the_wrong_catalog_is_refused(cat):
    err = _call(cat, "keywordId = 20, parentId = 10, catalogPath = 'C:/x/Photos.lrcat'")["error"]
    assert err["code"] == "WRONG_CATALOG" and _ev(cat, "writes") == 0
    assert _call(cat, "keywordId = 20, parentId = 10, catalogPath = 'C:\\\\x\\\\Madelyn.lrcat'")["result"]["moved"]


# ---- setParent misbehaving: never moved=true, always where it really is -----------------------------------------------

@pytest.mark.parametrize("mode,code,text", [
    ("noop", "PLACEMENT_MISMATCH", "is under the top level, not 'Shared' (id 10)"),
    ("wrong", "PLACEMENT_MISMATCH", "is under 'Trips' (id 30)"),
    ("throw", "OPERATION_FAILED", "setParent failed"),
    ("drop_photos", "MOVE_CHANGED_KEYWORD", "photos 12 -> 0"),
    ("new_id", "KEYWORD_LOST", "no longer in the tree"),
    ("dup", "MOVE_CHANGED_KEYWORD", "keywords with this name 1 -> 2"),
    ("queue", "OPERATION_FAILED", "queued"),
    ("skip", "OPERATION_FAILED", "did not run"),
    ("swap_photo", "MOVE_CHANGED_KEYWORD", "photos 12 -> 12 (not the same photos)"),     # same count, other photo
    ("copy", "PLACEMENT_MISMATCH", "'shared:cross-library': 1 -> 2 (a copy may have been made)"),
    ("vanish", "OPERATION_FAILED", "vanished before setParent was called"),
])
def test_a_misbehaving_setparent_is_an_error_naming_where_it_is(cat, mode, text, code):
    cat[0].execute(f"mode = '{mode}'")
    err = _call(cat, "keywordId = 20, parentId = 10")["error"]
    assert err["code"] == code and text in err["message"], err["message"]


def test_a_failed_setparent_still_reports_where_the_keyword_is(cat):
    cat[0].execute("mode = 'throw'")
    msg = _call(cat, "keywordId = 2, parentId = 10")["error"]["message"]
    assert "Read back: 'Thanksgiving' is under 'Holiday' (id 1)" in msg


def test_find_keyword_with_parent(cat):
    rt, module = cat
    kw, parent = module["_findKeywordWithParent"](rt.eval("TOP"), 32)
    assert kw["localIdentifier"] == 32 and parent["localIdentifier"] == 31
    kw, parent = module["_findKeywordWithParent"](rt.eval("TOP"), 20)
    assert kw["localIdentifier"] == 20 and parent is None
    assert module["_findKeywordWithParent"](rt.eval("TOP"), 999) is None


# ---- CLI + schema -------------------------------------------------------------------------------------------------

def test_cli_and_schema():
    from lightroom_sdk.validation import validate_params

    assert validate_params("catalog.moveKeyword", {"keywordId": 5, "toTop": True}) == {"keywordId": 5, "toTop": True}
    cases = [
        (["20", "--parent-id", "10"], {"keywordId": 20, "parentId": 10}),
        (["20", "--parent", "Shared", "--catalog-path", "C:/x.lrcat"],
         {"keywordId": 20, "parent": "Shared", "catalogPath": "C:/x.lrcat"}),
        (["2", "--to-top"], {"keywordId": 2, "toTop": True}),
    ]
    for args, sent in cases:
        bridge = AsyncMock()
        bridge.send_command.return_value = {"success": True, "result": {"moved": True}}
        with patch("cli.helpers.get_bridge", return_value=bridge):
            res = CliRunner().invoke(cli, ["-o", "json", "catalog", "move-keyword", *args])
        assert res.exit_code == 0, res.output
        assert bridge.send_command.call_args.args[1] == sent


def test_a_swapped_child_is_caught_although_the_count_is_the_same(cat):
    cat[0].execute("mode = 'swap_child'")
    err = _call(cat, "keywordId = 31, parentId = 40")["error"]      # '2004' holds 'Valley'; setParent swaps it
    assert err["code"] == "MOVE_CHANGED_KEYWORD" and "child keywords 1 -> 1 (not the same children)" in err["message"]


def test_id_sets(cat):
    rt, module = cat
    a, na = module["_idSet"](rt.eval("{ {localIdentifier=1}, {localIdentifier=2}, {localIdentifier=2} }"))
    b, nb = module["_idSet"](rt.eval("{ {localIdentifier=2}, {localIdentifier=1} }"))
    c, nc = module["_idSet"](rt.eval("{ {localIdentifier=1}, {localIdentifier=3} }"))
    assert na == 2 and module["_sameIdSet"](a, na, b, nb) and not module["_sameIdSet"](a, na, c, nc)
