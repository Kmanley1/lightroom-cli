from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@patch("cli.helpers.get_bridge")
def test_catalog_get_selected(mock_get_bridge, runner):
    """lr catalog get-selected が選択中の写真を返す"""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {
        "id": "1",
        "success": True,
        "result": [{"id": "photo-1", "filename": "IMG_001.jpg"}],
    }
    mock_get_bridge.return_value = mock_bridge

    result = runner.invoke(cli, ["catalog", "get-selected"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with("catalog.getSelectedPhotos", {}, timeout=30.0)


@patch("cli.helpers.get_bridge")
def test_catalog_list_with_options(mock_get_bridge, runner):
    """lr catalog list --limit 10 --offset 5 がパラメータを渡す"""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {
        "id": "2",
        "success": True,
        "result": [],
    }
    mock_get_bridge.return_value = mock_bridge

    result = runner.invoke(cli, ["catalog", "list", "--limit", "10", "--offset", "5"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with("catalog.getAllPhotos", {"limit": 10, "offset": 5}, timeout=60.0)


@patch("cli.helpers.get_bridge")
def test_catalog_set_metadata_coerces_value(mock_get_bridge, runner):
    """lr catalog set-metadata <id> rating 5 sends a number, not the string '5' (#147)."""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {}}
    mock_get_bridge.return_value = mock_bridge

    result = runner.invoke(cli, ["catalog", "set-metadata", "123", "rating", "5"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.setMetadata", {"photoId": "123", "key": "rating", "value": 5.0}, timeout=30.0
    )


@patch("cli.helpers.get_bridge")
def test_catalog_set_rating(mock_get_bridge, runner):
    """lr catalog set-rating photo-1 5 がratingを設定する"""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {
        "id": "3",
        "success": True,
        "result": {"rating": 5},
    }
    mock_get_bridge.return_value = mock_bridge

    result = runner.invoke(cli, ["catalog", "set-rating", "photo-1", "5"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.setRating", {"photoId": "photo-1", "rating": 5}, timeout=30.0
    )


@patch("cli.helpers.get_bridge")
def test_catalog_set_rating_sends_correct_command(mock_get_bridge, runner):
    """lr catalog set-rating がcatalog.setRatingコマンドを送信する"""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {
        "id": "10",
        "success": True,
        "result": {"photoId": "123", "rating": 4, "message": "Rating set successfully"},
    }
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(cli, ["catalog", "set-rating", "123", "4"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with("catalog.setRating", {"photoId": "123", "rating": 4}, timeout=30.0)


@patch("cli.helpers.get_bridge")
def test_catalog_add_keywords_sends_correct_command(mock_get_bridge, runner):
    """lr catalog add-keywords がcatalog.addKeywordsコマンドを送信する"""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {
        "id": "11",
        "success": True,
        "result": {
            "photoId": "123",
            "addedKeywords": ["landscape", "sunset"],
            "count": 2,
        },
    }
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(cli, ["catalog", "add-keywords", "123", "landscape", "sunset"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.addKeywords",
        {"photoId": "123", "keywords": ["landscape", "sunset"]},
        timeout=30.0,
    )


@patch("cli.helpers.get_bridge")
def test_catalog_add_to_collection(mock_get_bridge, runner):
    """lr catalog add-to-collection <id> <photo-ids...> sends collectionId + photoIds (collections populate)."""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {}}
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(cli, ["catalog", "add-to-collection", "42", "1", "2"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.addPhotosToCollection", {"collectionId": 42, "photoIds": ["1", "2"]}, timeout=60.0
    )


@patch("cli.helpers.get_bridge")
def test_catalog_remove_from_collection(mock_get_bridge, runner):
    """lr catalog remove-from-collection <id> <photo-ids...> sends to catalog.removePhotosFromCollection."""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {}}
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(cli, ["catalog", "remove-from-collection", "42", "7"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.removePhotosFromCollection", {"collectionId": 42, "photoIds": ["7"]}, timeout=60.0
    )


@patch("cli.helpers.get_bridge")
def test_catalog_create_collection_default(mock_get_bridge, runner):
    """create-collection sends returnExisting=True by default and omits parentId."""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {"id": 5}}
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(cli, ["catalog", "create-collection", "Trip 2026"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.createCollection", {"name": "Trip 2026", "returnExisting": True}, timeout=30.0
    )


@patch("cli.helpers.get_bridge")
def test_catalog_create_collection_with_parent(mock_get_bridge, runner):
    """--parent -> parentId (int); --no-return-existing -> returnExisting=False."""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {"id": 9}}
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(
        cli, ["catalog", "create-collection", "Japan", "--parent", "3", "--no-return-existing"]
    )
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.createCollection", {"name": "Japan", "returnExisting": False, "parentId": 3}, timeout=30.0
    )


@patch("cli.helpers.get_bridge")
def test_catalog_find_text(mock_get_bridge, runner):
    """lr catalog find --text sends searchDesc.text (free-text search)."""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {"photos": []}}
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(cli, ["catalog", "find", "--text", "sunset"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.findPhotos", {"searchDesc": {"text": "sunset"}, "limit": 50, "offset": 0}, timeout=90.0
    )


@patch("cli.helpers.get_bridge")
def test_catalog_batch_set(mock_get_bridge, runner):
    """lr catalog batch-set maps fields (flag pick->1) and keywords across photos."""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {}}
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(
        cli, ["catalog", "batch-set", "1", "2", "--rating", "5", "--flag", "pick", "--keyword", "vacation"]
    )
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.batchSetMetadata",
        {"photoIds": ["1", "2"], "rating": 5, "flag": 1, "addKeywords": ["vacation"]},
        timeout=60.0,
    )


@patch("cli.helpers.get_bridge")
def test_catalog_save_metadata(mock_get_bridge, runner):
    """lr catalog save-metadata sends photoIds to catalog.saveMetadata."""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {}}
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(cli, ["catalog", "save-metadata", "1", "2"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.saveMetadata", {"photoIds": ["1", "2"]}, timeout=120.0
    )
