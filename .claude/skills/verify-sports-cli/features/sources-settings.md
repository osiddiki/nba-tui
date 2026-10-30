# Sources and playback settings

The Broadcasts screen for a game or channel: its sources with automatic checks, and the toggles that change how playback works.

## Sub-features

- `src-list` Enter on a game lists its sources with side, quality and check status.
- `src-test` `t` tests the selected source.
- `src-backup` `b` turns the live backup source off and on.
- `src-breaks` `m` cycles what happens during detected ads: mute only, break screen, other game in a corner.
- `src-cache` `c` cycles the cache: 5, 15, 30 seconds.
- `src-player` `p` switches player when IINA or Celluloid is installed.

## How to get to it (user POV)

- Pick a game on a schedule and press Enter, or a channel on Live TV and press Enter.

## Driving it with drive.py

Preconditions: baseline; a live or upcoming game on today's NBA schedule with sources (sources usually appear near start time). Live TV channels always have sources, so use CNN when no game has any.

- **Open sources.** `$D --app-args="--tv" 'expect:CNN  \(' key:Enter 'expect:choices found' shot:sources`.
- **Backup.** Continue with `key:b 'expect:Backup source off' 'expect:backup: off' shot:backup-off key:b 'expect:adds a backup source' shot:backup-on`.
- **Ad breaks.** `key:m 'expect:During detected ads: break screen' 'expect:breaks: break screen' shot:breaks`. The context line shows `breaks:` only when started with `--ai-ad-mute`; without it the status line says `Applies when run with --ai-ad-mute.`
- **Cache.** `key:c 'expect:cache: 30s' shot:cache`.
- **Test.** `key:t 'expect:OK|HTTP|Testing' wait:5 shot:tested`.

## Gotchas

- Settings changes save to the run's own config folder only; the user's settings are untouched.
- `f` (side) exists only for live games; TV and replay sources have no side.
- `p` reports `IINA not found` when IINA is not installed; that message is the proof for this machine.
