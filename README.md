# qbit-checker

This is a simple project to enable me check my qbittorent instance by running a command and receiving output.

## autobrr
Initial plan was to hook this `autobrr` as an external script so that when torrents are ingested to be added into qbittorent, autobrr will run a script to check if there's enough space, and try to clear up space given some conditions. If not enough space can be cleared, the script will return an exit code that will prohibit `autobrr` from adding a new torrent.

For more info on autobrr's external scripts: [https://autobrr.com/filters/external](https://autobrr.com/filters/external)

## autobrr external script example
See `check_and_make_disk_space.py` in root dir