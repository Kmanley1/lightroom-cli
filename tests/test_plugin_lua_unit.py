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
