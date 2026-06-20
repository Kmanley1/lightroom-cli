"""Real unit tests for the plugin's Lua modules, executed in-process via embedded Lua.

These exercise the *actual* plugin Lua functions — no Lightroom required — using
``lupa`` (an embedded Lua runtime; Lua 5.5 in this environment). The string-escaping
and flag logic under test behaves identically across Lua 5.1–5.5, so this faithfully
covers Lightroom Classic's embedded Lua 5.1.4 plugin code. The Lightroom SDK
``import`` mechanism is replaced with a permissive mock so the modules load outside LR.

Covers two Windows-only bugs found during live CLI testing (2026-06-07):

  1. ``MessageProtocol._encodeJSON`` did not escape backslashes, so Windows paths
     produced invalid JSON: ``C:\\Users`` was emitted as ``"C:\\Users"`` and the
     illegal ``\\U`` escape made the Python side reject the whole response (then
     time out). Fix: escape ``\\`` first, before the other escapes.

  2. ``SimpleSocketBridge.startSocketServer`` never reset ``shuttingDown``, so after
     a Stop->Start the socket reconnect logic (gated on that flag) stayed disabled
     and the plugin never reconnected to the CLI listener. Fix: reset the flag on
     start.

The whole module is skipped if ``lupa`` is not installed (e.g. a minimal CI image),
so it never blocks the existing suite.
"""

import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
from lupa import LuaRuntime  # noqa: E402

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "lightroom_sdk" / "plugin"


def _make_runtime() -> LuaRuntime:
    """A LuaRuntime with the LR SDK ``import`` stubbed and ``require`` pointed at the plugin."""
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.execute(
        """
        -- Permissive mock standing in for any Lightroom SDK object: it is callable
        -- and every field access returns another permissive mock (also callable).
        -- Enough for the modules to load and for getLogger()/Config/LrPrefs to no-op.
        local function permissive()
            return setmetatable({}, {
                __index = function() return permissive() end,
                __call  = function() return permissive() end,
            })
        end
        function import(_name) return permissive() end
        """
    )
    rt.execute(f'package.path = "{PLUGIN_DIR.as_posix()}/?.lua;" .. package.path')
    return rt


def _load(rt: LuaRuntime, module_name: str):
    # Parenthesise so require's (possibly multi-value) return is truncated to the
    # single module table — otherwise lupa unpacks it into a Python tuple.
    return rt.eval(f'(require("{module_name}"))')


class TestMessageProtocolEncodeJSON:
    """JSON-escape fix: _encodeJSON must emit valid JSON for Windows paths."""

    @pytest.fixture
    def mp(self):
        rt = _make_runtime()
        return rt, _load(rt, "MessageProtocol")

    def _encode(self, mp, value):
        rt, module = mp
        return module["_encodeJSON"](module, value)

    @pytest.mark.parametrize(
        "value",
        [
            "C:\\Users\\Ken\\2009\\photo.jpg",
            "D:\\Ken\\2009\\2009-06\\2009.06.25 01.39.15.000097 PM.jpg",  # the real selected photo
            "\\\\nas\\share\\file.jpg",  # UNC path
            "plain string, no escapes",
            "",
            'embedded "double quotes"',
            "tab\there",
            "newline\nhere",
            "carriage\rreturn",
            'C:\\dir\\f "q" \t end\n',  # backslash + quote + tab + newline together
        ],
    )
    def test_string_roundtrips_as_valid_json(self, mp, value):
        encoded = self._encode(mp, value)
        # Must parse as JSON (this is what failed pre-fix) and round-trip exactly.
        assert json.loads(encoded) == value

    def test_windows_path_was_the_exact_bug(self, mp):
        # Pre-fix this emitted  "C:\\Users"  -> illegal \\U escape -> json.loads raised.
        encoded = self._encode(mp, "C:\\Users")
        assert encoded == '"C:\\\\Users"'  # backslash doubled
        assert json.loads(encoded) == "C:\\Users"

    def test_object_with_windows_path_value(self, mp):
        """Faithful repro: the real get-selected response was an object with a C:\\ path value."""
        rt, module = mp
        obj = rt.table_from({"path": "D:\\Ken\\2009\\x.jpg", "id": 3763624, "isVirtualCopy": False})
        decoded = json.loads(module["_encodeJSON"](module, obj))
        assert decoded == {"path": "D:\\Ken\\2009\\x.jpg", "id": 3763624, "isVirtualCopy": False}

    def test_array_of_strings(self, mp):
        rt, module = mp
        arr = rt.table("C:\\a\\b.jpg", "plain", 'has "q"')
        assert json.loads(module["_encodeJSON"](module, arr)) == ["C:\\a\\b.jpg", "plain", 'has "q"']

    def test_number_and_boolean(self, mp):
        assert json.loads(self._encode(mp, 42)) == 42
        assert json.loads(self._encode(mp, True)) is True
        assert json.loads(self._encode(mp, False)) is False

    @pytest.mark.xfail(
        reason="encoder escapes only \\n\\r\\t among control chars; other C0 controls (<0x20) "
        "are emitted raw -> invalid JSON. Latent gap, out of scope for the Windows-path fix.",
        strict=False,
    )
    def test_control_char_roundtrips(self, mp):
        value = "bell\x07char"
        assert json.loads(self._encode(mp, value)) == value


