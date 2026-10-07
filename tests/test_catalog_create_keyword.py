"""catalog.createKeyword -- create a keyword, optionally INSIDE an existing parent (2026-10-06).

Lua handler tests run the real plugin code against a stub catalog that models LrC's keyword tree: createKeyword is
parent-scoped for returnIfExists, and with parent=nil it puts the keyword under the last-selected keyword (the real
quirk, memory reference_lrc_keyword_sdk_constraints). A write can run, abort or throw; the stub can misplace a
keyword or create nothing. The response's placement must come from reading the tree back, never from the request.
Plus CLI option mapping (via --dry-run) and schema validation.
"""
import json

import pytest
from click.testing import CliRunner

from cli.main import cli

lupa = pytest.importorskip("lupa")
from tests.test_plugin_lua_unit import _load, _make_runtime  # noqa: E402

STUB = """
    unpack = unpack or table.unpack
    writes, reads = 0, 0
    write_mode = 'run'              -- 'abort' | 'throw' | 'queued' (LrC returns 'queued' and runs it later)
    attrs_fail = false              -- getAttributes() throws
    nil_parent_lands_under = nil    -- LrC's quirk: parent=nil puts the keyword under this (last-selected) keyword
    misplace_under = nil            -- a keyword, or 'top': where the stub puts it EVEN WITH an explicit parent
    create_noop = false             -- createKeyword returns but adds nothing
    open_path = [[C:\\_\\main\\LightRoom\\Catalogs\\Carolyn\\Carolyn.lrcat]]
    next_id = 1000
    created_args = nil
    function mkkw(id, name)
        local k = { localIdentifier = id, _name = name, _children = {}, _inc = true }
        function k:getName() return self._name end
        function k:getChildren() local c = {} for i, x in ipairs(self._children) do c[i] = x end return c end
        function k:getAttributes()
            if attrs_fail then error('attributes unavailable') end
            return { keywordName = self._name, includeOnExport = self._inc }
        end
        return k
    end
    TOP = {}
    function add(parent, kw) table.insert(parent and parent._children or TOP, kw) return kw end
    SHARED = add(nil, mkkw(10, 'Shared'))
    add(nil, mkkw(11, 'shared:cross-library'))
    WITHKEN = add(SHARED, mkkw(12, 'shared:with-ken'))
    PEOPLE = add(nil, mkkw(20, 'People'))
    add(PEOPLE, mkkw(21, 'Dup'))
    FAMILY = add(nil, mkkw(30, 'Family'))
    add(FAMILY, mkkw(31, 'Dup'))
    -- "parent-name/name" for every keyword called `name`, or "top/name"; in tree order
    function places(name)
        local out = {}
        local function walk(list, pname)
            for _, k in ipairs(list) do
                if k._name == name then table.insert(out, (pname or 'top') .. '/' .. k._name) end
                walk(k._children, k._name)
            end
        end
        walk(TOP, nil)
        return table.concat(out, ',')
    end
    CATALOG = {}
    function CATALOG:getPath() return open_path end
    function CATALOG:getKeywords() local c = {} for i, x in ipairs(TOP) do c[i] = x end return c end
    function CATALOG:createKeyword(name, synonyms, includeOnExport, parent, returnIfExists)
        created_args = { name = name, inc = includeOnExport, parent = parent and parent.localIdentifier or 'nil',
                         rif = returnIfExists }
        local siblings = parent and parent._children or TOP
        if returnIfExists then
            for _, k in ipairs(siblings) do if k._name == name then return k end end
        end
        if create_noop then return nil end
        next_id = next_id + 1
        local kw = mkkw(next_id, name)
        kw._inc = includeOnExport
        local target = parent
        if parent == nil and nil_parent_lands_under then target = nil_parent_lands_under end
        if misplace_under == 'top' then target = nil elseif misplace_under then target = misplace_under end
        add(target, kw)
        return kw
    end
    function CATALOG:withReadAccessDo(fn) reads = reads + 1; fn() end
    function CATALOG:withWriteAccessDo(_name, fn, _opts)
        writes = writes + 1
        if write_mode == 'throw' then error('write lock timeout') end
        if write_mode == 'abort' then return 'aborted' end
        if write_mode == 'queued' then queued_fn = fn; return 'queued' end
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
    module["createKeyword"](rt.eval("{ " + params_lua + " }"), lambda r: captured.append(r))
    assert len(captured) == 1  # exactly one response, always
    return captured[0]


def _ok(resp):
    assert resp["success"] is True, dict(resp["error"]) if resp["error"] else resp
    return resp["result"]


def _err(resp):
    assert resp["success"] is False
    return resp["error"]["code"], resp["error"]["message"]


# ---- creating in the right place ---------------------------------------------------------------------------------

def test_creates_inside_the_parent_given_by_id(cat):
    r = _ok(_call(cat, "keyword = 'shared:with-carolyn', parentId = 10"))
    assert (r["created"], r["parentId"], r["parentName"], r["placement"]) == (True, 10, "Shared", "as_requested")
    assert r["includeOnExport"] is True
    assert cat[0].eval("places('shared:with-carolyn')") == "Shared/shared:with-carolyn"
    args = cat[0].eval("created_args")
    assert (args["parent"], args["inc"], args["rif"]) == (10, True, True)
    assert cat[0].eval("writes") == 1


def test_creates_inside_the_parent_given_by_its_exact_name(cat):
    r = _ok(_call(cat, "keyword = 'shared:with-ethan', parent = 'Shared'"))
    assert (r["parentId"], r["placement"]) == (10, "as_requested")
    assert cat[0].eval("places('shared:with-ethan')") == "Shared/shared:with-ethan"


def test_include_on_export_false_is_passed_through(cat):
    r = _ok(_call(cat, "keyword = 'shared:with-madelyn', parentId = 10, includeOnExport = false"))
    assert r["includeOnExport"] is False and cat[0].eval("created_args.inc") is False


def test_already_there_returns_it_without_a_write(cat):
    r = _ok(_call(cat, "keyword = 'shared:with-ken', parentId = 10"))
    assert (r["created"], r["id"], r["parentName"]) == (False, 12, "Shared")
    assert cat[0].eval("writes") == 0


def test_no_parent_and_already_at_the_top_returns_it(cat):
    r = _ok(_call(cat, "keyword = 'People'"))
    assert (r["created"], r["id"], r["parentId"], r["placement"]) == (False, 20, None, "unrequested")
    assert cat[0].eval("writes") == 0


def test_no_parent_reports_where_lightroom_really_put_it(cat):
    cat[0].execute("nil_parent_lands_under = PEOPLE")       # the real quirk: last-selected keyword
    r = _ok(_call(cat, "keyword = 'Newbie'"))
    assert (r["created"], r["placement"], r["parentId"], r["parentName"]) == (True, "unrequested", 20, "People")
    assert cat[0].eval("created_args.parent") == "nil"


# ---- refusals: nothing written -----------------------------------------------------------------------------------

@pytest.mark.parametrize("params,code", [
    ("parent = 'Dup', keyword = 'x'", "PARENT_AMBIGUOUS"),
    ("parent = 'Nope', keyword = 'x'", "PARENT_NOT_FOUND"),
    ("parent = 'shared', keyword = 'x'", "PARENT_NOT_FOUND"),          # exact name: capitals matter
    ("parentId = 999, keyword = 'x'", "PARENT_NOT_FOUND"),
    ("parentId = 10, parent = 'Shared', keyword = 'x'", "INVALID_PARAM"),
    ("parentId = 'ten', keyword = 'x'", "INVALID_PARAM"),
    ("keyword = 'shared:cross-library', parentId = 10", "KEYWORD_EXISTS_ELSEWHERE"),   # it sits at the top level
    ("keyword = 'Shared:With-Ken', parentId = 20", "KEYWORD_EXISTS_ELSEWHERE"),        # any capitals
    ("keyword = 'Dup'", "KEYWORD_EXISTS_ELSEWHERE"),
    ("parentId = 10", "MISSING_PARAM"),
    ("keyword = '   '", "INVALID_PARAM_VALUE"),
    ("keyword = ' lead'", "INVALID_PARAM_VALUE"),
    ("keyword = 'tab\\there'", "INVALID_PARAM_VALUE"),
    ("keyword = 'x', parent = ''", "INVALID_PARAM_VALUE"),
])
def test_refusals_write_nothing(cat, params, code):
    got, _ = _err(_call(cat, params))
    assert got == code
    assert cat[0].eval("writes") == 0 and cat[0].eval("created_args") is None


def test_ambiguous_parent_lists_the_ids(cat):
    _, msg = _err(_call(cat, "parent = 'Dup', keyword = 'x'"))
    assert "21" in msg and "31" in msg and "parentId" in msg


def test_duplicate_name_can_be_allowed_explicitly(cat):
    r = _ok(_call(cat, "keyword = 'shared:cross-library', parentId = 10, allowDuplicateName = true"))
    assert r["created"] is True
    assert set(cat[0].eval("places('shared:cross-library')").split(",")) == {
        "top/shared:cross-library", "Shared/shared:cross-library"}


def test_wrong_catalog_is_refused(cat):
    got, _ = _err(_call(cat, "keyword = 'x', parentId = 10, catalogPath = [[C:\\other\\Photos.lrcat]]"))
    assert got == "WRONG_CATALOG" and cat[0].eval("reads") == 0 and cat[0].eval("writes") == 0


def test_right_catalog_matches_ignoring_case_and_slashes(cat):
    _ok(_call(cat, "keyword = 'y', parentId = 10, catalogPath = 'c:/_/main/lightroom/catalogs/carolyn/carolyn.lrcat'"))


# ---- writes that go wrong ----------------------------------------------------------------------------------------

def test_a_keyword_that_lands_outside_the_requested_parent_is_placement_mismatch(cat):
    cat[0].execute("misplace_under = 'top'")
    code, msg = _err(_call(cat, "keyword = 'shared:with-x', parentId = 10"))
    assert code == "PLACEMENT_MISMATCH" and "top level" in msg and "1001" in msg
    cat[0].execute("misplace_under = PEOPLE")
    code, msg = _err(_call(cat, "keyword = 'shared:with-y', parent = 'Shared'"))
    assert code == "PLACEMENT_MISMATCH" and "'People'" in msg


def test_aborted_write_reports_failure_and_creates_nothing(cat):
    cat[0].execute("write_mode = 'abort'")
    code, msg = _err(_call(cat, "keyword = 'shared:with-z', parentId = 10"))
    assert code == "OPERATION_FAILED" and "did not run" in msg
    assert cat[0].eval("places('shared:with-z')") == ""


def test_throwing_write_reports_failure(cat):
    cat[0].execute("write_mode = 'throw'")
    code, msg = _err(_call(cat, "keyword = 'shared:with-z', parentId = 10"))
    assert code == "OPERATION_FAILED" and "write lock timeout" in msg


def test_a_write_that_creates_nothing_is_not_reported_as_created(cat):
    cat[0].execute("create_noop = true")
    code, msg = _err(_call(cat, "keyword = 'shared:with-z', parentId = 10"))
    assert code == "OPERATION_FAILED" and "read-back" in msg


# ---- folds from the independent review (2026-10-06) ---------------------------------------------------------------

def test_include_on_export_is_read_back_not_echoed(cat):
    cat[0].execute("WITHKEN._inc = false")
    r = _ok(_call(cat, "keyword = 'shared:with-ken', parentId = 10"))       # requested: default true
    assert (r["created"], r["includeOnExport"], r["includeOnExportRequested"]) == (False, False, True)
    assert "Include on Export is false" in r["message"]


def test_an_unreadable_export_flag_is_reported_as_unknown(cat):
    cat[0].execute("attrs_fail = true")
    r = _ok(_call(cat, "keyword = 'shared:with-new', parentId = 10"))
    assert r["created"] is True and r["includeOnExport"] is None


def test_already_there_warns_about_same_named_keywords_elsewhere(cat):
    cat[0].execute("add(PEOPLE, mkkw(99, 'shared:with-ken'))")
    r = _ok(_call(cat, "keyword = 'shared:with-ken', parentId = 10"))
    assert r["created"] is False and "WARNING" in r["message"] and "99" in r["message"]
    dup = r["duplicatesElsewhere"]
    assert (dup[1]["id"], dup[1]["parentName"]) == (99, "People")


def test_a_queued_write_says_it_may_still_happen(cat):
    cat[0].execute("write_mode = 'queued'")
    code, msg = _err(_call(cat, "keyword = 'shared:with-q', parentId = 10"))
    assert code == "OPERATION_FAILED" and "queued" in msg and "re-run" in msg


def test_a_near_miss_parent_name_is_named_not_created(cat):
    code, msg = _err(_call(cat, "keyword = 'x', parent = 'shared'"))
    assert code == "PARENT_NOT_FOUND" and "'Shared' (id 10)" in msg and "create it first" not in msg


@pytest.mark.parametrize("name", ["a,b", "People|Leland"])
def test_lightroom_separators_are_refused(cat, name):
    code, _ = _err(_call(cat, f"keyword = '{name}', parentId = 10"))
    assert code == "INVALID_PARAM_VALUE" and cat[0].eval("writes") == 0


def test_a_handed_back_existing_keyword_is_explained(cat):
    # allowDuplicateName + a create that returns an existing keyword instead of making one (e.g. a different-case
    # sibling, if LrC's returnIfExists ignores case): honest failure, with the likely reason
    cat[0].execute("create_noop = true")
    code, msg = _err(_call(cat, "keyword = 'shared:cross-library', parentId = 10, allowDuplicateName = true"))
    assert code == "OPERATION_FAILED" and "handed back" in msg


def test_find_keywords_named_ci_reports_each_parent(cat):
    rt, module = cat
    hits = module["_findKeywordsNamedCI"](rt.eval("CATALOG:getKeywords()"), "dup")
    got = sorted((hits[i]["kw"]["localIdentifier"], hits[i]["parent"]["localIdentifier"]) for i in range(1, len(hits) + 1))
    assert got == [(21, 20), (31, 30)]


# ---- CLI + schema --------------------------------------------------------------------------------------------------

def _dry(*args):
    res = CliRunner().invoke(cli, ["-o", "json", "catalog", "create-keyword", *args, "--dry-run"])
    assert res.exit_code == 0, res.output
    return json.loads(res.output)["params"]


def test_cli_maps_every_option():
    assert _dry("shared:with-ken", "--parent-id", "10", "--no-export", "--catalog-path", "C:\\x.lrcat",
                "--allow-duplicate-name") == {"keyword": "shared:with-ken", "parentId": 10, "includeOnExport": False,
                                              "catalogPath": "C:\\x.lrcat", "allowDuplicateName": True}
    assert _dry("k", "--parent", "Shared") == {"keyword": "k", "parent": "Shared"}
    assert _dry("k") == {"keyword": "k"}


def test_schema_accepts_the_new_params():
    from lightroom_sdk.validation import validate_params

    out = validate_params("catalog.createKeyword", {"keyword": "k", "parentId": 10, "parent": "Shared",
                                                    "includeOnExport": False, "catalogPath": "x",
                                                    "allowDuplicateName": True})
    assert out["parentId"] == 10 and out["includeOnExport"] is False
