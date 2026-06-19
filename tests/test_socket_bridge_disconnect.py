"""Disconnect / connection-loss must release in-flight awaiters (no hangs to the 300s timeout)."""

import asyncio

import pytest

from lightroom_sdk.exceptions import ConnectionError as LRConnectionError
from lightroom_sdk.socket_bridge import SocketBridge, StreamAggregator


def _bare_bridge():
    bridge = SocketBridge.__new__(SocketBridge)
    bridge._pending_requests = {}
    bridge._pending_streams = {}
    bridge._receive_task = None
    bridge._send_writer = None
    bridge._receive_writer = None
    bridge._connected = True
    return bridge


@pytest.mark.asyncio
async def test_fail_pending_fails_requests_and_streams():
    bridge = _bare_bridge()
    loop = asyncio.get_running_loop()
    req = loop.create_future()
    bridge._pending_requests["r1"] = req
    agg = StreamAggregator()
    bridge._pending_streams["s1"] = agg

    bridge._fail_pending(LRConnectionError("lost"))

    assert req.done() and isinstance(req.exception(), LRConnectionError)
    assert agg.future.done() and isinstance(agg.future.exception(), LRConnectionError)
    assert bridge._pending_requests == {}
    assert bridge._pending_streams == {}


@pytest.mark.asyncio
async def test_disconnect_releases_inflight_awaiter():
    """disconnect() must fail in-flight requests so the awaiter doesn't hang to its own timeout."""
    bridge = _bare_bridge()
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    bridge._pending_requests["r1"] = fut

    await bridge.disconnect()

    assert fut.done()
    assert isinstance(fut.exception(), LRConnectionError)


@pytest.mark.asyncio
async def test_fail_pending_skips_already_resolved_future():
    bridge = _bare_bridge()
    loop = asyncio.get_running_loop()
    done = loop.create_future()
    done.set_result({"ok": True})
    bridge._pending_requests["r1"] = done

    bridge._fail_pending(LRConnectionError("lost"))  # must not raise on the resolved future

    assert done.result() == {"ok": True}
    assert bridge._pending_requests == {}
