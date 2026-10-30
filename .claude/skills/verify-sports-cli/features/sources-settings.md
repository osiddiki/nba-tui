# Sources and playback settings

The Broadcasts screen for a game or channel: its sources with automatic checks, and the toggles that change how playback works.

## Sub-features

- `src-list` Enter on a game lists its sources with side, quality and check status.
- `src-test` `x` tests the selected source.
- `set-backup` Settings (`,`) turns the live backup source off and on.
- `set-breaks` Settings cycles what happens during detected ads: mute only, break screen, other game in a corner.
- `set-cache` Settings cycles the cache: 5, 15, 30 seconds.
- `set-player` Settings switches player when IINA or Celluloid is installed.

## How to get to it (user POV)

- Pick a game on a schedule and press Enter, or a channel on Live TV and press Enter.

## Driving it with drive.py

Preconditions: baseline; a live or upcoming game on today's NBA schedule with sources (sources usually appear near start time). Live TV channels always have sources, so use CNN when no game has any.

- **Open sources.** `$D --app-args="--tv" 'expect:CNN  \(' key:Enter 'expect:choices found' shot:sources`.
- **Settings.** `$D 'expect:Home' key:, 'expect:Backup source for live streams' shot:settings key:Down key:Down key:Down key:Enter 'expect:Backup source off' key:Down key:Enter 'expect:During detected ads: break screen' key:Up key:Up key:Up key:Enter 'expect:Cache: 30 seconds' shot:changed`.
- **Settings reach sources.** Continue with `key:3 'expect:CNN  \(' key:Enter 'expect:backup: off' 'expect:cache: 30s' shot:sources`.
- **Test.** On a sources screen, `key:x 'expect:OK|HTTP|Testing' wait:5 shot:tested`.

## Gotchas

- Settings changes save to the run's own config folder only; the user's settings are untouched.
- `h` (home or away side) exists only for live games; TV and replay sources have no side.
- The Player row reports `IINA not found` when IINA is not installed; that message is the proof for this machine.
