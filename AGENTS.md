# Agent and developer setup

This repository is a Python terminal app for discovering and playing sports streams and replays. Use Python 3.9 or newer. The app itself uses the standard library; mpv is the default player. IINA is an optional macOS player and Celluloid is an optional Linux player. The PPV resolver is a separate Node.js 20+ checkout installed by `./setup.sh` into the ignored `resolver/` directory.

Run the local checks from the repository root:

```sh
python3 -m unittest -v
python3 -m py_compile sports_live sports-cli nba.py providers.py relay.py grading.py replays.py smart_search.py update_teams.py ad_mute.py
sh -n setup.sh
```

Run `./sports_live` in a terminal, or `./sports_live --list --league nba` for non-interactive output. Live provider tests depend on current games, upstream availability, and network access; keep deterministic fixtures in the unit tests and report which real-player or live checks were possible.

## Code map

- `sports_live`: executable launcher (`sports-cli` is a compatibility alias); `nba.py`: ESPN schedules, live source adapters, curses screens, asynchronous discovery, player launch and configuration.
- `smart_search.py`: local query parsing, team suggestions, and result ranking. `data/teams.json` is the bundled ESPN team-name index; refresh it with `python3 update_teams.py` when appropriate.
- `providers.py`: bounded public-page discovery and supported embedded player resolution.
- `replays.py`: replay catalog listings, search, and per-replay server discovery.
- `relay.py`: session-only local HLS relay for tokenized, image-wrapped streams.
- `grading.py`: on-demand playlist and segment checks, local grades and ranking.
- `ad_mute.py`: optional mpv muting for complete replay playlists with explicit ad cues.
- `test_nba.py`, `test_search.py`, `test_ad_mute.py`: offline tests for discovery, search, playback, relay, player state and UI behavior.

Preserve the lazy workflow: global search uses a local team index and fetches at most three relevant leagues after a brief typing debounce; look up live sources only when a game is selected and replay servers only after a replay is selected. Keep UI work responsive while directories load, retain the user's selection, and discard stale results when navigating away. Live schedules hide games ESPN marks completed; explicitly offline listings and sources that fail during a session are hidden until refresh. Replay archives intentionally include finished games.

Ad mute is enabled only for a run started with `--ad-mute`, applies only to marked replay playlists in mpv, and must preserve the user's own mute state. The current implementation does not classify live commercials. Any future model and its dependencies must stay out of the repository and default setup, require explicit installation and opt-in, and be validated against labeled broadcast footage.

The first two supported options from each directory receive bounded background playlist and segment checks. Those quick checks do not persist grades or hide a source after a transient failure; explicit tests and playback failures still hide it until refresh.

Provider URLs and playlist tokens can expire. Resolve them at selection time, do not check them into the repository, and do not save them in source-check history. Preserve required HTTP headers and keep the local relay alive while a graphical player is using it. Providers can return unsupported players or change without notice; handle failures in the UI and avoid claiming every listing works.

`README.md` is the user-facing setup and controls guide. Update it when changing keys, player choices, sources, or dependencies. Keep local settings in the existing owner-only config file and avoid committing credentials, cookies, local configuration, or captured stream URLs.