class TestSocketBridgeShutdownReset:
    """Reconnect fix: startSocketServer must clear ``shuttingDown`` left by a prior Stop."""

    def test_start_clears_shutting_down(self):
        rt = _make_runtime()
        # Simulate post-Stop state: bridge present, flagged shuttingDown, server stopped.
        rt.execute("_G.LightroomPythonBridge = { shuttingDown = true, socketServerRunning = false }")
        _load(rt, "SimpleSocketBridge")
        # start() resets the flag synchronously, before the LR-dependent socket setup;
        # pcall swallows the expected downstream error from the stubbed SDK.
        rt.execute("pcall(require('SimpleSocketBridge').start)")
        assert rt.eval("_G.LightroomPythonBridge.shuttingDown") is False

    def test_guard_skips_reset_when_already_running(self):
        """When the server is already running the guard returns early — before the reset."""
        rt = _make_runtime()
        rt.execute("_G.LightroomPythonBridge = { shuttingDown = true, socketServerRunning = true }")
        _load(rt, "SimpleSocketBridge")
        rt.execute("pcall(require('SimpleSocketBridge').start)")
        assert rt.eval("_G.LightroomPythonBridge.shuttingDown") is True


class TestDevelopModuleDevelopableFormat:
    """Develop read-guard fix: getSettings must accept any still image, not just RAW/DNG/VC.

    Lightroom develops JPEG/TIFF/PNG/etc., but DevelopModule.getSettings used to reject
    everything except RAW/DNG/virtual-copy, so `lr develop get-settings` failed on a JPEG
    even though the photo had real adjustments. The guard now delegates to a pure predicate.
    """

    @pytest.fixture
    def develop(self):
        rt = _make_runtime()
        return _load(rt, "DevelopModule")

    @pytest.mark.parametrize("fmt", ["RAW", "DNG", "JPG", "JPEG", "TIFF", "PNG", "HEIC", "PSD"])
    def test_still_image_formats_are_developable(self, develop, fmt):
        assert develop["_isDevelopableFormat"](fmt) is True

    def test_video_is_not_developable(self, develop):
        assert develop["_isDevelopableFormat"]("VIDEO") is False

    def test_nil_format_is_not_developable(self, develop):
        assert develop["_isDevelopableFormat"](None) is False


class TestConfigGetBooleanFalse:
    """Config:get must preserve a stored boolean ``false`` instead of the default.

    The old ``return self.prefs[key] or defaults[key]`` is the Lua ``or`` trap: a
    pref stored as ``false`` is falsy, so it was clobbered by its (true) default,
    making every disable switch (autoStart / enableDevelopSync / enableCatalogSync /
    enablePreviewSync) impossible to turn off.
    """

    def _cfg(self):
        rt = _make_runtime()
        cfg = _load(rt, "Config")
        # Inject a real prefs table (bypasses LrPrefs). A stored ``false`` must survive.
        rt.execute(
            "require('Config').prefs = "
            "{ autoStart = false, enableDevelopSync = false, serverPort = 99999 }"
        )
        return cfg

    def test_stored_false_is_preserved(self):
        cfg = self._cfg()
        assert cfg["get"](cfg, "autoStart") is False
        assert cfg["get"](cfg, "enableDevelopSync") is False

    def test_unset_key_falls_back_to_default(self):
        cfg = self._cfg()
        # enableCatalogSync is absent from prefs -> default (true).
        assert cfg["get"](cfg, "enableCatalogSync") is True

    def test_stored_value_overrides_default(self):
        cfg = self._cfg()
        assert cfg["get"](cfg, "serverPort") == 99999


