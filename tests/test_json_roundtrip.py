"""Cross-layer JSON round-trip tests: lock the Windows-path/backslash and unicode
encoding fixes *end to end*, across the Lua plugin and the Python CLI sides.

Why this file exists
--------------------
``tests/test_plugin_lua_unit.py::TestMessageProtocolEncodeJSON`` already proves the
plugin's ``_encodeJSON`` emits *valid JSON* for a handful of Windows-path / quote /
tab / newline strings (the 2026-06-07 backslash bug). This file COMPLEMENTS it by
exercising the full **cross-layer round trip** that the production bridge actually
relies on, and by adding the structured + unicode cases that test lacks:

  Direction A  (the read path — LR -> CLI):
      Lua ``MessageProtocol:_encodeJSON``  ->  Python ``json.loads``  ==  original
      This is THE path the Windows-path/unicode fix locked: the plugin serialises a
      response (containing ``C:\\Users\\...`` paths and possibly unicode metadata) and
      the Python CLI parses it with the stdlib ``json`` module.

  Direction B  (the request path — CLI -> LR):
      Python ``json.dumps``  ->  Lua ``MessageProtocol:decode``  ==  original
      The plugin decodes incoming requests with a *hand-rolled* parser
      (``_parseSimpleJSON``). This direction is only faithful for payloads that need
      no JSON un-escaping (forward-slash paths, raw-UTF-8 text, numbers, bools,
      nested objects/arrays). Its known limitations are pinned in
      ``DECODE_KNOWN_LIMITATIONS`` below and reported as violations, NOT silently
      weakened.

Both directions are driven through the *real* plugin Lua via ``lupa`` (Lua 5.5 here;
the escaping/parsing logic is identical on Lightroom Classic's embedded Lua 5.1.4),
using the same ``_make_runtime`` / ``_load`` harness as ``test_plugin_lua_unit.py``.
The whole module skips cleanly if ``lupa`` is absent.
"""

import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
from lupa import LuaRuntime  # noqa: E402

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "lightroom_sdk" / "plugin"

# A single literal backslash, built without escapes-in-test-source ambiguity.
BS = chr(92)
WIN_PATH = "C:" + BS + "Users" + BS + "Ken" + BS + "2009" + BS + "photo.jpg"
UNC_PATH = BS + BS + "nas" + BS + "share" + BS + "file.jpg"
FWD_PATH = "C:/Users/Ken/2009/photo.jpg"


# ---------------------------------------------------------------------------
# Allowlist: VERIFIED known limitations of the hand-rolled Lua request DECODER
# (MessageProtocol:_parseSimpleJSON). These are reported in `violations`. They are
# NOT regressions in the locked encode-side fix (Direction A round-trips all of
# them perfectly). The decoder strips a string value's outer quotes but never
# processes JSON escape sequences, so any payload whose JSON form contains a
# backslash escape decodes with the escape left LITERAL.
#
# Each tuple: (label, python_value, json_text_sent, what_decoder_returns)
# Verified empirically against lightroom_sdk/plugin/MessageProtocol.lua on
# 2026-06-20 with lupa 2.8 / Lua 5.5.
# ---------------------------------------------------------------------------
DECODE_KNOWN_LIMITATIONS = [
    # default json.dumps escapes the backslash; decoder keeps "\\" literal.
    ("win_path_backslash", WIN_PATH, json.dumps({"path": WIN_PATH}),
     "backslash escape \\\\ is NOT collapsed -> path keeps doubled backslashes"),
    ("unc_path_backslash", UNC_PATH, json.dumps({"path": UNC_PATH}),
     "leading \\\\\\\\ kept literal -> UNC prefix doubled"),
    ("embedded_quote", 'a"b', json.dumps({"v": 'a"b'}),
     'escaped quote \\" kept literal -> value contains a backslash'),
    ("tab", "a\tb", json.dumps({"v": "a\tb"}),
     "\\t kept literal (two chars) instead of a real tab"),
    ("newline", "a\nb", json.dumps({"v": "a\nb"}),
     "\\n kept literal (two chars) instead of a real newline"),
    # ensure_ascii=True (the json.dumps DEFAULT) emits \uXXXX for non-ASCII.
    ("unicode_ascii_escaped", "café", json.dumps({"v": "café"}),
     "\\u00e9 kept literal -> non-ASCII via default json.dumps is NOT decoded"),
]


