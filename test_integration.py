import pytest
from qbit_checker import QBitClient, Config, TorrentFilterBuilder

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


def test_full_filter_and_prune_scenario(live_qbit_client: QBitClient):
    """
    An integration test that simulates a full workflow:
    1. Fetches all torrents.
    2. Filters them based on multiple criteria using TorrentFilterBuilder.
    3. Sorts the result by size.
    4. Prunes the list to find the smallest torrents to free a target space.
    """
    # --- 1. Setup: Define criteria ---
    gB = 1024 * 1024 * 1024
    three_days_in_seconds = 3 * 24 * 60 * 60
    space_to_free_bytes = 50 * gB

    states_to_check = {"stalledUP", "pausedUP", "checkingUP", "forcedUP"}
    tracker_domain = "upload.cx"

    # --- 2. Execution: Fetch all torrents ---
    all_torrents = live_qbit_client._client.torrents_info()
    print(f"\nINFO: Found {len(all_torrents)} total torrents on the server.")
    if not all_torrents:
        pytest.skip("No torrents found on the server to test filtering.")

    # --- 3. Execution: Filter using the builder ---
    builder = (
        TorrentFilterBuilder(all_torrents)
        .with_states(states_to_check)
        .seeding_time_greater_than(three_days_in_seconds)
        .with_tracker_containing(tracker_domain)
    )
    filtered_torrents = builder.build()
    print(f"INFO: Found {len(filtered_torrents)} torrents after filtering.")

    if not filtered_torrents:
        print(
            "WARNING: No torrents matched the filter criteria. The pruning step will be skipped."
        )
        # We can assert that the list is empty and end the test.
        assert len(filtered_torrents) == 0
        return

    # --- 4. Execution: Prune the list ---
    # This static method sorts by size and selects the smallest torrents.
    torrents_to_prune = QBitClient.select_torrents_for_cleanup(
        torrents=filtered_torrents, space_to_free_bytes=space_to_free_bytes
    )
    print(f"INFO: Selected {len(torrents_to_prune)} torrents to prune.")
    for t in torrents_to_prune:
        print(f" - {t.name} ({t.size / gB:.5f} GB)")

    # --- 5. Assertion ---
    total_size_of_filtered = sum(t.size for t in filtered_torrents)
    if total_size_of_filtered < space_to_free_bytes:
        # If not enough torrents meet the criteria, the prune list should be empty.
        print(
            f"INFO: Total size of filtered torrents ({total_size_of_filtered / gB:.2f} GB) "
            f"is less than the target ({space_to_free_bytes / gB:.2f} GB). "
            "Expecting an empty prune list."
        )
        assert len(torrents_to_prune) == 0
    else:
        # If enough space is available, we expect a non-empty list.
        assert (
            len(torrents_to_prune) > 0
        ), "Expected to select torrents for pruning, but the list is empty."

        size_of_pruned = sum(t.size for t in torrents_to_prune)
        print(
            f"INFO: Cumulative size of pruned torrents is {size_of_pruned / gB:.2f} GB."
        )
        # The collected size should be greater than or equal to the target.
        assert size_of_pruned >= space_to_free_bytes


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
