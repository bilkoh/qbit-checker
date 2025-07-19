import os
import json
from pathlib import Path
import pytest

# This import will fail until we create the class in qbit_checker.py
from qbit_checker import Config

@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """Creates a temporary config.json file for testing."""
    config_data = {
        "qbittorrent": {
            "host": "localhost",
            "port": 8080,
            "user": "$QBIT_CHECKER_USER",
            "pass": "$QBIT_CHECKER_PASS"
        }
    }
    config_path = tmp_path / "config.json"
    with open(config_path, 'w') as f:
        json.dump(config_data, f)
    return config_path

def test_config_loads_from_file_and_expands_env_vars(config_file: Path, monkeypatch):
    """
    Tests that the Config class correctly loads settings from a JSON file
    and expands environment variable placeholders.
    """
    # 1. Setup: Set environment variables for the test
    expected_user = "test_user"
    expected_pass = "supersecret"
    monkeypatch.setenv("QBIT_CHECKER_USER", expected_user)
    monkeypatch.setenv("QBIT_CHECKER_PASS", expected_pass)

    # 2. Execution: Create a Config instance (this is the code we need to write)
    config = Config(config_file)

    # 3. Assertion: Check that the values are loaded and expanded correctly
    assert config.get('qbittorrent.host') == "localhost"
    assert config.get('qbittorrent.port') == 8080
    assert config.get('qbittorrent.user') == expected_user
    assert config.get('qbittorrent.pass') == expected_pass

def test_qbit_client_initializes_connection(config_file: Path, monkeypatch, mocker):
    """
    Tests that QBitClient correctly initializes the qbittorrentapi.Client
    with credentials from the config.
    """
    # 1. Setup: Prepare config and mock the API client
    expected_user = "test_user"
    expected_pass = "supersecret"
    monkeypatch.setenv("QBIT_CHECKER_USER", expected_user)
    monkeypatch.setenv("QBIT_CHECKER_PASS", expected_pass)
    
    config = Config(config_file)
    
    # This is the core of the mock. We replace the real Client with a mock object.
    mock_client_constructor = mocker.patch('qbit_checker.qbittorrentapi.Client')

    # 2. Execution: Instantiate our client class
    # This import will fail until we add it to qbit_checker.py
    from qbit_checker import QBitClient
    qbit_client = QBitClient(config)

    # 3. Assertion: Verify the mock was called correctly
    mock_client_constructor.assert_called_once_with(
        host='localhost',
        port=8080,
        username=expected_user,
        password=expected_pass
    )

def test_get_finished_torrents(config_file: Path, mocker):
    """
    Tests that the client can filter for torrents that are finished downloading.
    """
    # 1. Setup: Create a mock client and fake torrent data
    mock_qbit_client = mocker.MagicMock()
    
    # These are simplified representations of the TorrentDictionary objects
    mock_torrents = [
        # Finished torrents (seeding)
        mocker.MagicMock(hash='1', state='uploading'),
        mocker.MagicMock(hash='2', state='stalledUP'),
        mocker.MagicMock(hash='3', state='pausedUP'),
        
        # Unfinished torrents (downloading)
        mocker.MagicMock(hash='4', state='downloading'),
        mocker.MagicMock(hash='5', state='stalledDL'),
        mocker.MagicMock(hash='6', state='checkingDL'),
        mocker.MagicMock(hash='7', state='metaDL'),
        mocker.MagicMock(hash='8', state='error'),
    ]
    mock_qbit_client.torrents_info.return_value = mock_torrents

    # We need to patch the client instance within our QBitClient
    mocker.patch('qbit_checker.qbittorrentapi.Client', return_value=mock_qbit_client)
    
    # 2. Execution
    # We use the config_file fixture to create a valid, but unused, config
    from qbit_checker import QBitClient, Config
    config = Config(config_file)
    qbit_client = QBitClient(config)
    finished_torrents = qbit_client.get_finished_torrents()

    # 3. Assertion
    assert len(finished_torrents) == 3
    finished_hashes = {t.hash for t in finished_torrents}
    assert finished_hashes == {'1', '2', '3'}
