# Sports CLI

Find a game or replay in your terminal, choose a source, and play it in mpv, IINA, or Celluloid. Search suggestions appear as you type; the app loads only the relevant schedules and replay catalogs, then finds streams for the game you select. Its compact browsing flow takes inspiration from [ani-cli](https://github.com/pystardust/ani-cli).

Live schedules cover NBA, WNBA, NFL, NCAA football, men's and women's NCAA basketball, MLB, NHL, and soccer: MLS, Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Liga MX, and UEFA Champions League. Search includes replays from supported archives.

## Install

You need Python 3.9+ with `curses`, Git, and a player. Node.js 20+ and npm are needed for the optional PPV resolver installed by `setup.sh`.

**macOS** — install mpv and Node with Homebrew:

```sh
brew install mpv node
```

For a native graphical player, also install [IINA](https://iina.io/):

```sh
brew install --cask iina
```

**Ubuntu / Debian** — install the dependencies:

```sh
sudo apt install git python3 mpv nodejs npm
```

Check `node --version`; if it is below 20, install a newer version from [Node.js](https://nodejs.org/). For a graphical player, optionally install [Celluloid](https://celluloid-player.github.io/) with `sudo apt install celluloid`. Other Linux distributions can use their own package manager. Windows requires a terminal with Python's curses support, such as WSL.

**Then, on either system:**

```sh
git clone https://github.com/osiddiki/nba-tui.git
cd nba-tui
./setup.sh
./sports-cli
```

The setup script installs a pinned copy of the [PPV HLS resolver](https://github.com/Lunatic16/ppv-hls-proxy) in `resolver/` and, when pip is available, the small [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) search accelerator in `.deps/`. You can run `./sports-cli` without setup; search falls back to the built-in matcher and PPV sources need the resolver. To update an existing checkout later, run `git pull` and then `./sports-cli`.

## First run

1. Select a sport or league on the opening screen, or press `s`, `/`, or `Space` to search across sports. Use `./sports-cli --search` to open directly into search.
2. Try `warriors`, `mavs rockets`, `lakers vs blazers oct 27`, or `tamu vs alabama`. Results are grouped under the team, with live broadcasts, recent replays, and upcoming games. Matching team suggestions follow below. The app checks a relevant team's upcoming schedule and, for specific NBA matchups, searches a few older replay pages in the background.
3. Use the arrow keys and `Enter` to open a game, a home or away broadcast list, or a replay. Home and away choices appear when a directory identifies those sides; open the live game to see all sources, including unlabeled ones. Replay listings for the same game are grouped; choose a provider, then a server. In search, `Ctrl-U` clears the query, `Ctrl-R` refreshes, and `Tab` returns to sports.
4. Select a stream and press `Enter` to play. The stream list shows its provider, broadcast side, listed or measured quality, and availability check. Press `o` to filter by provider, `f` by broadcast side, or `/` to search providers and channels. Press `r` to refresh.
5. On macOS, press `p` to switch between mpv and IINA. On Linux, `p` switches between mpv and Celluloid. The graphical player must be installed first.
6. To browse archives by league, select a league and press `R` in its game list. Press `R` again to return to games. Press `s` in a game, replay, or stream list to choose a different sport.

Press `?` for the in-app controls and `Ctrl-F` to return to global search from another screen. `Esc` goes back. `Ctrl-X` quits from search; `q` quits from the other lists. The schedule date is in Eastern time; game times are displayed in your machine's local timezone. Completed games are omitted from live schedules but may appear as replays.

Search uses a small bundled team index and local fuzzy matching; it does not download or run an AI model. RapidFuzz accelerates typo matching when installed; the standard-library fallback works without it. Network requests start only after you type a team or league and query at most three relevant leagues. The app fetches broadcast listings only for an identified live game and looks up replay servers only after selection. Results depend on what schedules and archives provide.

When using mpv, close its window or press `q` in mpv to return to the picker. IINA and Celluloid open separate windows, leaving the picker usable. **Keep the terminal app open while playing a local relay stream.**

## Controls

| Key | Action |
| --- | --- |
| `↑` / `↓`, `Enter`, `Esc` | Move, select, or go back (`j` / `k` also move outside search) |
| `s` / `/` / `Space` on the opening screen | Open global search |
| `Ctrl-F`, `Tab`, `Ctrl-U`, `Ctrl-R`, `Ctrl-X` | Global search, browse sports, clear, refresh, or quit search |
| `s` (or `S`), `[`, `]`, `/`, `l` | Choose sport, change schedule date, search, or filter for the Lakers |
| `R` | Switch between the live schedule and replays |
| `f`, `o`, `r` | Broadcast side, provider, or refresh |
| `t`, `g`, `i` | Test a source, rank sources by checks, or inspect its media URL |
| `p`, `c`, `v` | Player, cache size, or mpv terminal video |
| `u`, `a`, `d` | Paste a media URL, configure an add-on, or select a PPV resolver directory |
| `?`, `q` | Help or quit |

Keys are case-sensitive except for `s` / `S`. `./sports-cli --list --league wnba` prints a plain-text schedule and the first game's streams. `./sports-cli --league ncaaf` opens college football directly; `./sports-cli --league nba --date 2026-10-31` selects a schedule date. Run `./sports-cli --help` for all league codes.

## Sources and options

### Live directories

| Source | Coverage and behavior |
| --- | --- |
| StreamFree | Multiple sports; sources marked not live are omitted and fresh playlist URLs are resolved on selection. |
| PPV | Multiple sports and broadcast labels; uses the local PPV resolver. |
| NTV | Multiple sports and event-specific servers; some channels require the app's local relay. |
| NBA Bite, NBA Monster | Additional NBA directories; individual embedded players are resolved when selected. |
| Sports add-on | Optional compatible Stremio manifest configured with `a`; results depend on the add-on. |

A dash for broadcast side or quality means the directory did not provide it. A `~` before quality, such as `~1080p`, means the directory reported that value; a value without `~` came from a source check. Labels can be wrong and directories can list the same stream more than once. Sources that do not report live status may still be unavailable.

While choices load, the app checks up to two supported sources per directory in the background. `OK` means it reached a playlist and one media segment; `Checking`, `Unverified`, or a status such as `HTTP 403` describes other outcomes. A single failed check may be temporary, so the option remains available. PPV sources are resolved when selected instead. Results appear without waiting for these checks.

If resolution, a test, or mpv playback fails, the source is hidden for the current list. Press `r` to fetch the list again. A missing local dependency is reported without hiding the source. Some players use short-lived tokens or wrapped video segments; the session-only relay on `127.0.0.1` refreshes tokens and supplies normal HLS to the player. Its URLs stop working when the app exits.

### Replays

The replay view uses Basketball Replays and Basketball Video for basketball, NFL Video for football, FullMatchShows for soccer, and WatchReplay for MLB and NHL. It fetches listings only for the selected league and looks up servers only after you select a replay. Soccer replay listings can include multiple competitions. Search depends on each directory; when a site blocks search, the app filters its recent listings instead. Coverage and playable server support vary, and a full match may be listed as separate parts. More replay indexes are listed by [FMHY](https://fmhy.net/video#sports-replays).

### Source checks and ranking

Press `t` to resolve the selected source and read part of one segment from your connection. The app shows video height when it can determine it from the playlist or an optional `ffprobe` installation. This is a point-in-time check, not a sustained playback or buffering test.

The last 20 manual `t` checks are stored per provider, server, or channel; background checks do not affect grades. After at least three tests, A, B, C, and D correspond to success rates of at least 90%, 70%, 50%, and below 50%; fewer tests show `?`. The adjacent count shows the number of successful and total checks. Press `g` to rank tested sources by these results.

### Ad mute

To enable ad mute for one run, start with `./sports-cli --ad-mute`. Normal launches leave it off. It currently works only in mpv for complete replay HLS playlists with explicit `EXT-X-CUE-OUT` / `EXT-X-CUE-IN` ad markers. The app mutes at marked breaks and restores sound afterward if it was responsible for muting. It does not download a model, send frames to a service, or run AI.

Most live streams tested do not include these markers, and this setting does not yet detect their commercials. A replay without markers, IINA, and Celluloid also play without automatic muting. Manual mute controls remain available in the player.

For an **experimental local AI detector for NBA broadcasts**, install it separately, then opt in for each run:

```sh
./sports-cli --install-ad-model   # one-time optional download
./sports-cli --ai-ad-observe      # show predictions, keep audio unchanged
./sports-cli --ai-ad-mute         # enable for this run
```

The install downloads the original 150 MB model and conversion packages, verifies its checksum, and quantizes it locally. Allow about 1.5 GB of temporary disk space during installation. It removes the source model and conversion environment afterward, leaving the 22 MB model and an isolated runtime in `${XDG_DATA_HOME:-~/.local/share}/sports-live/ad-mute/`. On Linux and Apple Silicon, the finished installation takes roughly 200 MB, depending on Python and platform. Intel Macs use a larger TensorFlow runtime. Setup needs Python 3.9–3.12 with `venv` and pip; on Ubuntu/Debian, install `python3-venv` if needed. If the app runs on a newer Python, it searches for a compatible version. The normal launcher never installs the model automatically, and the Git checkout contains no model weights.

This detector samples video frames locally in mpv and sends nothing to an AI service. It was trained for NBA video and is disabled for other leagues. Try `--ai-ad-observe` first: it shows predictions without muting. In tests with real NBA broadcasts and commercials, the detector also classified some studio and bench coverage as ads. Automatic muting is experimental and may silence game coverage; use mpv's `m` key to override it. The model is a quantized version of the MIT-licensed [NBA-redzone-ML model](https://huggingface.co/plt3/NBA-redzone-ML), and the project describes its original training and evaluation [here](https://github.com/plt3/NBA-redzone-ML).

For developers comparing detectors against labeled local recordings, see [ad detector testing](docs/ad-detector-testing.md).

### Add-ons and resolver

Press `a` to configure a compatible sports Stremio add-on. For example, [Sports Streams](https://sports.highfly.to/configure) offers a manifest after its one-time setup. The app queries the selected sport and generic sports catalogs for direct URLs. Pass a manifest for one run with `./sports-cli --addon 'https://…/manifest.json'`.

The PPV helper runs only when needed on `127.0.0.1:38765` and is closed on exit if the app started it. To use a different checkout, press `d` or pass `--resolver-dir /path/to/ppv-hls-proxy`; run `npm install` in that checkout first. Settings are saved with owner-only permissions in `${XDG_CONFIG_HOME:-~/.config}/nba-tui/config.json`. Source-check history does not store media URLs or tokens. The app does not decrypt DRM-protected streams.

Streams and archives change frequently. Try another source or increase the cache with `c` if playback stalls. For development and agent setup, see [AGENTS.md](AGENTS.md).
