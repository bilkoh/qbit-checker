import os
import json
import qbittorrentapi
from typing import Any, Optional

class QBitClient:
    """A client for interacting with the qBittorrent API."""
    def __init__(self, config: 'Config'):
        self._client = qbittorrentapi.Client(
            host=config.get('qbittorrent.host'),
            port=config.get('qbittorrent.port'),
            username=config.get('qbittorrent.user'),
            password=config.get('qbittorrent.pass')
        )

    def get_finished_torrents(self):
        """
        Retrieves all torrents and filters for those that are finished downloading.
        Finished states include various forms of uploading/seeding.
        """
        all_torrents = self._client.torrents_info()
        finished_states = {'uploading', 'stalledUP', 'pausedUP', 'checkingUP', 'forcedUP'}
        
        return [
            torrent for torrent in all_torrents 
            if torrent.state in finished_states
        ]

    def get_eligible_torrents(self, exclude_tags: list[str] = None, exclude_trackers: list[str] = None):
        """
        Retrieves finished torrents and filters them based on provided criteria.
        """
        # Start with finished torrents
        candidates = self.get_finished_torrents()

        # Filter by excluded tags
        if exclude_tags:
            excluded_tags_set = set(exclude_tags)
            candidates = [
                t for t in candidates 
                if not set(tag.strip() for tag in t.tags.split(',')).intersection(excluded_tags_set)
            ]

        # Filter by excluded trackers
        if exclude_trackers:
            excluded_trackers_set = set(exclude_trackers)
            filtered_candidates = []
            for torrent in candidates:
                # A torrent can have multiple trackers. If any of them are in the exclusion list, we skip the torrent.
                torrent_tracker_urls = {tracker['url'] for tracker in torrent.trackers}
                if not torrent_tracker_urls.intersection(excluded_trackers_set):
                    filtered_candidates.append(torrent)
            candidates = filtered_candidates
            
        return candidates

    def select_torrents_for_cleanup(self, torrents: list, space_to_free_bytes: int) -> list:
        """
        Selects the smallest torrents from a list to free up a target amount of space.

        :param torrents: A list of torrent objects (must have a 'size' attribute).
        :param space_to_free_bytes: The target amount of space to free in bytes.
        :return: A list of the smallest torrents that meet the space requirement, or an empty list if not possible.
        """
        # First, check if it's even possible to free the required space.
        total_available_space = sum(t.size for t in torrents)
        if total_available_space < space_to_free_bytes:
            return []

        # Sort torrents by size, smallest first
        sorted_torrents = sorted(torrents, key=lambda t: t.size)
        
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
            return # Do nothing if the list is empty

        torrent_hashes = [t.hash for t in torrents]
        self._client.torrents_delete(
            torrent_hashes=torrent_hashes,
            delete_files=delete_files
        )

class Config:
    """
    Manages loading configuration from a JSON file and expanding environment variables.
    """
    def __init__(self, config_path: str):
        self._config = self._load_config(config_path)

    def _load_config(self, config_path: str) -> dict:
        """Loads the config file and expands any environment variables."""
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        
        self._expand_variables(config_data)
        return config_data

    def _expand_variables(self, data: Any):
        """Recursively traverses the config data to find and replace env var placeholders."""
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and value.startswith('$'):
                    data[key] = os.getenv(value[1:])
                else:
                    self._expand_variables(value)
        elif isinstance(data, list):
            for index, item in enumerate(data):
                if isinstance(item, str) and item.startswith('$'):
                    data[index] = os.getenv(item[1:])
                else:
                    self._expand_variables(item)

    def get(self, key_path: str, default: Optional[Any] = None) -> Optional[Any]:
        """
        Retrieves a value from the configuration using dot notation.
        e.g., get('qbittorrent.host')
        """
        keys = key_path.split('.')
        value = self._config
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default