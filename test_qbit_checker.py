import json
from pathlib import Path
import pytest
from qbit_checker import strategy_smallest_first

# This import will fail until we create the class in qbit_checker.py
from qbit_checker import Config, TorrentFilterBuilder


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """Creates a temporary config.json file for testing."""
    config_data = {
        "qbittorrent": {
            "host": "localhost",
            "port": 8080,
            "user": "$QBIT_CHECKER_USER",
            "pass": "$QBIT_CHECKER_PASS",
        }
    }
    config_path = tmp_path / "config.json"
    with open(config_path, "w") as f:
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
    assert config.get("qbittorrent.host") == "localhost"
    assert config.get("qbittorrent.port") == 8080
    assert config.get("qbittorrent.user") == expected_user
    assert config.get("qbittorrent.pass") == expected_pass


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
    mock_client_constructor = mocker.patch("qbit_checker.qbittorrentapi.Client")

    # 2. Execution: Instantiate our client class
    # This import will fail until we add it to qbit_checker.py
    from qbit_checker import QBitClient

    qbit_client = QBitClient(config)

    # 3. Assertion: Verify the mock was called correctly
    mock_client_constructor.assert_called_once_with(
        host="localhost", port=8080, username=expected_user, password=expected_pass
    )


def test_get_finished_torrents(config_file: Path, mocker):
    """
    Tests that the client can filter for torrents that are finished downloading.
    """
    # 1. Setup: Create a mock client and fake torrent data
    mock_qbit_client = mocker.MagicMock()

    # These are simplified representations of the TorrentDictionary objects
    mock_torrents = [
        # This torrent is "finished" but should be excluded by the current logic
        mocker.MagicMock(hash="1", state="uploading"),
        # These are the actual finished torrents we expect to get
        mocker.MagicMock(hash="2", state="stalledUP"),
        mocker.MagicMock(hash="3", state="pausedUP"),
        # Unfinished torrents (downloading)
        mocker.MagicMock(hash="4", state="downloading"),
        mocker.MagicMock(hash="5", state="stalledDL"),
        mocker.MagicMock(hash="6", state="checkingDL"),
        mocker.MagicMock(hash="7", state="metaDL"),
        mocker.MagicMock(hash="8", state="error"),
    ]
    mock_qbit_client.torrents_info.return_value = mock_torrents

    # We need to patch the client instance within our QBitClient
    mocker.patch("qbit_checker.qbittorrentapi.Client", return_value=mock_qbit_client)

    # 2. Execution
    # We use the config_file fixture to create a valid, but unused, config
    from qbit_checker import QBitClient, Config

    config = Config(config_file)
    qbit_client = QBitClient(config)
    finished_torrents = qbit_client.get_finished_torrents()

    # 3. Assertion
    assert len(finished_torrents) == 2
    finished_hashes = {t.hash for t in finished_torrents}
    assert finished_hashes == {"2", "3"}


def test_get_eligible_torrents_excludes_by_tag(config_file: Path, mocker):
    """
    Tests that eligible torrents can be filtered to exclude certain tags.
    """
    # 1. Setup
    mock_qbit_client = mocker.MagicMock()

    # Mock torrents that are all "finished", but have different tags
    mock_torrents = [
        mocker.MagicMock(hash="1", state="uploading", tags=""),  # Not eligible
        mocker.MagicMock(hash="2", state="stalledUP", tags="keep, other"),  # Eligible
        mocker.MagicMock(
            hash="3", state="pausedUP", tags="permaseed"
        ),  # Excluded by tag
        mocker.MagicMock(hash="4", state="uploading", tags="another"),  # Not eligible
    ]
    mock_qbit_client.torrents_info.return_value = mock_torrents
    mocker.patch("qbit_checker.qbittorrentapi.Client", return_value=mock_qbit_client)

    # 2. Execution
    from qbit_checker import QBitClient, Config

    config = Config(config_file)
    qbit_client = QBitClient(config)
    eligible_torrents = qbit_client.get_eligible_torrents(
        exclude_tags=["permaseed", "some_other_tag"]
    )

    # 3. Assertion
    assert len(eligible_torrents) == 1
    eligible_hashes = {t.hash for t in eligible_torrents}
    assert "3" not in eligible_hashes
    assert eligible_hashes == {"2"}


