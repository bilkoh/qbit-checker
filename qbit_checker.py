import os
import json
import qbittorrentapi
from typing import Any, Optional
from dotenv import load_dotenv


class QBitClient:
    """A client for interacting with the qBittorrent API."""

    _FINISHED_STATES = {
        # "uploading",  # has leechers
        "stalledUP",
        "pausedUP",
        "checkingUP",
        "forcedUP",
    }

    def __init__(self, config: "Config"):
        self._client = qbittorrentapi.Client(
            host=config.get("qbittorrent.host"),
            port=config.get("qbittorrent.port"),
            username=config.get("qbittorrent.user"),
            password=config.get("qbittorrent.pass"),
        )

    def get_finished_torrents(self):
        """
        Retrieves all torrents and filters for those that are finished downloading.
        Finished states include various forms of uploading/seeding.
        """
        all_torrents = self._client.torrents_info()
        return [
            torrent
            for torrent in all_torrents
            if torrent.state in self._FINISHED_STATES
        ]

    def get_eligible_torrents(
        self, exclude_tags: list[str] = None, exclude_trackers: list[str] = None
    ):
        """
        Retrieves finished torrents and filters them based on provided criteria.
        """
        # Start with finished torrents
        candidates = self.get_finished_torrents()

        # Filter by excluded tags
        if exclude_tags:
            excluded_tags_set = set(exclude_tags)
            candidates = [
                t
                for t in candidates
                if not set(tag.strip() for tag in t.tags.split(",")).intersection(
                    excluded_tags_set
                )
            ]

        # Filter by excluded trackers
        if exclude_trackers:
            excluded_trackers_set = set(exclude_trackers)
            candidates = [
                t
                for t in candidates
                if not {tracker["url"] for tracker in t.trackers}.intersection(
                    excluded_trackers_set
                )
            ]

        return candidates

    @staticmethod
    def select_torrents_for_cleanup(
        torrents: list, space_to_free_bytes: int, strategy: callable
    ) -> list:
        """
        Selects torrents from a list to free up space using a given strategy.

        :param torrents: A list of torrent objects.
        :param space_to_free_bytes: The target amount of space to free in bytes.
        :param strategy: A function that takes a list of torrents and returns a sorted list.
        :return: A list of torrents that meet the space requirement, or an empty list.
        """
        # First, check if it's even possible to free the required space.
        total_available_space = sum(t.size for t in torrents)
        if total_available_space < space_to_free_bytes:
            return []

        # Apply the provided strategy to sort the torrents.
        sorted_torrents = strategy(torrents)

        selected_for_deletion = []
        space_freed = 0

        for torrent in sorted_torrents:
            if space_freed >= space_to_free_bytes:
                break
            selected_for_deletion.append(torrent)
            space_freed += torrent.size

        return selected_for_deletion

    def remove_torrents(self, torrents: list, delete_files: bool = True):
        """
        Removes a list of torrents from the qBittorrent client.

        :param torrents: A list of torrent objects to remove.
        :param delete_files: If True, deletes the torrent's data from disk. Defaults to True.
        """
        if not torrents:
            return  # Do nothing if the list is empty

        torrent_hashes = [t.hash for t in torrents]
        self._client.torrents_delete(
            torrent_hashes=torrent_hashes, delete_files=delete_files
        )


class TorrentFilterBuilder:
    """Builds a set of filters to apply to a list of torrents."""

    def __init__(self, torrents: list):
        self._torrents = torrents
        self._filters = []

    def with_states(self, states: set[str]):
        self._filters.append(lambda t: t.state in states)
        return self

    def with_tracker_containing(self, substring: str):
        self._filters.append(
            lambda t: any(substring in tracker["url"] for tracker in t.trackers)
        )
        return self

    def with_tags(self, tags: list[str]):
        tag_set = set(tags)
        self._filters.append(
            lambda t: tag_set.intersection({tag.strip() for tag in t.tags.split(",")})
        )
        return self

    def without_tags(self, tags: list[str]):
        tag_set = set(tags)
        self._filters.append(
            lambda t: not tag_set.intersection(
                {tag.strip() for tag in t.tags.split(",")}
            )
        )
        return self

    def with_size_greater_than(self, size_bytes: int):
        self._filters.append(lambda t: t.size > size_bytes)
        return self

    def with_size_less_than(self, size_bytes: int):
        self._filters.append(lambda t: t.size < size_bytes)
        return self

    def completed_before(self, timestamp: int):
        self._filters.append(lambda t: t.completion_on < timestamp)
        return self

    def completed_after(self, timestamp: int):
        self._filters.append(lambda t: t.completion_on > timestamp)
        return self

    def with_ratio_greater_than(self, ratio: float):
        self._filters.append(lambda t: t.ratio > ratio)
        return self

    def seeding_time_greater_than(self, seconds: int):
        self._filters.append(lambda t: t.seeding_time > seconds)
        return self

    def seeding_time_less_than(self, seconds: int):
        self._filters.append(lambda t: t.seeding_time < seconds)
        return self

    def build(self) -> list:
        """Applies all configured filters and returns the matching torrents."""
        if not self._filters:
            return self._torrents

        return [
            torrent
            for torrent in self._torrents
            if all(f(torrent) for f in self._filters)
        ]


# --- Cleanup Strategies ---


def strategy_smallest_first(torrents: list) -> list:
    """Sorts torrents by size, smallest first."""
    return sorted(torrents, key=lambda t: t.size)


def strategy_score_by_seeding_time(torrents: list) -> list:
    """
    Sorts torrents by a score of (seeding_days / size_gb), highest score first.
    This prioritizes torrents that have seeded the longest for their size.
    """
    # The torrents with the highest score will be selected for deletion first.
    return sorted(
        torrents,
        key=lambda t: (
            ((t.seeding_time / 86400) / (t.size / (1024**3))) if t.size > 0 else 0
        ),
        reverse=True,
    )


class Config:
    """
    Manages loading configuration from a JSON file and expanding environment variables.
    """

    def __init__(self, config_path: str):
        load_dotenv()  # Load variables from .env file into the environment
        self._config = self._load_config(config_path)

    def _load_config(self, config_path: str) -> dict:
        """Loads the config file and expands any environment variables."""
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
        except (FileNotFoundError, TypeError):
            # If the path is None/invalid or not found, treat it as an empty config
            return {}

        self._expand_variables(config_data)
        return config_data

    def _expand_variables(self, data: Any):
        """Recursively traverses the config data to find and replace env var placeholders."""
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and value.startswith("$"):
                    data[key] = os.getenv(value[1:])
                else:
                    self._expand_variables(value)
        elif isinstance(data, list):
            for index, item in enumerate(data):
                if isinstance(item, str) and item.startswith("$"):
                    data[index] = os.getenv(item[1:])
                else:
                    self._expand_variables(item)

    def get(self, key_path: str, default: Optional[Any] = None) -> Optional[Any]:
        """
        Retrieves a value from the configuration using dot notation.
        e.g., get('qbittorrent.host')
        """
        keys = key_path.split(".")
        value = self._config
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