class TestRemoveFromCatalogNotSupported:
    """removeFromCatalog must return an honest NOT_SUPPORTED, not call a nil SDK method.

    LrCatalog has no removePhoto(); the old code entered a write transaction and
    called catalog:removePhoto(photo), which always failed with OPERATION_FAILED.
    """

    def _call(self, params):
        rt = _make_runtime()
        # Wire the real ErrorUtils into the bridge global BEFORE loading the
        # module, mirroring PluginInit. CatalogModule captures ErrorUtils once at
        # load time via getErrorUtils(); without this it would fall back to a
        # minimal stub with a different error shape.
        # NOTE: production wires an INLINE ErrorUtils built in PluginInit.lua, not
        # this external module — NOT_SUPPORTED must live in both CODES tables for
        # this verb to ship the right code. Parity is guarded by
        # TestErrorUtilsCodesParity below.
        rt.execute("_G.LightroomPythonBridge = { ErrorUtils = require('ErrorUtils') }")
        cat = _load(rt, "CatalogModule")
        captured = []
        cat["removeFromCatalog"](rt.table_from(params), lambda r: captured.append(r))
        return captured

    def test_missing_photo_id(self):
        captured = self._call({})
        assert len(captured) == 1
        assert captured[0]["success"] is False
        assert captured[0]["error"]["code"] == "MISSING_PARAM"

    def test_valid_id_returns_not_supported(self):
        captured = self._call({"photoId": 12345})
        assert len(captured) == 1
        assert captured[0]["success"] is False
        assert captured[0]["error"]["code"] == "NOT_SUPPORTED"


class TestEditInPhotoshopNotSupported:
    """editInPhotoshop must return NOT_SUPPORTED, not call the nonexistent
    LrPhoto:openInPhotoshop()."""

    def test_returns_not_supported(self):
        rt = _make_runtime()
        # Wire the real ErrorUtils before load (see TestRemoveFromCatalogNotSupported).
        rt.execute("_G.LightroomPythonBridge = { ErrorUtils = require('ErrorUtils') }")
        dev = _load(rt, "DevelopModule")
        captured = []
        dev["editInPhotoshop"](rt.table_from({"photoId": 1}), lambda r: captured.append(r))
        assert len(captured) == 1
        assert captured[0]["success"] is False
        assert captured[0]["error"]["code"] == "NOT_SUPPORTED"


class TestCommandRouterWallClockTimeout:
    """isTimedOut must use wall-clock os.time, not CPU-time os.clock.

    Long handlers spend their elapsed time yielded inside SDK/sleep/I/O, where CPU
    time barely advances, so the os.clock-based check never fired. We simulate a
    request whose recorded start time is well in the past and assert it is detected.
    """

    def _cr(self, start_times_lua):
        rt = _make_runtime()
        cr = _load(rt, "CommandRouter")
        rt.execute(f"require('CommandRouter').commandStartTime = {start_times_lua}")
        return cr

    def test_elapsed_beyond_limit_is_timed_out(self):
        # preview.generate limit is 110s; started ~9999s ago.
        cr = self._cr("{ req1 = os.time() - 9999 }")
        assert cr["isTimedOut"](cr, "req1", "preview.generate") is True

    def test_recent_request_not_timed_out(self):
        cr = self._cr("{ req2 = os.time() }")
        assert cr["isTimedOut"](cr, "req2", "preview.generate") is False

    def test_unknown_request_not_timed_out(self):
        cr = self._cr("{}")
        assert cr["isTimedOut"](cr, "missing", "preview.generate") is False


class TestErrorUtilsCodesParity:
    """Guard against the dual-ErrorUtils divergence.

    There are TWO ErrorUtils in this plugin: the external ``ErrorUtils.lua``
    module (what these unit tests load) and an INLINE copy built in
    ``PluginInit.lua`` and wired to ``_G.LightroomPythonBridge.ErrorUtils`` — the
    inline one is what production modules actually capture at load time. A
    capability code added to one CODES table but not the other silently degrades
    to the generic ``"ERROR"`` code in production (``createError`` falls back to
    ``code or "ERROR"``). So a NOT_SUPPORTED-returning verb would unit-test green
    against the external module while shipping ``"ERROR"`` to clients. Keep
    NOT_SUPPORTED (and any future capability code) in BOTH tables.
    """

    _DECL = 'NOT_SUPPORTED = "NOT_SUPPORTED"'

    def test_not_supported_in_external_errorutils(self):
        text = (PLUGIN_DIR / "ErrorUtils.lua").read_text(encoding="utf-8")
        assert self._DECL in text, "NOT_SUPPORTED missing from external ErrorUtils.lua CODES"

    def test_not_supported_in_inline_plugininit(self):
        text = (PLUGIN_DIR / "PluginInit.lua").read_text(encoding="utf-8")
        assert self._DECL in text, (
            "NOT_SUPPORTED missing from the INLINE PluginInit.lua CODES — "
            "removeFromCatalog/editInPhotoshop would ship code='ERROR' in production"
        )