def test_get_eligible_torrents_excludes_by_tracker(config_file: Path, mocker):
    """
    Tests that eligible torrents can be filtered to exclude certain trackers.
    """
    # 1. Setup
    mock_qbit_client = mocker.MagicMock()

    # Mock torrents that are finished and untagged, but have different trackers
    # The structure of torrent.trackers is a list of objects, each with a 'url'
    mock_torrents = [
        mocker.MagicMock(
            hash="1",
            state="uploading",
            tags="",
            trackers=[{"url": "udp://public.tracker.com"}],
        ),  # Not eligible
        mocker.MagicMock(
            hash="2",
            state="stalledUP",
            tags="",
            trackers=[{"url": "udp://private.tracker.io"}],
        ),  # Excluded by tracker
        mocker.MagicMock(
            hash="3",
            state="pausedUP",
            tags="",
            trackers=[{"url": "udp://another.public.tracker"}],
        ),  # Eligible
        mocker.MagicMock(
            hash="4",
            state="uploading",
            tags="",
            trackers=[{"url": "udp://private.tracker.io"}],
        ),  # Not eligible
    ]
    mock_qbit_client.torrents_info.return_value = mock_torrents
    mocker.patch("qbit_checker.qbittorrentapi.Client", return_value=mock_qbit_client)

    # 2. Execution
    from qbit_checker import QBitClient, Config

    config = Config(config_file)
    qbit_client = QBitClient(config)
    eligible_torrents = qbit_client.get_eligible_torrents(
        exclude_trackers=["udp://private.tracker.io"]
    )

    # 3. Assertion
    assert len(eligible_torrents) == 1
    eligible_hashes = {t.hash for t in eligible_torrents}
    assert "2" not in eligible_hashes
    assert "4" not in eligible_hashes
    assert eligible_hashes == {"3"}


def test_select_torrents_for_cleanup(config_file: Path, mocker):
    """
    Tests that the torrent selection algorithm correctly picks the smallest
    torrents to free up a specific amount of space.
    """
    # 1. Setup
    # This test doesn't need a real client, just the selection logic.
    # We create mock torrents with only the 'size' and 'hash' attributes being relevant.
    gB = 1024 * 1024 * 1024
    mock_torrents = [
        mocker.MagicMock(hash="1", size=2 * gB),
        mocker.MagicMock(hash="2", size=4 * gB),
        mocker.MagicMock(hash="3", size=1 * gB),  # Smallest
        mocker.MagicMock(hash="4", size=8 * gB),  # Largest
        mocker.MagicMock(hash="5", size=3 * gB),
    ]

    # We need an instance of QBitClient to call the method from.
    from qbit_checker import QBitClient, Config

    config = Config(config_file)
    qbit_client = QBitClient(config)

    # 2. Execution
    # We want to free 5 GB. The algorithm should pick the 1GB, 2GB, and 3GB torrents.
    space_to_free = 5.5 * gB
    selected_torrents = QBitClient.select_torrents_for_cleanup(
        torrents=mock_torrents,
        space_to_free_bytes=space_to_free,
        strategy=strategy_smallest_first,
    )

    # 3. Assertion
    assert len(selected_torrents) == 3

    selected_hashes = {t.hash for t in selected_torrents}
    assert selected_hashes == {"1", "3", "5"}  # 2GB, 1GB, 3GB torrents

    total_size_freed = sum(t.size for t in selected_torrents)
    assert total_size_freed >= space_to_free
    assert total_size_freed == (1 + 2 + 3) * gB


def test_select_torrents_for_cleanup_not_enough_space(config_file: Path, mocker):
    """
    Tests that the selection algorithm returns all torrents if the space
    to free is larger than the total size of all available torrents.
    """
    # 1. Setup
    gB = 1024 * 1024 * 1024
    mock_torrents = [
        mocker.MagicMock(hash="1", size=2 * gB),
        mocker.MagicMock(hash="2", size=1 * gB),
    ]

    from qbit_checker import QBitClient, Config

    config = Config(config_file)
    qbit_client = QBitClient(config)

    # 2. Execution
    # Ask to free 10GB, but only 3GB is available.
    space_to_free = 10 * gB
    selected_torrents = QBitClient.select_torrents_for_cleanup(
        torrents=mock_torrents,
        space_to_free_bytes=space_to_free,
        strategy=strategy_smallest_first,
    )

    # 3. Assertion
    # It should return an empty list.
    assert len(selected_torrents) == 0


