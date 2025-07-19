import pytest
from qbit_checker import QBitClient, Config

# Mark all tests in this file as 'integration'
pytestmark = pytest.mark.integration

PERMASEED_TAG = "permaseed"
TRACKER_URL = "lst.gg"


@pytest.fixture(scope="module")
def live_qbit_client():
    """
    Provides a QBitClient instance connected to a live server.
    Fails if the config file is missing or connection fails.
    """
    # Assumes integ-test-config.json is in the project root
    config = Config("integ-test-config.json")

    # Check that config loaded properly for a sane test environment
    assert config.get("qbittorrent.host"), "Host not found in integ-test-config.json"

    client = QBitClient(config)

    # Verify connection before running tests
    try:
        client._client.auth_log_in()
    except Exception as e:
        pytest.fail(
            f"Failed to connect to qBittorrent. Is it running and is integ-test-config.json correct? Error: {e}"
        )

    return client


def test_fetch_and_validate_torrent_data_structure(live_qbit_client: QBitClient):
    """
    Tests that we can fetch torrents and that their data structure
    matches what our application expects.
    """
    # 1. Execution: Fetch all torrents without any filters
    # This tests the most basic interaction with the API.
    all_torrents = live_qbit_client.get_finished_torrents()

    # 2. Assertion: Check the data shape and types
    assert isinstance(all_torrents, list)

    # If you have no finished torrents on your test instance, this test will still pass.
    # To get full value, ensure at least one finished torrent is present.
    if not all_torrents:
        print(
            "\nWARNING: No finished torrents found on the server. Test is passing but not validating data structure."
        )
        return

    # Validate the structure of the first torrent object
    torrent = all_torrents[0]
    print(f"\nINFO: Validating structure of torrent: {torrent.name}")

    assert hasattr(torrent, "state"), "Torrent object missing 'state' attribute"
    assert isinstance(torrent.state, str)

    assert hasattr(torrent, "tags"), "Torrent object missing 'tags' attribute"
    assert isinstance(torrent.tags, str)

    assert (
        len([torrent for torrent in all_torrents if torrent.tags == "permaseed"]) > 0
    ), "No torrents with 'permaseed' tag found"

    assert hasattr(torrent, "size"), "Torrent object missing 'size' attribute"
    assert isinstance(torrent.size, int)

    assert hasattr(torrent, "hash"), "Torrent object missing 'hash' attribute"
    assert isinstance(torrent.hash, str)

    assert hasattr(torrent, "trackers"), "Torrent object missing 'trackers' attribute"
    # The 'trackers' attribute is a list-like object, not a plain list.
    # We can check for an attribute that all list-like objects have, like __iter__
    # assert hasattr(torrent.trackers, "__iter__"), "torrent.trackers is not iterable"


def test_torrents_have_specific_tracker(live_qbit_client: QBitClient):
    """
    Tests that the fetched torrents include at least one torrent
    with a tracker URL that partially matches a specific string.
    """
    all_torrents = live_qbit_client.get_finished_torrents()

    if not all_torrents:
        pytest.skip("No finished torrents found to test tracker matching.")

    # Check if any torrent's tracker URL contains the specified string
    tracker_found = any(TRACKER_URL in torrent.tracker for torrent in all_torrents)

    assert tracker_found, f"No torrent found with tracker containing '{TRACKER_URL}'"
