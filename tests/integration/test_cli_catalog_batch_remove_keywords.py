import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from cli.main import cli

OK = {"id": "1", "success": True,
      "result": {"requested": 2, "removed": 2, "notOnPhoto": 0, "photoNotFound": 0, "stillPresent": 0,
                 "unverified": 0, "complete": True, "writeRan": True, "results": []}}


@pytest.fixture
def runner():
    return CliRunner()


def _bridge(mock_get_bridge):
    b = AsyncMock()
    b.send_command.return_value = OK
    mock_get_bridge.return_value = b
    return b


def _sent(bridge):
    args, kwargs = bridge.send_command.call_args
    return args, kwargs


@patch("cli.helpers.get_bridge")
def test_pairs_file_as_lists(mock_get_bridge, runner, tmp_path):
    b = _bridge(mock_get_bridge)
    f = tmp_path / "pairs.json"
    f.write_text(json.dumps([[10, 7], [11, 7]]))
    result = runner.invoke(cli, ["catalog", "batch-remove-keywords", "--pairs-file", str(f)])
    assert result.exit_code == 0, result.output
    args, _ = _sent(b)
    assert args[0] == "catalog.batchRemoveKeywords"
    assert args[1] == {"pairs": [{"photoId": 10, "keywordId": 7}, {"photoId": 11, "keywordId": 7}]}


@patch("cli.helpers.get_bridge")
def test_pairs_file_as_objects(mock_get_bridge, runner, tmp_path):
    b = _bridge(mock_get_bridge)
    f = tmp_path / "pairs.json"
    f.write_text(json.dumps([{"photoId": 10, "keywordId": 7}]))
    result = runner.invoke(cli, ["catalog", "batch-remove-keywords", "--pairs-file", str(f)])
    assert result.exit_code == 0, result.output
    assert _sent(b)[0][1] == {"pairs": [{"photoId": 10, "keywordId": 7}]}


@pytest.mark.parametrize("content", ["[]", "{}", '[[1, "x"]]', "[[1, 2, 3]]", "[[true, 2]]", "not json"])
@patch("cli.helpers.get_bridge")
def test_bad_pairs_file_is_rejected(mock_get_bridge, runner, tmp_path, content):
    b = _bridge(mock_get_bridge)
    f = tmp_path / "pairs.json"
    f.write_text(content)
    result = runner.invoke(cli, ["catalog", "batch-remove-keywords", "--pairs-file", str(f)])
    assert result.exit_code == 2
    b.send_command.assert_not_called()


@patch("cli.helpers.get_bridge")
def test_more_than_200_distinct_pairs_is_rejected(mock_get_bridge, runner, tmp_path):
    b = _bridge(mock_get_bridge)
    f = tmp_path / "pairs.json"
    f.write_text(json.dumps([[1, k] for k in range(201)]))
    result = runner.invoke(cli, ["catalog", "batch-remove-keywords", "--pairs-file", str(f)])
    assert result.exit_code == 2
    b.send_command.assert_not_called()


@patch("cli.helpers.get_bridge")
def test_requires_a_pairs_source(mock_get_bridge, runner):
    b = _bridge(mock_get_bridge)
    result = runner.invoke(cli, ["catalog", "batch-remove-keywords"])
    assert result.exit_code == 2
    b.send_command.assert_not_called()


@patch("cli.helpers.get_bridge")
def test_catalog_path_is_passed(mock_get_bridge, runner, tmp_path):
    b = _bridge(mock_get_bridge)
    f = tmp_path / "pairs.json"
    f.write_text(json.dumps([[10, 7]]))
    result = runner.invoke(cli, ["catalog", "batch-remove-keywords", "--pairs-file", str(f),
                                 "--catalog-path", "C:/x/Carolyn.lrcat"])
    assert result.exit_code == 0, result.output
    assert _sent(b)[0][1] == {"pairs": [{"photoId": 10, "keywordId": 7}], "catalogPath": "C:/x/Carolyn.lrcat"}


@patch("cli.helpers.get_bridge")
def test_json_input_passes_through(mock_get_bridge, runner):
    b = _bridge(mock_get_bridge)
    payload = {"pairs": [{"photoId": 3, "keywordId": 4}]}
    result = runner.invoke(cli, ["catalog", "batch-remove-keywords", "--json", json.dumps(payload)])
    assert result.exit_code == 0, result.output
    assert _sent(b)[0][1] == payload
