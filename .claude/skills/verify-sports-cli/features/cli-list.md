# Plain listings

Non-interactive output for scripts: today's games with one game's sources, and the live TV channel list.

## Sub-features

- `list-games` `./sports-cli --list --league nba` prints games and sources.
- `list-tv` `./sports-cli --list --tv` prints the main channels and their sources.

## How to get to it (user POV)

- Run the commands in a terminal.

## Driving it with a shell

Preconditions: baseline; network without a proxy.

- **Games.** `python3 sports-cli --list --league nba > out.txt; echo $?`. Exit code 0; numbered games, then `Streams for:` with sources or `No feeds found yet`.
- **TV.** `python3 sports-cli --list --tv > out.txt; echo $?`. Exit code 0; lines such as `CNN: iptv-org 720p, DaddyLive channel 345`, then `2202 channels in all` (the number varies).

## Gotchas

- Save stdout and the exit code as the proof; source errors print to stderr.