class TestGetSelectedPhotosFilmstripGuard:
    """getSelectedPhotos must NOT report the whole filmstrip when nothing is selected.

    ``LrCatalog:getTargetPhotos()`` returns the *entire filmstrip* when no photos are
    selected (a well-known LrC gotcha), and the old guard only caught the empty case —
    so "get selected" reported the whole catalog as the selection. The fix gates on
    ``getTargetPhoto()`` (singular, the active photo): nil => nothing is truly selected
    => return empty. The decision is factored into the pure ``_resolveSelection`` helper
    so it is unit-testable without a live Lightroom (the rest of the handler — read
    access, metadata extraction — still needs LR, but the BUG lives entirely here).
    """

    @pytest.fixture
    def cat(self):
        rt = _make_runtime()
        # CatalogModule captures ErrorUtils at load; wire the real one (see other tests).
        rt.execute("_G.LightroomPythonBridge = { ErrorUtils = require('ErrorUtils') }")
        return rt, _load(rt, "CatalogModule")

    def _resolve(self, cat, target_photo, photos):
        rt, module = cat
        arr = rt.table_from(photos) if photos is not None else None
        result = module["_resolveSelection"](target_photo, arr)
        if result is None:
            return None
        return list(result.values())

    def test_nothing_selected_returns_empty_even_when_filmstrip_full(self, cat):
        # The exact bug: getTargetPhoto() is nil but getTargetPhotos() gave the filmstrip.
        assert self._resolve(cat, None, ["p1", "p2", "p3", "...whole filmstrip..."]) == []

    def test_selection_is_returned_when_active_photo_present(self, cat):
        assert self._resolve(cat, "active", ["p1", "p2"]) == ["p1", "p2"]

    def test_single_selection(self, cat):
        assert self._resolve(cat, "active", ["only"]) == ["only"]

    def test_active_photo_but_nil_list_is_empty(self, cat):
        # Defensive: never nil-iterate if getTargetPhotos() somehow failed.
        assert self._resolve(cat, "active", None) == []

    def test_nothing_selected_and_empty_filmstrip(self, cat):
        assert self._resolve(cat, None, []) == []


class TestFindPhotosUnknownFilterKeyFailsClosed:
    """findPhotos must reject unknown filter keys, not silently match every photo.

    The old code collected a ``warnings`` list and ran an empty predicate, so an unknown
    key (e.g. the legacy ``search`` path's ``{query=...}``) matched the whole catalog and
    returned it as a "search result". The decision is the pure ``_unknownFilterKeys`` helper.
    """

    @pytest.fixture
    def cat(self):
        rt = _make_runtime()
        rt.execute("_G.LightroomPythonBridge = { ErrorUtils = require('ErrorUtils') }")
        return rt, _load(rt, "CatalogModule")

    def _unknown(self, cat, desc):
        rt, module = cat
        arg = rt.table_from(desc) if desc is not None else None
        result = module["_unknownFilterKeys"](arg)
        return None if result is None else list(result.values())

    def test_all_known_keys_returns_nil(self, cat):
        assert self._unknown(cat, {"keyword": "x", "rating": 5, "flag": "pick"}) is None

    def test_empty_desc_returns_nil(self, cat):
        assert self._unknown(cat, {}) is None

    def test_non_table_returns_nil(self, cat):
        assert self._unknown(cat, None) is None

    def test_query_key_is_unknown(self, cat):
        # The exact #8 bug: the search command sent {query=...}.
        assert self._unknown(cat, {"query": "sunset"}) == ["query"]

    def test_unknown_keys_are_sorted(self, cat):
        assert self._unknown(cat, {"zzz": 1, "aaa": 2, "keyword": "k"}) == ["aaa", "zzz"]


