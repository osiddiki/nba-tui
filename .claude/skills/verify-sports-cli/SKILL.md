---
name: verify-sports-cli
description: Drive the Sports CLI terminal app (./sports-cli, a curses TUI) in a pseudo-terminal like a user and save screen evidence. Use to prove a change to screens, keys, sources, replays, live TV, settings toggles or mpv playback works in the real app, not just in unit tests.
---

# Verify Sports CLI

The app is a curses TUI started with `./sports-cli` from the repo root. It has no server; each drive starts its own copy in a pseudo-terminal, presses keys, and saves the screen as text. `tests/test_screens.py` already proves every key against the screen statechart offline; this skill proves the same flows with real network data and real mpv.

## Launch

Nothing to build. Each run of the driver starts a fresh app and ends it:

```sh
.claude/skills/verify-sports-cli/scripts/drive.py [--app-args="--tv"] STEP...
```

The first run creates `~/.cache/sports-cli-verify/venv` with the `pyte` terminal emulator (the app itself stays standard-library only). The app is ready when the screen matches its first screen: `expect:Home` for a plain start, `expect:Live TV` with `--app-args="--tv"`, `expect:Games` with `--app-args="--league nba"`.

Steps: `key:NAME` (Enter, Esc, Tab, Space, Backspace, Up, Down, Ctrl-F, Ctrl-X or one character), `type:TEXT`, `wait:SECONDS`, `expect:REGEX` (waits up to 20 s; the run fails if it never matches), `shot:LABEL`.

Non-interactive features need no driver: `python3 sports-cli --list --league nba` and `python3 sports-cli --list --tv`.

## Doctor

```sh
.claude/skills/verify-sports-cli/scripts/doctor.sh
```

Read-only. It reports the commit, Python, whether `./sports-cli` starts, mpv and ffmpeg, whether a network proxy is set, and other running app copies. **A proxy line means you are inside a sandbox** (`HTTPS_PROXY=http://127.0.0.1:…`): stream hosts can be refused and TLS can fail at random there, so failures of network features in that shell prove nothing about the app. Run network and playback features from the user's terminal (the Terminal panel tool) or report them as not provable here.

## Drive

Real handles from this app, all from the footer and headings it renders:

Every screen takes `1` live sports, `2` replays, `3` live TV, `/` search, `,` settings, `?` help and `q` quit; Esc goes back one level and repeated reaches Home.

| Screen | Heading | Ready when | Keys |
|---|---|---|---|
| Home | `Home` | `Live sports` | Enter on a row, or its key |
| Sport list | `Live sports: choose a sport` or `Replays: choose a sport` | that text | Enter, Esc |
| Schedule | `Games` | `NBA  \|` (league name then a bar) | Enter sources, `s` sport, `[` `]` date, `f` filter, `r` |
| Sources | `Sources` | `choices found` | Enter play, `x` test, `i` inspect, `u` paste URL, `a` side (live), `o` source, `f` filter, `g` rank, Esc |
| Replays | `Replays` | `replays found` | Enter sources, `s` sport, `f` search titles, Esc |
| Live TV | `Live TV` | `CNN  \(\d+ sources?\)` | Enter sources, `f` filter (prompt), Esc |
| Search | `Search` | `Search:` | type text; `TV CHANNELS`, `LIVE`, `REPLAYS` groups; Enter, Esc |
| Settings | `Settings` | `Backup source for live streams` | Up/Down, Enter changes the row, Esc |
| Help | `Help` | `Controls and setup` in the status line | Esc |

Move with `key:Down` / `key:Up` (sent as `j` / `k`). Prompts (`f` filters, `u`, and the add-on and resolver rows in Settings) leave curses for a plain `input()` line: send `type:TEXT` then `key:Enter`.

Each run uses its own `XDG_CONFIG_HOME`, so changes in Settings never touch the user's saved settings, and its own `MPV_HOME` whose `mpv.conf` plays with `vo=null`, `ao=null` and `length=N` (`--mpv-seconds`, default 8). Pressing Enter on a source therefore runs the real resolve-and-play path and returns to the app with `Returned from mpv.` without opening a window.

## Evidence

Screens go to `~/.cache/sports-cli-verify/runs/<time>/NN-label.txt` (or `--out DIR`), outside the repo; the driver prints each path and the folder at the end. A proof needs:

- the real user path: keys on screens, not calling `App` methods or setting attributes;
- a shot before and after the action, plus the status line (`expect` the message the action prints, such as `Backup source off` or `Returned from mpv.`);
- side effects observed, not assumed: for playback, `Returned from mpv.` after the play key; for Settings, the context line on the Sources screen (`backup: off`, `cache: 30s`).

Live data changes all day: games appear near start time, sources come and go. Record what the screen showed rather than claiming a listing works everywhere.

## Cleanup

The driver ends the copy it started (q, then SIGTERM to that process id only) and deletes its scratch settings and mpv folders. It never kills other `sports-cli` processes: the user may be running one. Evidence folders stay until you delete them; delete only folders you created.

## Helpers

- `scripts/drive.py`: the pseudo-terminal driver above. `scripts/drive.py --help` prints the step syntax.
- `scripts/doctor.sh`: the readiness check above.

Feature map: [features/README.md](features/README.md).
