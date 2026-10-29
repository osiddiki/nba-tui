# Sports Live

Find a game or replay in your terminal, choose a source, and play it in mpv, IINA, or Celluloid. The app loads only the league and game you select, and shows source results as they arrive. Its compact browsing flow takes inspiration from [ani-cli](https://github.com/pystardust/ani-cli).

Live schedules cover NBA, WNBA, NFL, NCAA football, men's and women's NCAA basketball, MLB, NHL, and soccer: MLS, Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Liga MX, and UEFA Champions League. Replays have a separate archive view.

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

The setup script installs a pinned copy of the [PPV HLS resolver](https://github.com/Lunatic16/ppv-hls-proxy) in `resolver/`. You can run `./sports-cli` without setup if you do not need PPV sources. To update an existing checkout later, run `git pull` and then `./sports-cli`.

## First run

1. Choose a sport or league on the opening screen. Press `s` at any game, replay, or source list to change it. Use `[` and `]` to change the schedule date, or `/` to search for a team. In the NBA list, `l` quickly filters for the Lakers.
2. Select a game with the arrow keys or `j` / `k`, then press `Enter`. Sources appear as each directory responds. ESPN's completed games and sources explicitly marked offline are hidden.
3. Select a source and press `Enter` to play. Press `o` to filter by provider, `f` to filter by broadcast side, or `/` to search sources and channels. Press `r` to refresh.
4. On macOS, press `p` to switch between mpv and IINA. On Linux, `p` switches between mpv and Celluloid. The graphical player must be installed first.
5. For past games, return to the game list and press `R`. Choose a league with `s`, search with `/`, choose a replay, then choose a server. Press `R` to return to live games.

Press `?` at any time for the in-app controls. `Esc` goes back and `q` quits. The schedule date is in Eastern time; game times are displayed in your machine's local timezone.

When using mpv, close its window or press `q` in mpv to return to the picker. IINA and Celluloid open separate windows, leaving the picker usable. **Keep the terminal app open while playing a local relay stream.**

## Controls

| Key | Action |
| --- | --- |
| `↑` / `↓`, `j` / `k`, `Enter`, `Esc` | Move, select, or go back |
| `s` (or `S`), `[`, `]`, `/`, `l` | Sport or league, date, search, or Lakers shortcut |
| `R` | Switch between the live schedule and replays |
| `f`, `o`, `r` | Broadcast side, provider, or refresh |
| `t`, `g`, `i` | Test a source, rank sources by checks, or inspect its media URL |
| `p`, `c`, `v` | Player, cache size, or mpv terminal video |
| `u`, `a`, `d` | Paste a media URL, configure an add-on, or select a PPV resolver directory |
| `?`, `q` | Help or quit |

Keys are case-sensitive except for `s` / `S`. `./sports-cli --list --league wnba` prints a plain-text schedule and the first game's streams. `./sports-cli --league ncaaf` opens college football directly; `./sports-cli --date 2026-10-31` selects a schedule date. Run `./sports-cli --help` for all league codes.

## Sources and options

### Live directories

| Source | Coverage and behavior |
| --- | --- |
| StreamFree | Multiple sports; sources marked not live are omitted and fresh playlist URLs are resolved on selection. |
| PPV | Multiple sports and broadcast labels; uses the local PPV resolver. |
| NTV | Multiple sports and event-specific servers; some channels require the app's local relay. |
| NBA Bite, NBA Monster | Additional NBA directories; individual embedded players are resolved when selected. |
| Sports add-on | Optional compatible Stremio manifest configured with `a`; results depend on the add-on. |

`PLAY` indicates a supported direct or resolver-backed source. `TRY` is a directory listing whose player must still be resolved. `?` for broadcast side means the directory did not identify home or away. Labels can be wrong and directories can list the same stream more than once. Sources that do not report live status may still be unavailable.

While choices load, the app checks up to two supported sources per directory in the background. `[OK]` means it reached a playlist and one media segment; `[HTTP 403]` or `[?]` means the quick check could not verify it. A single failed check may be temporary, so the option remains available. PPV sources are resolved when selected instead. Results appear without waiting for these checks.

If resolution, a test, or mpv playback fails, the source is hidden for the current list. Press `r` to fetch the list again. A missing local dependency is reported without hiding the source. Some players use short-lived tokens or wrapped video segments; the session-only relay on `127.0.0.1` refreshes tokens and supplies normal HLS to the player. Its URLs stop working when the app exits.

### Replays

The replay view uses Basketball Replays and Basketball Video for basketball, NFL Video for football, FullMatchShows for soccer, and WatchReplay for MLB and NHL. It fetches listings only for the selected league and looks up servers only after you select a replay. Soccer replay listings can include multiple competitions. Search depends on each directory; when a site blocks search, the app filters its recent listings instead. Coverage and playable server support vary, and a full match may be listed as separate parts. More replay indexes are listed by [FMHY](https://fmhy.net/video#sports-replays).

### Source checks and ranking

Press `t` to resolve the selected source and read part of one segment from your connection. The app shows video height when it can determine it from the playlist or an optional `ffprobe` installation. This is a point-in-time check, not a sustained playback or buffering test.

The last 20 manual `t` checks are stored per provider, server, or channel; background checks do not affect grades. After at least three tests, A, B, C, and D correspond to success rates of at least 90%, 70%, 50%, and below 50%; fewer tests show `?`. The adjacent count shows the number of successful and total checks. Press `g` to rank tested sources by these results.

### Add-ons and resolver

Press `a` to configure a compatible sports Stremio add-on. For example, [Sports Streams](https://sports.highfly.to/configure) offers a manifest after its one-time setup. The app queries the selected sport and generic sports catalogs for direct URLs. Pass a manifest for one run with `./sports-cli --addon 'https://…/manifest.json'`.

The PPV helper runs only when needed on `127.0.0.1:38765` and is closed on exit if the app started it. To use a different checkout, press `d` or pass `--resolver-dir /path/to/ppv-hls-proxy`; run `npm install` in that checkout first. Settings are saved with owner-only permissions in `${XDG_CONFIG_HOME:-~/.config}/nba-tui/config.json`. Source-check history does not store media URLs or tokens. The app does not decrypt DRM-protected streams.

Streams and archives change frequently. Try another source or increase the cache with `c` if playback stalls. For development and agent setup, see [AGENTS.md](AGENTS.md).
