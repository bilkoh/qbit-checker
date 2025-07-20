#!/usr/bin/env python3
import argparse
import sys
import shutil
import time
from qbit_checker import (
    QBitClient,
    Config,
    TorrentFilterBuilder,
    strategy_smallest_first,
)

# --- Constants ---
GIB_TO_BYTES = 1024 * 1024 * 1024
# Time to wait in seconds for qBittorrent and the OS to process file deletions.
POST_DELETE_SLEEP_SECONDS = 10
# Assumes the config file is in the same directory as the script.
DEFAULT_CONFIG_FILE = "config.json"


def check_free_space(path: str, required_bytes: int) -> bool:
    """Checks if the free space at a given path meets the required amount."""
    try:
        _, _, free = shutil.disk_usage(path)
        print(
            f"INFO: Path: '{path}' | Required: {required_bytes / GIB_TO_BYTES:.2f} GiB | Available: {free / GIB_TO_BYTES:.2f} GiB"
        )
        return free >= required_bytes
    except FileNotFoundError:
        print(f"ERROR: The specified path '{path}' does not exist.", file=sys.stderr)
        sys.exit(1)


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Checks for sufficient disk space and attempts to free it up by removing torrents if necessary."
    )
    parser.add_argument(
        "path",
        type=str,
        help="The filesystem path to check for free space (e.g., '/downloads').",
    )
    parser.add_argument(
        "bytes", type=int, help="The required amount of free space in bytes."
    )
    parser.add_argument(
        "--config",
        type=str,
        default=DEFAULT_CONFIG_FILE,
        help=f"Path to the configuration file (default: {DEFAULT_CONFIG_FILE}).",
    )
    args = parser.parse_args()

    required_space_bytes = args.bytes

    # 1. Initial Check: See if we already have enough space.
    print("--- Initial Disk Space Check ---")
    if check_free_space(args.path, required_space_bytes):
        print("SUCCESS: Sufficient disk space is already available.")
        sys.exit(0)

    # 2. Cleanup Process: If not enough space, try to free some up.
    print("\n--- Attempting to Free Space by Removing Torrents ---")

    # Calculate how much space we actually need to free
    _, _, current_free_bytes = shutil.disk_usage(args.path)
    space_deficit_bytes = required_space_bytes - current_free_bytes
    print(
        f"INFO: Need to free {space_deficit_bytes / GIB_TO_BYTES:.2f} GiB to meet requirement"
    )

    try:
        config = Config(args.config)
        client = QBitClient(config)
        # Verify connection
        client._client.auth_log_in()
    except Exception as e:
        print(
            f"ERROR: Failed to connect to qBittorrent. Please check '{args.config}'. Error: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Define filter criteria (similar to the integration test)
    # These could be moved into the config file for more flexibility.
    states_to_check = {"stalledUP", "pausedUP", "checkingUP", "forcedUP"}
    min_seeding_time_seconds = 3 * 24 * 60 * 60  # 3 days
    tags_to_exclude = ["permaseed", "keep"]

    all_torrents = client._client.torrents_info()
    if not all_torrents:
        print("INFO: No torrents found on the server. Cannot free space.")
        sys.exit(1)

    # Filter torrents to find candidates for removal
    filtered_torrents = (
        TorrentFilterBuilder(all_torrents)
        .with_states(states_to_check)
        .seeding_time_greater_than(min_seeding_time_seconds)
        .without_tags(tags_to_exclude)
        .build()
    )

    if not filtered_torrents:
        print("INFO: No torrents matched the filter criteria for removal.")
        sys.exit(1)

    # Select which torrents to remove based on the space deficit (not the total required space)
    torrents_to_remove = QBitClient.select_torrents_for_cleanup(
        torrents=filtered_torrents,
        space_to_free_bytes=space_deficit_bytes,
        strategy=strategy_smallest_first,
    )

    if not torrents_to_remove:
        print(
            "INFO: Could not find a combination of torrents to free the required space."
        )
        sys.exit(1)

    # Remove the torrents
    print(f"INFO: Removing {len(torrents_to_remove)} torrent(s) to free up space...")
    for t in torrents_to_remove:
        print(f" - Deleting: {t.name} ({t.size / GIB_TO_BYTES:.2f} GiB)")

    client.remove_torrents(torrents_to_remove, True)
    print("INFO: Torrent removal command sent to qBittorrent.")

    # 3. Post-Cleanup Check
    print(
        f"\n--- Post-Cleanup Disk Space Check (waiting {POST_DELETE_SLEEP_SECONDS}s) ---"
    )
    time.sleep(POST_DELETE_SLEEP_SECONDS)

    if check_free_space(args.path, required_space_bytes):
        print("SUCCESS: Sufficient disk space has been freed.")
        sys.exit(0)
    else:
        print(
            "FAILURE: Failed to free sufficient disk space after cleanup.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
