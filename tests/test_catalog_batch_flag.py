"""バッチフラグ設定のテスト (catalog.batchSetFlag)"""

import pytest

from lightroom_sdk.client import LightroomClient
from lightroom_sdk.exceptions import LightroomSDKError


@pytest.mark.asyncio
async def test_batch_set_flag_reject_multiple_photos(mock_lr_server):
    """3枚の写真にRejectフラグを一括設定し、全枚の結果が返ること"""
    mock_lr_server.register_response(
        "catalog.batchSetFlag",
        {
            "processed": 3,
            "succeeded": 3,
            "results": [
                {"photoId": 1, "success": True},
                {"photoId": 2, "success": True},
                {"photoId": 3, "success": True},
            ],
        },
    )
    async with LightroomClient(port_file=str(mock_lr_server.port_file)) as client:
        result = await client.execute_command(
            "catalog.batchSetFlag",
            {"photoIds": [1, 2, 3], "flag": -1},
        )
    assert result["processed"] == 3
    assert result["succeeded"] == 3
    assert len(result["results"]) == 3
    assert all(r["success"] for r in result["results"])


@pytest.mark.asyncio
async def test_batch_set_flag_partial_failure(mock_lr_server):
    """5枚中2枚が見つからない場合、3枚は成功し部分結果が返ること"""
    mock_lr_server.register_response(
        "catalog.batchSetFlag",
        {
            "processed": 5,
            "succeeded": 3,
            "results": [
                {"photoId": 1, "success": True},
                {"photoId": 2, "success": False, "error": "Photo not found"},
                {"photoId": 3, "success": True},
                {"photoId": 4, "success": False, "error": "Photo not found"},
                {"photoId": 5, "success": True},
            ],
        },
    )
    async with LightroomClient(port_file=str(mock_lr_server.port_file)) as client:
        result = await client.execute_command(
            "catalog.batchSetFlag",
            {"photoIds": [1, 2, 3, 4, 5], "flag": -1},
        )
    assert result["processed"] == 5
    assert result["succeeded"] == 3
    failed = [r for r in result["results"] if not r["success"]]
    assert len(failed) == 2


@pytest.mark.asyncio
async def test_batch_set_flag_max_50_limit(mock_lr_server):
    """51枚指定でエラーが返ること"""
    mock_lr_server.register_response(
        "catalog.batchSetFlag",
        {"error": {"code": "BATCH_SIZE_EXCEEDED", "message": "Maximum batch size is 50 photos"}},
    )
    async with LightroomClient(port_file=str(mock_lr_server.port_file)) as client:
        with pytest.raises(LightroomSDKError) as exc_info:
            await client.execute_command(
                "catalog.batchSetFlag",
                {"photoIds": list(range(1, 52)), "flag": -1},
            )
    assert exc_info.value.code == "BATCH_SIZE_EXCEEDED"


@pytest.mark.asyncio
async def test_batch_set_flag_empty_photo_ids(mock_lr_server):
    """空の photoIds でエラー"""
    mock_lr_server.register_response(
        "catalog.batchSetFlag",
        {"error": {"code": "MISSING_PHOTO_IDS", "message": "photoIds array is required"}},
    )
    async with LightroomClient(port_file=str(mock_lr_server.port_file)) as client:
        with pytest.raises(LightroomSDKError) as exc_info:
            await client.execute_command(
                "catalog.batchSetFlag",
                {"photoIds": [], "flag": -1},
            )
    assert exc_info.value.code == "MISSING_PHOTO_IDS"


@pytest.mark.asyncio
async def test_batch_set_flag_invalid_flag_value(mock_lr_server):
    """flag が 1/-1/0 以外の場合エラー"""
    mock_lr_server.register_response(
        "catalog.batchSetFlag",
        {"error": {"code": "INVALID_PARAM_VALUE", "message": "flag must be 1 (pick), -1 (reject), or 0 (none)"}},
    )
    async with LightroomClient(port_file=str(mock_lr_server.port_file)) as client:
        with pytest.raises(LightroomSDKError) as exc_info:
            await client.execute_command(
                "catalog.batchSetFlag",
                {"photoIds": [1, 2], "flag": 99},
            )
    assert exc_info.value.code == "INVALID_PARAM_VALUE"
