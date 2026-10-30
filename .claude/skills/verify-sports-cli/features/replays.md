# Replays

Recent full-game replays from each league's archives, and the servers listed for one replay.

## Sub-features

- `rep-list` `2` (or Replays on Home), then a sport, lists replays; Esc returns to the sport list.
- `rep-servers` Enter on a replay lists its servers on the Broadcasts screen.

## How to get to it (user POV)

- Press `2` anywhere, or choose Replays on Home.

## Driving it with drive.py

Preconditions: baseline; network without a proxy.

- **List.** `$D 'expect:Home' key:2 'expect:Replays: choose a sport' key:Enter 'expect:replays found' shot:replays`.
- **Servers.** Continue with `key:Enter 'expect:Replay servers from' 'expect:choices found' shot:servers`.
- **Back.** `key:Esc 'expect:Replays' key:Esc 'expect:choose a sport'`.

## Gotchas

- Replay sites change listings often; report the count shown rather than expecting a particular game.