class TestAddKeywordsFindsExistingKeyword:
    """addKeywords must reuse an existing keyword object, not spawn duplicates.

    ``catalog:createKeyword(name, {}, false, nil, true)`` is parent-scoped and unreliable
    for top-level reuse, so calling it per tag created duplicate keyword OBJECTS (the dup
    sets merged in production). The pure ``_findKeywordByName`` helper finds an existing
    keyword (recursively) so addKeywords reuses it.
    """

    @pytest.fixture
    def cat(self):
        rt = _make_runtime()
        rt.execute("_G.LightroomPythonBridge = { ErrorUtils = require('ErrorUtils') }")
        return rt, _load(rt, "CatalogModule")

    # A keyword tree of mocks; each responds to :getName() / :getChildren().
    _KW = """
        local function kw(name, children)
            return {
                getName = function(self) return name end,
                getChildren = function(self) return children end,
            }
        end
        tree = { kw('source:onedrive-ken'), kw('People', { kw('Carolyn'), kw('Ken') }) }
    """

    def _tree(self, cat):
        rt, module = cat
        rt.execute(self._KW)
        return module, rt.eval("tree")

    def test_finds_top_level_keyword(self, cat):
        module, tree = self._tree(cat)
        found = module["_findKeywordByName"](tree, "source:onedrive-ken")
        assert found is not None
        assert found["getName"](found) == "source:onedrive-ken"

    def test_finds_nested_keyword(self, cat):
        module, tree = self._tree(cat)
        found = module["_findKeywordByName"](tree, "Carolyn")
        assert found is not None
        assert found["getName"](found) == "Carolyn"

    def test_missing_keyword_returns_nil(self, cat):
        module, tree = self._tree(cat)
        assert module["_findKeywordByName"](tree, "Nonexistent") is None

    def test_nil_and_empty_are_safe(self, cat):
        rt, module = cat
        assert module["_findKeywordByName"](None, "x") is None
        assert module["_findKeywordByName"](rt.eval("{}"), "x") is None


class TestCollectKeywordsMatching:
    """findPhotos resolves keyword searches via the keyword index (#9). The pure matcher
    collects every keyword whose name contains the substring (case-insensitive, recursive);
    findPhotos then unions their getPhotos() instead of scanning the whole catalog.
    """

    @pytest.fixture
    def cat(self):
        rt = _make_runtime()
        rt.execute("_G.LightroomPythonBridge = { ErrorUtils = require('ErrorUtils') }")
        return rt, _load(rt, "CatalogModule")

    _KW = """
        local function kw(name, children)
            return { getName = function(self) return name end,
                     getChildren = function(self) return children end }
        end
        tree = {
            kw('Carolyn'),
            kw('source:onedrive-carolyn'),
            kw('People', { kw('Ken'), kw('CAROLYN Smith') }),
        }
    """

    def _names(self, cat, substr):
        rt, module = cat
        rt.execute(self._KW)
        matched = module["_collectKeywordsMatching"](rt.eval("tree"), substr)
        return sorted(m["getName"](m) for m in matched.values())

    def test_substring_case_insensitive_recursive(self, cat):
        # 'carolyn' matches Carolyn, source:onedrive-carolyn, and nested 'CAROLYN Smith'
        assert self._names(cat, "carolyn") == ["CAROLYN Smith", "Carolyn", "source:onedrive-carolyn"]

    def test_no_match_returns_empty(self, cat):
        assert self._names(cat, "zzz-nope") == []

    def test_nil_inputs_safe(self, cat):
        rt, module = cat
        assert list(module["_collectKeywordsMatching"](None, "x").values()) == []
        rt.execute(self._KW)
        assert list(module["_collectKeywordsMatching"](rt.eval("tree"), None).values()) == []


class TestSetMetadataAlwaysResponds:
    """setMetadata must always call back exactly once -- no silent hang on write-access failure.

    The old code put the callback INSIDE catalog:withWriteAccessDo with no safeCall, so a write
    that never ran the closure (lock timeout) sent no response and the client hung to its own
    timeout. The fix mirrors removeKeyword: capture result/error in outer locals, wrap
    withWriteAccessDo in safeCall, and call back exactly once afterward.
    """

    @pytest.fixture
    def cat(self):
        rt = _make_runtime()
        rt.execute("_G.LightroomPythonBridge = { ErrorUtils = require('ErrorUtils') }")
        return rt, _load(rt, "CatalogModule")

    def _call(self, cat, params):
        rt, module = cat
        captured = []
        module["setMetadata"](rt.table_from(params), lambda r: captured.append(r))
        return captured

    def test_missing_photo_id_responds_once(self, cat):
        captured = self._call(cat, {"key": "title", "value": "x"})
        assert len(captured) == 1
        assert captured[0]["error"]["code"] == "MISSING_PARAM"

    def test_missing_key_responds_once(self, cat):
        captured = self._call(cat, {"photoId": 123, "value": "x"})
        assert len(captured) == 1
        assert captured[0]["error"]["code"] == "MISSING_PARAM"

    def test_valid_params_respond_exactly_once(self, cat):
        # Anti-hang: even when the stubbed write transaction can't really run, setMetadata must
        # respond exactly once (the OLD callback-inside-withWriteAccessDo path called back 0 times).
        captured = self._call(cat, {"photoId": 123, "key": "title", "value": "x"})
        assert len(captured) == 1
