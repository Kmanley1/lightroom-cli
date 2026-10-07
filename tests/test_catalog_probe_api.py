"""catalog.probeApi -- the read-only diagnostic that lists the methods Lightroom exposes (2026-10-07).

Built to settle whether the SDK can delete a keyword before anyone builds `delete-keyword`. What must hold: it lists
inherited methods (SDK classes chain through metatables), says how much it could see (`indexKind`), finds a candidate
name even behind a computed __index, reports a lookup that throws as an error rather than as "absent" -- and it
never CALLS a method it finds and never opens a write.
"""
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from cli.main import cli

lupa = pytest.importorskip("lupa")
from tests.test_plugin_lua_unit import _load, _make_runtime  # noqa: E402

STUB = """
    unpack = unpack or table.unpack     -- LrC is Lua 5.1 (global unpack); the test runtime is 5.4
    writes = 0
    calls = {}                          -- every stub method a probe must NOT call records itself here
    function mark(name) return function() calls[name] = (calls[name] or 0) + 1 end end
    read_fails = false
    Base = { getPath = mark('getPath') }                                  -- an inherited method, two levels up
    CatalogClass = setmetatable({ createKeyword = mark('createKeyword') }, { __index = Base })
    function CatalogClass:withReadAccessDo(fn) if read_fails then error('catalog busy') end fn() end
    function CatalogClass:withWriteAccessDo(_n, fn) writes = writes + 1; fn() end
    function CatalogClass:getKeywords() return TOP end
    KeywordClass = { addSynonym = mark('addSynonym'), getAttributes = mark('getAttributes') }
    function KeywordClass:getName() return self._name end
    function KeywordClass:getChildren() return self._kids end
    local function mkkw(id, name, kids)
        return setmetatable({ localIdentifier = id, _name = name, _kids = kids or {} }, { __index = KeywordClass })
    end
    TOP = { mkkw(10, 'Holiday', { mkkw(11, 'Thanksgiving') }), mkkw(20, 'Shared') }
    CATALOG = setmetatable({}, { __index = CatalogClass })
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


def _call(cat, params_lua="{}"):
    rt, module = cat
    captured = []
    module["probeApi"](rt.eval(params_lua), lambda r: captured.append(r))
    assert len(captured) == 1
    assert rt.eval("writes") == 0                                   # never opens a write
    return captured[0]


def _objects(resp):
    objs = resp["result"]["objects"]
    out = {}
    for i in range(1, len(objs) + 1):
        o = objs[i]
        out[o["object"]] = {
            "indexKind": o["indexKind"],
            "methods": [o["methods"][j] for j in range(1, len(o["methods"]) + 1)],
            "candidates": dict(o["candidates"].items()),
            "errors": [o["errors"][j] for j in range(1, len(o["errors"]) + 1)],
            "blind": [o["blind"][j] for j in range(1, len(o["blind"]) + 1)],
            "knownMissing": [o["knownMissing"][j] for j in range(1, len(o["knownMissing"]) + 1)],
            "suspicious": [o["suspicious"][j] for j in range(1, len(o["suspicious"]) + 1)],
            "listingComplete": o["listingComplete"],
        }
    return out


def _never_called(cat):
    assert dict(cat[0].eval("calls").items()) == {}


def test_lists_own_and_inherited_methods_and_calls_none(cat):
    resp = _call(cat)
    objs = _objects(resp)
    c = objs["catalog"]
    assert c["indexKind"] == "table"
    for m in ("createKeyword", "getKeywords", "withReadAccessDo", "withWriteAccessDo", "getPath"):
        assert m in c["methods"], m
    assert c["candidates"]["deleteKeyword"] == "nil" and c["candidates"]["delete"] == "nil"
    assert c["listingComplete"] is True and c["blind"] == [] and c["suspicious"] == []
    k = objs["keyword"]
    assert {"getName", "getChildren", "addSynonym"} <= set(k["methods"]) and k["listingComplete"] is True
    assert resp["result"]["keywordId"] == 10 and resp["result"]["keywordName"] == "Holiday"
    _never_called(cat)


def test_a_delete_method_is_found_and_not_called(cat):
    cat[0].execute("CatalogClass.deleteKeyword = mark('deleteKeyword'); KeywordClass.delete = mark('kwDelete')")
    objs = _objects(_call(cat))
    assert objs["catalog"]["candidates"]["deleteKeyword"] == "function" and "deleteKeyword" in objs["catalog"]["methods"]
    assert objs["keyword"]["candidates"]["delete"] == "function"
    assert objs["catalog"]["suspicious"] == ["deleteKeyword"] and objs["keyword"]["suspicious"] == ["delete"]
    _never_called(cat)


def test_a_computed_index_is_reported_and_candidates_still_found(cat):
    cat[0].execute("""
        DK = mark('deleteKeyword')
        CATALOG = setmetatable({}, { __index = function(_, k)
            if k == 'deleteKeyword' then return DK end
            return CatalogClass[k]
        end })""")
    c = _objects(_call(cat))["catalog"]
    assert c["indexKind"] == "function"                  # the listing could not see inside: methods are incomplete
    assert c["listingComplete"] is False and "computed __index (function) at depth 0" in c["blind"]
    assert c["candidates"]["deleteKeyword"] == "function"
    _never_called(cat)


def test_a_lookup_that_throws_is_an_error_not_absent(cat):
    cat[0].execute("""
        CATALOG = setmetatable({}, { __index = function(_, k)
            local v = CatalogClass[k]
            if v == nil then error('undefined member ' .. k) end
            return v
        end })""")
    c = _objects(_call(cat))["catalog"]
    assert c["candidates"]["deleteKeyword"].startswith("lookup error:")
    assert "undefined member deleteKeyword" in c["candidates"]["deleteKeyword"]


def test_a_protected_metatable_is_reported(cat):
    cat[0].execute("CATALOG = setmetatable({}, { __index = CatalogClass, __metatable = 'locked' })")
    c = _objects(_call(cat))["catalog"]
    assert c["indexKind"] == "hidden metatable (string)" and c["methods"] == [] and c["listingComplete"] is False
    assert c["candidates"]["deleteKeyword"] == "nil"     # direct lookups still go through the real __index


def test_a_nested_keyword_by_id(cat):
    resp = _call(cat, "{ keywordId = 11 }")
    assert resp["result"]["keywordId"] == 11 and resp["result"]["keywordName"] == "Thanksgiving"


@pytest.mark.parametrize("params,code", [("{ keywordId = 999 }", "KEYWORD_NOT_FOUND"),
                                         ("{ keywordId = 'x' }", "INVALID_PARAM")])
def test_bad_keyword_ids(cat, params, code):
    assert _call(cat, params)["error"]["code"] == code


def test_a_failed_read_transaction_is_operation_failed(cat):
    cat[0].execute("read_fails = true")
    resp = _call(cat)
    assert resp["error"]["code"] == "OPERATION_FAILED" and "catalog busy" in resp["error"]["message"]


def test_cli_and_schema():
    from lightroom_sdk.validation import validate_params

    assert validate_params("catalog.probeApi", {}) == {}
    assert validate_params("catalog.probeApi", {"keywordId": 5}) == {"keywordId": 5}
    res = CliRunner().invoke(cli, ["-o", "json", "catalog", "probe-api", "--help"])
    assert res.exit_code == 0 and "read-only" in res.output
    for args, sent in ((["--keyword-id", "5"], {"keywordId": 5}), ([], {})):
        bridge = AsyncMock()
        bridge.send_command.return_value = {"success": True, "result": {"objects": []}}
        with patch("cli.helpers.get_bridge", return_value=bridge):
            res = CliRunner().invoke(cli, ["-o", "json", "catalog", "probe-api", *args])
        assert res.exit_code == 0, res.output
        assert bridge.send_command.call_args.args[1] == sent


# ---- blind spots the 2026-10-07 review reproduced: each must make the listing say it is NOT complete -----------------

def test_a_computed_index_one_level_down_is_blind(cat):
    cat[0].execute("""
        Lazy = setmetatable({ createKeyword = mark('createKeyword') }, { __index = function(_, k) return CatalogClass[k] end })
        CATALOG = setmetatable({}, { __index = Lazy })""")
    c = _objects(_call(cat))["catalog"]
    assert c["indexKind"] == "table" and c["listingComplete"] is False
    assert "computed __index (function) at depth 1" in c["blind"] and "getKeywords" in c["knownMissing"]


def test_a_chain_past_the_depth_cap_is_blind(cat):
    cat[0].execute("""
        local top = CatalogClass
        for _ = 1, 10 do top = setmetatable({}, { __index = top }) end
        CATALOG = setmetatable({}, { __index = top })""")
    c = _objects(_call(cat))["catalog"]
    assert c["listingComplete"] is False and any("depth cap" in b for b in c["blind"])


def test_a_hidden_table_metatable_is_caught_by_the_known_methods(cat):
    cat[0].execute("CATALOG = setmetatable({}, { __index = CatalogClass, __metatable = {} })")
    c = _objects(_call(cat))["catalog"]
    assert c["listingComplete"] is False and "createKeyword" in c["knownMissing"]


def test_a_callable_table_is_listed_and_metamethods_are_not(cat):
    cat[0].execute("""
        CatalogClass.deleteKeyword = setmetatable({}, { __call = mark('deleteKeyword') })
        CatalogClass.__tostring = function() return 'catalog' end""")
    c = _objects(_call(cat))["catalog"]
    assert "deleteKeyword" in c["methods"] and c["candidates"]["deleteKeyword"] == "table"
    assert "__tostring" not in c["methods"] and c["suspicious"] == ["deleteKeyword"]
    _never_called(cat)


def test_a_hidden_base_class_is_blind_even_when_every_known_method_shows(cat):
    # the case that matters most: the documented methods are all visible, but a base class sits behind a computed
    # __index -- a delete method there would be missed, so the listing must still say it is not complete
    cat[0].execute("setmetatable(CatalogClass, { __index = function(_, k) return Base[k] end })")
    c = _objects(_call(cat))["catalog"]
    assert c["knownMissing"] == [] and "getPath" not in c["methods"]
    assert c["listingComplete"] is False and "computed __index (function) at depth 1" in c["blind"]