def _make_runtime() -> LuaRuntime:
    """LuaRuntime with the LR SDK ``import`` stubbed and ``require`` pointed at the plugin.

    Copied from tests/test_plugin_lua_unit.py so this file is self-contained.
    """
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.execute(
        """
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
    return rt.eval(f'(require("{module_name}"))')


def _lua_len(rt: LuaRuntime, tbl) -> int:
    """Lua ``#tbl`` (array length) for a returned table."""
    return int(rt.eval("function(t) return #t end")(tbl))


@pytest.fixture
def proto():
    """(runtime, MessageProtocol module) — fresh per test."""
    rt = _make_runtime()
    return rt, _load(rt, "MessageProtocol")


# ===========================================================================
# Direction A: Lua encode -> Python json.loads  (the locked read path)
# ===========================================================================
class TestEncodeToPythonRoundTrip:
    """Lua ``_encodeJSON`` output must parse with stdlib ``json`` to the SAME value.

    This is the cross-layer assertion the unit test stops short of: it not only
    checks the Lua string is valid JSON, it checks the Python side reconstructs the
    original value byte-for-byte. Complements TestMessageProtocolEncodeJSON with the
    unicode + structured + full-combo cases.
    """

    def _enc(self, proto, value):
        rt, module = proto
        return module["_encodeJSON"](module, value)

    @pytest.mark.parametrize(
        "value",
        [
            WIN_PATH,
            UNC_PATH,
            FWD_PATH,
            "C:" + BS + "Program Files" + BS + "Adobe",  # spaces + backslash
            # --- unicode (the cases the unit test lacks) ---
            "café résumé naïve",            # Latin-1 accents
            "Köln Straße Zürich",            # umlaut + eszett
            "日本語 中文 한국어",             # CJK
            "Москва Київ",                   # Cyrillic
            "photo 📷 done ✅ 🎉",           # emoji (astral plane)
            "mixed café 日本 📷 end",         # mixed scripts + emoji
            # --- control / quoting (combos the unit test only tests singly) ---
            'embedded "double" quotes',
            "tab\tchar",
            "newline\nchar",
            "carriage\rreturn",
            "crlf\r\npair",
            'C:' + BS + 'dir' + BS + 'f "q"\ttab\nnl\rcr',  # everything at once
            # --- empties ---
            "",
        ],
    )
    def test_string_encode_then_python_loads(self, proto, value):
        encoded = self._enc(proto, value)
        assert json.loads(encoded) == value

    @pytest.mark.parametrize(
        "value",
        [0, 42, -7, 1000000, 3.14, -0.5, 0.8],
    )
    def test_number_encode_then_python_loads(self, proto, value):
        encoded = self._enc(proto, value)
        assert json.loads(encoded) == value

    def test_bool_encode_then_python_loads(self, proto):
        assert json.loads(self._enc(proto, True)) is True
        assert json.loads(self._enc(proto, False)) is False

    def test_nested_object_with_mixed_types_roundtrips(self, proto):
        rt, module = proto
        obj = rt.table_from(
            {
                "command": "catalog.export",
                "params": rt.table_from(
                    {
                        "dest": WIN_PATH,
                        "unc": UNC_PATH,
                        "fwd": FWD_PATH,
                        "note": 'has "q", tab\t, nl\n, cr\r',
                        "unicode": "café 日本 📷",
                        "quality": 80,
                        "ratio": 0.8,
                        "neg": -3,
                        "flag": True,
                        "off": False,
                    }
                ),
            }
        )
        decoded = json.loads(module["_encodeJSON"](module, obj))
        assert decoded == {
            "command": "catalog.export",
            "params": {
                "dest": WIN_PATH,
                "unc": UNC_PATH,
                "fwd": FWD_PATH,
                "note": 'has "q", tab\t, nl\n, cr\r',
                "unicode": "café 日本 📷",
                "quality": 80,
                "ratio": 0.8,
                "neg": -3,
                "flag": True,
                "off": False,
            },
        }

    def test_array_of_objects_with_paths_roundtrips(self, proto):
        rt, module = proto
        arr = rt.table(
            rt.table_from({"path": WIN_PATH, "id": 1, "vc": False}),
            rt.table_from({"path": UNC_PATH, "id": 2, "vc": True}),
        )
        decoded = json.loads(module["_encodeJSON"](module, arr))
        assert decoded == [
            {"path": WIN_PATH, "id": 1, "vc": False},
            {"path": UNC_PATH, "id": 2, "vc": True},
        ]

    def test_array_of_mixed_scalars_roundtrips(self, proto):
        rt, module = proto
        arr = rt.table(WIN_PATH, "plain", 5, -2, 3.5, True, False)
        decoded = json.loads(module["_encodeJSON"](module, arr))
        assert decoded == [WIN_PATH, "plain", 5, -2, 3.5, True, False]

    def test_unicode_object_keys_roundtrip(self, proto):
        # Object keys go through _encodeJSON(tostring(k)); unicode keys must survive.
        rt, module = proto
        obj = rt.table_from({"café": 1, "日本": 2, WIN_PATH: 3})
        decoded = json.loads(module["_encodeJSON"](module, obj))
        assert decoded == {"café": 1, "日本": 2, WIN_PATH: 3}

    def test_empty_string_encodes_to_empty_json_string(self, proto):
        assert self._enc(proto, "") == '""'
        assert json.loads(self._enc(proto, "")) == ""

    def test_empty_table_encodes_to_empty_object(self, proto):
        # An empty Lua table (#t == 0) is encoded as an OBJECT "{}" by this encoder.
        rt, module = proto
        encoded = module["_encodeJSON"](module, rt.table_from({}))
        assert encoded == "{}"
        assert json.loads(encoded) == {}

    def test_windows_path_exact_byte_shape(self, proto):
        # Pin the exact serialisation, not just validity: each backslash doubled.
        encoded = self._enc(proto, "C:" + BS + "Users")
        # JSON text is  "C:\\Users"  -> the single source backslash is doubled.
        assert encoded == '"C:' + BS + BS + 'Users"'
        assert json.loads(encoded) == "C:" + BS + "Users"

    def test_encode_loads_reencode_is_idempotent(self, proto):
        # loads(lua_encode(x)) must survive a further stdlib dumps->loads unchanged.
        for value in [WIN_PATH, UNC_PATH, "café 📷", 'a"b\tc\nd\re', FWD_PATH]:
            once = json.loads(self._enc(proto, value))
            twice = json.loads(json.dumps(once))
            assert once == value == twice


# ===========================================================================
# Direction B: Python json.dumps -> Lua decode  (the request path; faithful subset)
# ===========================================================================
class TestPythonToLuaDecodeRoundTrip:
    """Python-serialised requests must decode back to the same values through the
    plugin's ``MessageProtocol:decode`` -- for the payloads that need no un-escaping.

    The decoder is hand-rolled (``_parseSimpleJSON``) and does NOT unescape string
    escapes; those cases are pinned in TestDecoderKnownLimitations and reported as
    violations. Here we lock everything that genuinely survives.
    """

    def _decode(self, proto, py_obj, *, ensure_ascii=True):
        rt, module = proto
        text = json.dumps(py_obj, ensure_ascii=ensure_ascii)
        return module["decode"](module, text)

    def test_forward_slash_path_roundtrips(self, proto):
        t = self._decode(proto, {"path": FWD_PATH})
        assert t["path"] == FWD_PATH

    @pytest.mark.parametrize(
        "value",
        ["café résumé", "Köln Straße", "日本語 中文", "Москва", "photo 📷 done"],
    )
    def test_raw_utf8_string_roundtrips(self, proto, value):
        # A real client sending UTF-8 (ensure_ascii=False) round-trips faithfully:
        # the decoder copies bytes between the quotes verbatim.
        t = self._decode(proto, {"v": value}, ensure_ascii=False)
        assert t["v"] == value

    @pytest.mark.parametrize("value", [0, 42, -7, 1000000])
    def test_integer_roundtrips(self, proto, value):
        t = self._decode(proto, {"v": value})
        assert t["v"] == value

    @pytest.mark.parametrize("value", [3.14, -0.5, 0.8])
    def test_float_roundtrips(self, proto, value):
        t = self._decode(proto, {"v": value})
        assert t["v"] == value

    def test_bool_roundtrips(self, proto):
        assert self._decode(proto, {"v": True})["v"] is True
        assert self._decode(proto, {"v": False})["v"] is False

    def test_null_drops_key(self, proto):
        # JSON null -> Lua nil -> key absent. Semantically correct round-trip.
        t = self._decode(proto, {"v": None})
        assert ("v" in dict(t)) is False

    def test_nested_object_roundtrips(self, proto):
        t = self._decode(proto, {"a": {"b": FWD_PATH, "n": 7}})
        assert t["a"]["b"] == FWD_PATH
        assert t["a"]["n"] == 7

    def test_array_roundtrips(self, proto):
        rt, _ = proto
        t = self._decode(proto, {"a": [FWD_PATH, "plain", 5]})
        a = t["a"]
        assert [a[1], a[2], a[3]] == [FWD_PATH, "plain", 5]
        assert _lua_len(rt, a) == 3

    def test_empty_string_value_roundtrips(self, proto):
        t = self._decode(proto, {"s": ""})
        assert t["s"] == ""


# ===========================================================================
# Decoder known-limitation pins (reported as violations, not hidden)
# ===========================================================================
class TestDecoderKnownLimitations:
    """Lock the CURRENT (lossy) behaviour of the request decoder for escaped
    payloads, so a future fix that makes it faithful trips this test and prompts a
    review of DECODE_KNOWN_LIMITATIONS. Each entry is a VERIFIED round-trip failure
    of Python json.dumps -> Lua decode, reported verbatim in `violations`.

    These are limitations of the *request* decoder only. The locked encode-side fix
    (Direction A) round-trips every one of these values perfectly -- see
    TestEncodeToPythonRoundTrip -- so the production read path is unaffected.
    """

    def _decode_first_value(self, proto, json_text):
        rt, module = proto
        t = module["decode"](module, json_text)
        d = dict(t)
        # the limitation payloads use key "path" or "v"
        return d.get("path", d.get("v"))

    @pytest.mark.parametrize(
        "label,py_value,json_text,_desc",
        DECODE_KNOWN_LIMITATIONS,
        ids=[c[0] for c in DECODE_KNOWN_LIMITATIONS],
    )
    def test_escaped_payload_does_not_yet_roundtrip(self, proto, label, py_value, json_text, _desc):
        got = self._decode_first_value(proto, json_text)
        # Documented behaviour: the decoded value is NOT equal to the original
        # (it still carries the literal JSON escape). If this assertion ever fails
        # because they ARE equal, the decoder was fixed -- update the allowlist.
        assert got != py_value, (
            f"{label}: decoder now round-trips an escaped payload that "
            f"DECODE_KNOWN_LIMITATIONS marks as lossy -- re-evaluate the allowlist"
        )
        # And the lossy result still contains a backslash (the un-processed escape),
        # except for the pure-unicode \\u case where it carries the literal 'u'+hex.
        assert (BS in got) or ("u00" in got) or ("u" in got and label == "unicode_ascii_escaped")
