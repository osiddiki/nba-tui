# Navigation

Moving between the sports list, a league's schedule, help and search, and getting back with Esc from anywhere. `tests/test_screens.py` proves every key offline; this proves the same paths on the real screen with live schedules.

## Sub-features

- `nav-schedule` Enter on a sport opens its schedule; Esc returns to the sports list.
- `nav-help` `?` opens help from any screen; Esc returns to the same screen.
- `nav-search` `s`, `/` or Space on the sports list opens search; Esc returns.
- `nav-date` `[` and `]` change the schedule date.

## How to get to it (user POV)

- Start `./sports-cli`; the sports list is the first screen.
- Start `./sports-cli --league nba` to open a schedule directly.

## Driving it with drive.py

Preconditions: baseline.

- **Open a schedule.** `$D 'expect:Choose a sport or league' shot:home key:Enter 'expect:NBA  \|' shot:schedule`. The heading reads `Games` and the line under it starts with `NBA  |`.
- **Back to sports.** Continue with `key:Esc 'expect:Choose a sport or league' shot:back`.
- **Help round trip.** `$D --app-args="--league nba" 'expect:NBA  \|' 'key:?' 'expect:Controls and setup' shot:help key:Esc 'expect:NBA  \|' shot:back`.
- **Search round trip.** `$D 'expect:Choose a sport' key:s 'expect:Search:' type:lakers shot:search key:Esc 'expect:Choose a sport' shot:back`.
- **Date.** `$D --app-args="--league nba" 'expect:NBA  \|' shot:today 'key:]' 'expect:NBA  \|' shot:tomorrow`. The date after `NBA  |` moves forward one day.

## Gotchas

- Inside search, letters type into the query; `q` does not quit there (Ctrl-X does).
- The schedule shows `Loading schedule` with a spinner first; expect the league line, not the game rows.
