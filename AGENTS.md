# Agent and developer setup

This repository is a Python terminal app for discovering and playing sports streams and replays. Use Python 3.9 or newer. The app itself uses the standard library; mpv is the default player. IINA is an optional macOS player and Celluloid is an optional Linux player. The PPV resolver is a separate Node.js 20+ checkout installed by `./setup.sh` into the ignored `resolver/` directory.

Run the local checks from the repository root:

```sh
python3 -m unittest -v
python3 -m py_compile nba.py providers.py relay.py grading.py replays.py
sh -n setup.sh
```

Run `./nba.py` in a terminal, or `./nba.py --list --league nba` for non-interactive output. Live provider tests depend on current games, upstream availability, and network access; keep deterministic fixtures in the unit tests and report which real-player or live checks were possible.

## Code map

- `nba.py`: ESPN schedules, live source adapters, curses screens, asynchronous discovery, player launch and configuration.
- `providers.py`: bounded public-page discovery and supported embedded player resolution.
- `replays.py`: replay catalog listings, search, and per-replay server discovery.
- `relay.py`: session-only local HLS relay for tokenized, image-wrapped streams.
- `grading.py`: on-demand playlist and segment checks, local grades and ranking.
- `test_nba.py`: offline tests for discovery, matching, the relay, players and UI state.

Preserve the lazy workflow: load one league and date at a time, look up live sources only when a game is selected, and load replay servers only after a replay is selected. Keep UI work responsive while directories load, retain the user's selection, and discard stale results when navigating away. Live schedules hide games ESPN marks completed; explicitly offline listings and sources that fail during a session are hidden until refresh. Replay archives intentionally include finished games.

Provider URLs and playlist tokens can expire. Resolve them at selection time, do not check them into the repository, and do not save them in source-check history. Preserve required HTTP headers and keep the local relay alive while a graphical player is using it. Providers can return unsupported players or change without notice; handle failures in the UI and avoid claiming every listing works.

`README.md` is the user-facing setup and controls guide. Update it when changing keys, player choices, sources, or dependencies. Keep local settings in the existing owner-only config file and avoid committing credentials, cookies, local configuration, or captured stream URLs.