def test_remove_torrents_deletes_files_by_default(config_file: Path, mocker):
    """
    Tests that remove_torrents defaults to deleting files.
    """
    # 1. Setup
    mock_api_client = mocker.MagicMock()
    mocker.patch("qbit_checker.qbittorrentapi.Client", return_value=mock_api_client)
    torrents_to_delete = [mocker.MagicMock(hash="111")]

    from qbit_checker import QBitClient, Config

    config = Config(config_file)
    qbit_client = QBitClient(config)

    # 2. Execution
    qbit_client.remove_torrents(torrents_to_delete)

    # 3. Assertion
    mock_api_client.torrents_delete.assert_called_once_with(
        torrent_hashes=["111"], delete_files=True  # Check for the new default
    )


def test_remove_torrents_can_preserve_files(config_file: Path, mocker):
    """
    Tests that remove_torrents can be told to preserve files.
    """
    # 1. Setup
    mock_api_client = mocker.MagicMock()
    mocker.patch("qbit_checker.qbittorrentapi.Client", return_value=mock_api_client)
    torrents_to_delete = [mocker.MagicMock(hash="222")]

    from qbit_checker import QBitClient, Config

    config = Config(config_file)
    qbit_client = QBitClient(config)

    # 2. Execution
    qbit_client.remove_torrents(torrents_to_delete, False)

    # 3. Assertion
    mock_api_client.torrents_delete.assert_called_once_with(
        torrent_hashes=["222"], delete_files=False  # Check for the override
    )


def test_remove_torrents_empty_list(config_file: Path, mocker):
    """
    Tests that the client does NOT call the API if the torrent list is empty.
    """
    # 1. Setup
    mock_api_client = mocker.MagicMock()
    mocker.patch("qbit_checker.qbittorrentapi.Client", return_value=mock_api_client)

    from qbit_checker import QBitClient, Config

    config = Config(config_file)
    qbit_client = QBitClient(config)

    # 2. Execution
    qbit_client.remove_torrents([])  # Pass an empty list

    # 3. Assertion
    # Verify the API was NOT called
    mock_api_client.torrents_delete.assert_not_called()


# TorrentFilterBuilder Tests
# ==========================


@pytest.fixture
def mock_torrents(mocker):
    """Provides a list of mock torrent objects for filter testing."""
    gB = 1024 * 1024 * 1024
    return [
        # Torrent 1: High ratio, long seeding time
        mocker.MagicMock(
            hash="1",
            name="ubuntu-22.04.iso",
            state="stalledUP",
            tags="linux,iso",
            trackers=[{"url": "udp://tracker.opentrackr.org:1337/announce"}],
            size=10 * gB,
            completion_on=1672531200,  # 2023-01-01
            ratio=5.0,
            seeding_time=864000,  # 10 days
        ),
        # Torrent 2: Low ratio, short seeding time
        mocker.MagicMock(
            hash="2",
            name="big_buck_bunny.mp4",
            state="pausedUP",
            tags="movie,hd",
            trackers=[{"url": "http://tracker.publicbt.com/announce"}],
            size=2 * gB,
            completion_on=1675209600,  # 2023-02-01
            ratio=1.2,
            seeding_time=86400,  # 1 day
        ),
        # Torrent 3: Medium ratio, medium seeding time, private tracker
        mocker.MagicMock(
            hash="3",
            name="awesome-game.zip",
            state="stalledUP",
            tags="game",
            trackers=[{"url": "https://tracker.my-private-site.com/announce"}],
            size=50 * gB,
            completion_on=1677628800,  # 2023-03-01
            ratio=2.5,
            seeding_time=345600,  # 4 days
        ),
        # Torrent 4: No tags, very recent, still uploading
        mocker.MagicMock(
            hash="4",
            name="latest-driver.exe",
            state="uploading",
            tags="",
            trackers=[{"url": "udp://tracker.opentrackr.org:1337/announce"}],
            size=1 * gB,
            completion_on=1680307200,  # 2023-04-01
            ratio=0.5,
            seeding_time=3600,  # 1 hour
        ),
    ]


