# Replays

Recent full-game replays from each league's archives, and the servers listed for one replay.

## Sub-features

- `rep-list` `R` on a schedule lists replays; `R` or Esc returns.
- `rep-servers` Enter on a replay lists its servers on the Broadcasts screen.

## How to get to it (user POV)

- Press `R` on a schedule.

## Driving it with drive.py

Preconditions: baseline; network without a proxy.

- **List.** `$D --app-args="--league nba" 'expect:NBA  \|' key:R 'expect:replays found' shot:replays`.
- **Servers.** Continue with `key:Enter 'expect:Replay servers from' 'expect:choices found' shot:servers`.
- **Back.** `key:Esc 'expect:Replays' key:R 'expect:NBA  \|'`.

## Gotchas

- Replay sites change listings often; report the count shown rather than expecting a particular game.
