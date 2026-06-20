from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@patch("cli.helpers.get_bridge")
def test_export_files_default_original_passthrough(mock_get_bridge, runner):
    """export files --dest X --photo-ids 1,2 -> ORIGINAL passthrough (no format key sent; Lua defaults it)."""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {}}
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(cli, ["export", "files", "--dest", "C:/out", "--photo-ids", "1,2"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.exportPhotos",
        {"dest": "C:/out", "continueOnError": True, "photoIds": ["1", "2"]},
        timeout=300.0,
    )


@patch("cli.helpers.get_bridge")
def test_export_files_jpeg_quality_resize(mock_get_bridge, runner):
    """Raster format passes format/quality/resizeLongEdge through to the bridge."""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {}}
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(
        cli,
        ["export", "files", "--dest", "C:/out", "--format", "JPEG", "--quality", "80", "--resize-long-edge", "1024"],
    )
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.exportPhotos",
        {"dest": "C:/out", "continueOnError": True, "format": "JPEG", "quality": 80, "resizeLongEdge": 1024},
        timeout=300.0,
    )


def test_export_files_requires_dest(runner):
    """--dest is mandatory (click usage error, nonzero exit)."""
    result = runner.invoke(cli, ["export", "files"])
    assert result.exit_code != 0


@patch("cli.helpers.get_bridge")
def test_export_files_rejects_bad_format(mock_get_bridge, runner):
    """--format GIF is rejected by click Choice and never reaches the bridge."""
    mock_bridge = AsyncMock()
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(cli, ["export", "files", "--dest", "C:/out", "--format", "GIF"])
    assert result.exit_code != 0
    mock_bridge.send_command.assert_not_called()


@patch("cli.helpers.get_bridge")
def test_export_files_rejects_garbage_photo_ids(mock_get_bridge, runner):
    """--photo-ids ',,,' must NOT silently fall back to the current selection -- it's rejected (footgun guard)."""
    mock_bridge = AsyncMock()
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(cli, ["export", "files", "--dest", "C:/out", "--photo-ids", ",,,"])
    assert result.exit_code != 0
    mock_bridge.send_command.assert_not_called()


@patch("cli.helpers.get_bridge")
def test_export_files_stop_on_error(mock_get_bridge, runner):
    """--stop-on-error sends continueOnError=False."""
    mock_bridge = AsyncMock()
    mock_bridge.send_command.return_value = {"id": "x", "success": True, "result": {}}
    mock_get_bridge.return_value = mock_bridge
    result = runner.invoke(cli, ["export", "files", "--dest", "C:/out", "--photo-ids", "1", "--stop-on-error"])
    assert result.exit_code == 0
    mock_bridge.send_command.assert_called_once_with(
        "catalog.exportPhotos", {"dest": "C:/out", "continueOnError": False, "photoIds": ["1"]}, timeout=300.0
    )
