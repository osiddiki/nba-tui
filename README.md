# NBA Live: terminal picker

Browse NBA games by date and team, select a home or away broadcast, and launch it in `mpv`. The program retrieves one day's schedule first, then looks up streams only when you select a game. Feed availability and quality depend on the provider and your connection.

## Setup

Install Python 3.9+ with `curses`, Node.js 20+ with npm, Git, and `mpv`. On macOS, `brew install mpv node`; on Ubuntu/Debian, `sudo apt install mpv nodejs npm git python3` (the Node package must be version 20 or newer). Other systems can use their package manager. Windows needs a terminal with Python's curses support, such as WSL.

Clone the repository and run:

```sh
git clone https://github.com/osiddiki/nba-tui.git
cd nba-tui
./setup.sh
./nba.py
```

`setup.sh` installs the [PPV HLS resolver](https://github.com/Lunatic16/ppv-hls-proxy) into `resolver/`, pinned to the revision tested here, and installs its dependencies. If the checkout is already present, it keeps it. The app starts that helper automatically on `127.0.0.1:38765`, resolves the selected feed, and closes the helper when the app exits. If that port is occupied by an existing helper the app uses it and leaves it running. The resolver relays video locally, so keep the app open during playback.

## Controls

- `↑` / `↓` or `j` / `k`: move; `Enter`: select a game or play a feed; `Esc`: return to games; `q`: quit.
- `[` / `]`: previous / next NBA schedule date (Eastern time); `/`: search for a team; clear the search to see all games.
- `r`: refresh the current schedule or stream list. Stream lists often appear close to tipoff.
- `f`: cycle all, home, away, unknown, and (when applicable) Lakers feeds. The labels come from the provider; `?` means the broadcast is not identified.
- `c`: cycle cache between 5, 15, and 30 seconds; `v`: switch between normal window and terminal video (`mpv --vo=tct`); `u`: play a pasted direct media URL.
- `i`: resolve the selected source and display its current media URL and required headers. `a`: add/remove a sports Stremio add-on manifest; `s`: select a different local resolver checkout.

Close mpv with `q` to return to the picker. Use `./nba.py --list` for a plain-text schedule and stream list, or `./nba.py --date 2026-10-28` to open a particular NBA schedule date. The score and team schedule are sourced from ESPN; displayed game times use your machine's local timezone.

## Sources and options

StreamFree sources are resolved to fresh HLS URLs when selected. Its player does not identify commentary sides, so those choices show `?`. PPV's index supplies home/away labels and uses the local PPV resolver. Each playlist is checked before mpv starts.

NBA Bite is a game-specific directory of multiple providers. NBA Monster is another source listed by [FMHY](https://fmhy.net/video#live-tv-sports). Their entries appear as `TRY`: the program follows supported embedded players and tries to extract a playable URL when you select one. Unsupported or unavailable players report an error in the app, rather than opening a browser. Some providers return wrapped video segments and short-lived playlist tokens; for those the app runs a session-only relay on `127.0.0.1` that refreshes tokens and gives mpv a normal HLS stream. Keep the app open during playback. The displayed local URL is valid only while the app is running.

Directory names, quality, language and broadcast labels come from their listings and may be inaccurate. Where a channel matches a single home or away broadcaster on the schedule, the app labels the corresponding side; otherwise it shows `?`. Streams may be unavailable before tipoff or during a game, and one listing may duplicate another.

For more direct stream options, configure a compatible sports add-on with `a`. One option is [Sports Streams](https://sports.highfly.to/configure): complete its one-time verification on its page and copy its manifest URL into the app. The app queries compatible basketball/sports catalogs and adds direct media URLs to the picker. Add-on streams, sides, and availability depend on that service; the unconfigured public manifest does not return playable streams. You can also pass a manifest for one run with `./nba.py --addon 'https://…/manifest.json'`. Add-on URLs may contain access tokens, so the config file is created with owner-only permissions at `${XDG_CONFIG_HOME:-~/.config}/nba-tui/config.json`.

For a different resolver checkout, press `s` and enter its folder, or use `./nba.py --resolver-dir /path/to/ppv-hls-proxy`. Run `npm install` inside it first. To play direct links you already have, press `u` in a game's stream view. The app does not decrypt DRM-protected streams.

No provider can guarantee uninterrupted, high-quality playback for every game. Try another feed or increase the cache if a stream stutters. If a source fails, refresh the game or use another source; providers and their APIs can change without notice.
