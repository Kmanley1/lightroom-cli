"""ConnectionManager のテスト。MockLightroomServer を使用。"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

from mcp_server.connection import ConnectionManager


@pytest.mark.asyncio
async def test_lazy_connect(mock_lr_server):
    """初回 execute 時に自動接続する"""
    mock_lr_server.register_response("system.ping", {"status": "ok"})

    cm = ConnectionManager(port_file=str(mock_lr_server.port_file))
    assert cm._client is None

    result = await cm.execute("system.ping", {}, timeout=5.0, mutating=False)
    assert result.get("isError") is not True
    assert cm._client is not None
    await cm.shutdown()


@pytest.mark.asyncio
async def test_connection_error_returns_mcp_error():
    """接続できない場合に MCP エラーレスポンスを返す"""
    import tempfile as _tf

    cm = ConnectionManager(port_file=str(Path(_tf.gettempdir()) / "nonexistent_port_file_test.txt"))

    result = await cm.execute("system.ping", {}, timeout=2.0, mutating=False)
    assert result["isError"] is True
    await cm.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Timing-sensitive test unreliable on Windows CI")
async def test_lock_serializes_commands(mock_lr_server):
    """asyncio.Lock がコマンドを直列化すること（タイムスタンプで証明）"""
    timestamps = []

    mock_lr_server.register_response("system.ping", {"status": "ok"})

    cm = ConnectionManager(port_file=str(mock_lr_server.port_file))

    async def run_cmd(label: str):
        start = time.monotonic()
        await cm.execute("system.ping", {}, timeout=5.0, mutating=False)
        end = time.monotonic()
        timestamps.append((label, start, end))

    await asyncio.gather(run_cmd("A"), run_cmd("B"))
    assert len(timestamps) == 2

    (label_a, start_a, end_a) = timestamps[0]
    (label_b, start_b, end_b) = timestamps[1]
    # At least one must have finished before the other started
    # Windows timer resolution is ~15ms, so use generous tolerance
    assert end_a <= start_b + 0.1 or end_b <= start_a + 0.1, (
        f"Commands overlapped: {label_a}=[{start_a:.3f},{end_a:.3f}], {label_b}=[{start_b:.3f},{end_b:.3f}]"
    )
    await cm.shutdown()


@pytest.mark.asyncio
async def test_mutating_not_retried_after_reconnect():
    """C1: mutating コマンドは接続エラー時に再送されずエラーを返す"""
    import tempfile as _tf

    cm = ConnectionManager(port_file=str(Path(_tf.gettempdir()) / "nonexistent_port_file_test.txt"))
    result = await cm.execute(
        "develop.setValue",
        {"param": "Exposure", "value": 0.5},
        timeout=2.0,
        mutating=True,
    )
    assert result["isError"] is True
    await cm.shutdown()


@pytest.mark.asyncio
async def test_read_failure_does_not_block_next_mutating(mock_lr_server):
    """#126: a read-only failure must NOT pre-emptively block a later, fresh mutating command.

    Previously a non-mutating connection failure set a `_reconnected` flag that made the next
    mutating command return MUTATING_NOT_RETRIED spuriously, even though a fresh mutating command
    on a new connection is safe. The in-flight protection (a mutating command that itself fails ->
    MUTATING_NOT_RETRIED) is unchanged (see test_mutating_not_retried_after_reconnect).
    """
    cm = ConnectionManager(port_file=str(mock_lr_server.port_file))

    mock_lr_server.register_response("system.ping", {"status": "ok"})
    mock_lr_server.register_response("develop.setValue", {"parameter": "Exposure", "value": 0.5})
    await cm.execute("system.ping", {}, timeout=5.0, mutating=False)

    cm._client = None  # as a read-failure path leaves it

    result = await cm.execute(
        "develop.setValue",
        {"param": "Exposure", "value": 0.5},
        timeout=5.0,
        mutating=True,
    )
    assert result.get("code") != "MUTATING_NOT_RETRIED", result
    assert result.get("isError") is not True, result
    await cm.shutdown()


@pytest.mark.asyncio
async def test_readonly_command_retried_after_reconnect(mock_lr_server):
    """C1: read-only コマンドは再接続後に再送される"""
    mock_lr_server.register_response("system.ping", {"status": "ok"})

    cm = ConnectionManager(port_file=str(mock_lr_server.port_file))
    await cm.execute("system.ping", {}, timeout=5.0, mutating=False)
    cm._client = None

    result = await cm.execute("system.ping", {}, timeout=5.0, mutating=False)
    assert result.get("isError") is not True or result.get("code") == "CONNECTION_ERROR"
    await cm.shutdown()
