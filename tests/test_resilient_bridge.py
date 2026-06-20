import asyncio

import pytest

from lightroom_sdk.resilient_bridge import ConnectionState, ResilientSocketBridge


@pytest.mark.asyncio
async def test_initial_state_is_disconnected():
    bridge = ResilientSocketBridge(port_file="/tmp/nonexistent.txt")
    assert bridge.state == ConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_connect_transitions_to_connected(mock_lr_server):
    mock_lr_server.register_response("system.ping", {"status": "ok"})
    bridge = ResilientSocketBridge(port_file=str(mock_lr_server.port_file))
    await bridge.connect()
    assert bridge.state == ConnectionState.CONNECTED
    await bridge.disconnect()


@pytest.mark.asyncio
async def test_auto_reconnect_on_send_failure(mock_lr_server):
    """接続断後のsend_command()が自動再接続する"""
    mock_lr_server.register_response("system.ping", {"status": "ok"})
    bridge = ResilientSocketBridge(
        port_file=str(mock_lr_server.port_file),
        max_reconnect_attempts=2,
        heartbeat_interval=0,  # テスト用: ハートビート無効
    )
    await bridge.connect()

    # 内部bridgeを強制切断
    bridge._bridge._connected = False

    # send_commandが自動再接続を試みる
    result = await bridge.send_command("system.ping")
    assert result["result"]["status"] == "ok"
    assert bridge.state == ConnectionState.CONNECTED
    await bridge.disconnect()


def test_is_mutating_classifies_by_schema():
    """The reconnect guard classifies commands via the schema; unknowns are treated as mutating."""
    bridge = ResilientSocketBridge(port_file="/tmp/nonexistent.txt")
    assert bridge._is_mutating("catalog.setRating") is True
    assert bridge._is_mutating("catalog.addKeywords") is True
    assert bridge._is_mutating("catalog.getAllPhotos") is False
    assert bridge._is_mutating("system.ping") is False
    assert bridge._is_mutating("totally.unknown.command") is True  # conservative default


@pytest.mark.asyncio
async def test_mutating_command_not_auto_retried(mock_lr_server):
    """A mutating command interrupted by a disconnect must NOT be silently re-sent (double-apply guard).

    The read path stays retryable (covered by test_auto_reconnect_on_send_failure with system.ping).
    """
    from lightroom_sdk.exceptions import MutatingNotRetriedError

    mock_lr_server.register_response("system.ping", {"status": "ok"})
    bridge = ResilientSocketBridge(
        port_file=str(mock_lr_server.port_file),
        max_reconnect_attempts=2,
        heartbeat_interval=0,
    )
    await bridge.connect()
    bridge._bridge._connected = False  # force the next send to fail mid-flight

    with pytest.raises(MutatingNotRetriedError):
        await bridge.send_command("catalog.setRating", {"photoId": "1", "rating": 5})

    # The bridge still reconnected (it's healthy); only the mutating re-send was withheld.
    assert bridge.state == ConnectionState.CONNECTED
    await bridge.disconnect()


@pytest.mark.asyncio
async def test_shutdown_event_transitions_to_shutdown(mock_lr_server):
    """server.shutdownイベントでSHUTDOWN状態になる"""
    bridge = ResilientSocketBridge(
        port_file=str(mock_lr_server.port_file),
        heartbeat_interval=0,
    )
    await bridge.connect()
    await mock_lr_server.wait_for_client()

    await mock_lr_server.send_event("server.shutdown", {"reason": "test"})
    await asyncio.sleep(0.3)

    assert bridge.state == ConnectionState.SHUTDOWN


@pytest.mark.asyncio
async def test_send_command_forwards_stream_and_progress_kwargs():
    """send_command must forward stream/progress_callback to the inner bridge (NDJSON).

    The resilient wrapper used to re-declare send_command(command, params, timeout) and
    forward only those three positionally, so NDJSON streaming/progress were unreachable.
    """
    bridge = ResilientSocketBridge(port_file="/tmp/nonexistent.txt")
    captured = {}

    class _StubBridge:
        async def send_command(self, command, params=None, timeout=30.0, stream=False, progress_callback=None):
            captured.update(
                command=command,
                params=params,
                timeout=timeout,
                stream=stream,
                progress_callback=progress_callback,
            )
            return {"id": "x", "success": True, "result": {"ok": True}}

    bridge._bridge = _StubBridge()
    bridge._state = ConnectionState.CONNECTED

    def _cb(_):
        return None

    result = await bridge.send_command(
        "catalog.findPhotos", {"searchDesc": {}}, timeout=12.0, stream=True, progress_callback=_cb
    )
    assert result["result"]["ok"] is True
    assert captured["stream"] is True
    assert captured["progress_callback"] is _cb
    assert captured["timeout"] == 12.0


@pytest.mark.asyncio
async def test_heartbeat_failure_triggers_reconnect():
    """A failed heartbeat ping must trigger a reconnect, not just log and keep pinging a dead socket."""
    bridge = ResilientSocketBridge(port_file="/tmp/nonexistent.txt", heartbeat_interval=0.01)
    reconnected = asyncio.Event()

    async def _fake_reconnect():
        reconnected.set()
        bridge._state = ConnectionState.SHUTDOWN  # stop the loop after first detection

    bridge._reconnect = _fake_reconnect

    class _DeadBridge:
        async def send_command(self, *args, **kwargs):
            raise ConnectionError("dead socket")

    bridge._bridge = _DeadBridge()
    bridge._state = ConnectionState.CONNECTED

    await asyncio.wait_for(bridge._heartbeat_loop(), timeout=2.0)
    assert reconnected.is_set()