def test_filter_by_seeding_time(mock_torrents):
    """Tests filtering by seeding time."""
    # Torrents seeding for more than 5 days (should be just torrent 1)
    five_days_in_seconds = 5 * 24 * 60 * 60
    builder = TorrentFilterBuilder(mock_torrents).seeding_time_greater_than(
        five_days_in_seconds
    )
    result = builder.build()
    assert len(result) == 1
    assert result[0].hash == "1"

    # Torrents seeding for less than 2 days (should be torrents 2 and 4)
    two_days_in_seconds = 2 * 24 * 60 * 60
    builder = TorrentFilterBuilder(mock_torrents).seeding_time_less_than(
        two_days_in_seconds
    )
    result = builder.build()
    assert len(result) == 2
    assert {t.hash for t in result} == {"2", "4"}


def test_filter_by_state(mock_torrents):
    """Tests filtering by torrent state."""
    builder = TorrentFilterBuilder(mock_torrents).with_states({"pausedUP"})
    result = builder.build()
    assert len(result) == 1
    assert result[0].hash == "2"


def test_filter_by_tracker(mock_torrents):
    """Tests filtering by a substring in the tracker URL."""
    builder = TorrentFilterBuilder(mock_torrents).with_tracker_containing("private")
    result = builder.build()
    assert len(result) == 1
    assert result[0].hash == "3"


def test_filter_by_tags(mock_torrents):
    """Tests filtering by tags."""
    builder = TorrentFilterBuilder(mock_torrents).with_tags(["linux", "movie"])
    result = builder.build()
    assert len(result) == 2
    assert {t.hash for t in result} == {"1", "2"}


def test_filter_by_size(mock_torrents):
    """Tests filtering by size."""
    gB = 1024 * 1024 * 1024
    # Greater than 15 GB
    builder = TorrentFilterBuilder(mock_torrents).with_size_greater_than(15 * gB)
    result = builder.build()
    assert len(result) == 1
    assert result[0].hash == "3"

    # Less than 5 GB
    builder = TorrentFilterBuilder(mock_torrents).with_size_less_than(5 * gB)
    result = builder.build()
    assert len(result) == 2
    assert {t.hash for t in result} == {"2", "4"}


def test_filter_by_completion_date(mock_torrents):
    """Tests filtering by completion date."""
    # Completed before Feb 15, 2023
    builder = TorrentFilterBuilder(mock_torrents).completed_before(1676419200)
    result = builder.build()
    assert len(result) == 2
    assert {t.hash for t in result} == {"1", "2"}

    # Completed after Feb 15, 2023
    builder = TorrentFilterBuilder(mock_torrents).completed_after(1676419200)
    result = builder.build()
    assert len(result) == 2
    assert {t.hash for t in result} == {"3", "4"}


def test_filter_by_ratio(mock_torrents):
    """Tests filtering by ratio."""
    builder = TorrentFilterBuilder(mock_torrents).with_ratio_greater_than(3.0)
    result = builder.build()
    assert len(result) == 1
    assert result[0].hash == "1"


def test_filter_chaining(mock_torrents):
    """Tests chaining multiple filters together."""
    five_days_in_seconds = 5 * 24 * 60 * 60
    gB = 1024 * 1024 * 1024

    builder = (
        TorrentFilterBuilder(mock_torrents)
        .with_states({"stalledUP", "uploading"})  # Torrents 1, 3, 4
        .with_ratio_greater_than(1.0)  # Torrents 1, 3
        .with_size_less_than(20 * gB)  # Torrent 1
        .seeding_time_greater_than(five_days_in_seconds)  # Torrent 1
    )
    result = builder.build()
    assert len(result) == 1
    assert result[0].hash == "1"


def test_no_filters_returns_all_torrents(mock_torrents):
    """Tests that calling build() with no filters returns the original list."""
    builder = TorrentFilterBuilder(mock_torrents)
    result = builder.build()
    assert len(result) == len(mock_torrents)
    assert {t.hash for t in result} == {"1", "2", "3", "4"}
