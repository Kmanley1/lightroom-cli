"""Lightroom connection lifecycle manager for MCP Server.

C2: LightroomClient.execute_command() 経由でコマンドを実行する。
    client._bridge 直アクセスは行わない（例外正規化を崩さないため）。
C1: mutating=True のコマンドは再接続後に再送せずエラー返却する。

NOTE: ResilientSocketBridge は send_command 内で接続断時に自動リトライ(1回)する。
      mutating コマンドの二重送信リスクがあるが、ResilientSocketBridge に
      retry_on_error=False オプションを追加する変更は本フェーズのスコープ外。
      実機E2Eテストで確認し、必要なら後続タスクで対処する。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# develop.ai.<type> MCP tools have no plugin handler; route them to the real bridge command
# (the CLI uses these underlying commands directly). Mapping: tool command -> (real command,
# params to inject). develop.ai.{presets,list,reset} + system.{checkConnection,reconnect} are
# serviced explicitly in execute() below.
_AI_TOOL_REWRITE = {
    "develop.ai.subject": ("develop.createAIMaskWithAdjustments", {"selectionType": "subject"}),
    "develop.ai.sky": ("develop.createAIMaskWithAdjustments", {"selectionType": "sky"}),
    "develop.ai.background": ("develop.createAIMaskWithAdjustments", {"selectionType": "background"}),
    "develop.ai.objects": ("develop.createAIMaskWithAdjustments", {"selectionType": "objects"}),
    "develop.ai.people": ("develop.createAIMaskWithAdjustments", {"selectionType": "people"}),
    "develop.ai.landscape": ("develop.createAIMaskWithAdjustments", {"selectionType": "landscape"}),
    "develop.ai.list": ("develop.getAllMasks", {}),
    "develop.ai.reset": ("develop.resetMasking", {}),
}


class ConnectionManager:
    """Manages LightroomClient lifecycle with lazy connect and asyncio.Lock."""

    def __init__(self, port_file: str | None = None):
        self._port_file = port_file
        self._client = None
        self._lock = asyncio.Lock()

    async def execute(
        self,
        command: str,
        params: dict[str, Any],
        timeout: float,
        mutating: bool,
    ) -> dict[str, Any]:
        """Execute a command with validation, locking, and error handling."""
        # 0. MCP-only tools: the LR plugin has no handler for develop.ai.* or
        #    system.{checkConnection,reconnect}. Service the local ones here and rewrite the
        #    develop.ai.* mask tools to the real bridge command -- otherwise these advertised
        #    tools return UNKNOWN_COMMAND (dead on arrival).
        if command == "develop.ai.presets":
            from lightroom_sdk.presets import AI_MASK_PRESETS

            return {"result": {"presets": AI_MASK_PRESETS}}
        if command == "system.checkConnection":
            async with self._lock:
                try:
                    client = await self._get_client()
                    await client.execute_command("system.ping", {}, timeout=timeout)
                    return {"result": {"status": "ok", "connected": True}}
                except Exception as e:
                    self._client = None
                    return {"result": {"status": "unavailable", "connected": False, "reason": str(e)}}
        if command == "system.reconnect":
            async with self._lock:
                await self.shutdown()
                try:
                    await self._get_client()
                    return {"result": {"status": "reconnected", "connected": True}}
                except Exception as e:
                    return {"isError": True, "code": "CONNECTION_ERROR", "message": str(e)}
        if command in _AI_TOOL_REWRITE:
            real_command, injected = _AI_TOOL_REWRITE[command]
            params = {**(params or {}), **injected}
            command = real_command

        # 1. Validation
        from lightroom_sdk.validation import ValidationError, validate_params

        try:
            validated = validate_params(command, params)
        except ValidationError as e:
            return {
                "isError": True,
                "code": "VALIDATION_ERROR",
                "message": str(e),
                "suggestions": e.suggestions if hasattr(e, "suggestions") else [],
            }

        # 2. Execute with lock (asyncio.wait_for for Python 3.10 compatibility)
        try:

            async def _execute():
                async with self._lock:
                    client = await self._get_client()
                    return await client.execute_command(command, validated, timeout=timeout)

            result = await asyncio.wait_for(_execute(), timeout=timeout)
            return {"result": result}
        except (ConnectionError, OSError) as e:
            logger.warning(f"Connection error on '{command}': {e}")
            self._client = None
            if mutating:
                # An in-flight mutating command must not be auto-resent (it may have landed).
                return {
                    "isError": True,
                    "code": "MUTATING_NOT_RETRIED",
                    "message": (
                        "接続が切断されたため、mutating コマンドは安全のため再送されませんでした。"
                        "再度実行してください。"
                    ),
                }
            return {
                "isError": True,
                "code": "CONNECTION_ERROR",
                "message": (
                    "Lightroom に接続できません。Lightroom Classic が起動し、"
                    "CLI Bridge プラグインが有効であることを確認してください。"
                ),
            }
        except (asyncio.TimeoutError, TimeoutError):
            return {
                "isError": True,
                "code": "TIMEOUT_ERROR",
                "message": f"コマンドがタイムアウトしました ({timeout}秒)。",
            }
        except Exception as e:
            from lightroom_sdk.exceptions import ConnectionError as LRConnectionError
            from lightroom_sdk.exceptions import LightroomSDKError
            from lightroom_sdk.exceptions import TimeoutError as LRTimeoutError

            if isinstance(e, LRConnectionError):
                self._client = None
                if mutating:
                    return {
                        "isError": True,
                        "code": "MUTATING_NOT_RETRIED",
                        "message": (
                            "接続が切断されたため、mutating コマンドは安全のため再送されませんでした。"
                            "再度実行してください。"
                        ),
                    }
                return {
                    "isError": True,
                    "code": "CONNECTION_ERROR",
                    "message": (
                        "Lightroom に接続できません。Lightroom Classic が起動し、"
                        "CLI Bridge プラグインが有効であることを確認してください。"
                    ),
                }
            if isinstance(e, LRTimeoutError):
                return {
                    "isError": True,
                    "code": "TIMEOUT_ERROR",
                    "message": f"コマンドがタイムアウトしました ({timeout}秒)。",
                }
            if isinstance(e, LightroomSDKError):
                return {
                    "isError": True,
                    "code": e.code if hasattr(e, "code") else "SDK_ERROR",
                    "message": str(e),
                }
            logger.exception(f"Unexpected error on '{command}'")
            return {
                "isError": True,
                "code": "INTERNAL_ERROR",
                "message": str(e),
            }

    async def _get_client(self):
        """Get or create LightroomClient (lazy initialization)."""
        if self._client is None:
            from lightroom_sdk.client import LightroomClient

            # Only retain the client once connect() succeeds -- a failed connect must not
            # leave a half-constructed, non-connected client in self._client.
            client = LightroomClient(port_file=self._port_file)
            await client.connect()
            self._client = client
        return self._client

    async def get_status(self) -> str:
        """Get connection status for MCP resource (JSON string).

        fastmcp >=3.0 のリソースは str / bytes を返す必要がある。
        """
        import json

        if self._client is None:
            return json.dumps({"connected": False, "state": "disconnected"})
        state = self._client._bridge.state.value
        return json.dumps({"connected": state == "connected", "state": state})

    async def shutdown(self) -> None:
        """Clean shutdown."""
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
