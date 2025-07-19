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