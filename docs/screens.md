# Screens

The app's screens and keys form the statechart in `sportscli/screens.py`.
`tests/test_screens.py` explores every reachable screen state with every key
(offline, with sample games, replays and channels) and checks that:

- every move between screens is one the chart allows, and every chart move happens;
- Esc, repeated, always leads back to the sports list;
- help and search always return to the screen they were opened from;
- `q` (Ctrl-X in search) quits from every screen;
- every key shown in a screen's footer does something there.

Change the chart in the same commit as the key handling in `App.handle_key`.

```mermaid
stateDiagram-v2
    [*] --> leagues
    leagues --> next_: Enter
    leagues --> back_: Esc
    leagues --> leagues: Esc
    leagues --> channels: t
    leagues --> search: s
    leagues --> search: /
    leagues --> search: Space
    leagues --> help: ?
    leagues --> search: Ctrl-F
    leagues --> [*]: q
    games --> feeds: Enter
    games --> leagues: Esc
    games --> leagues: s
    games --> channels: t
    games --> replays: R
    games --> search: /
    games --> help: ?
    games --> search: Ctrl-F
    games --> [*]: q
    replays --> feeds: Enter
    replays --> games: Esc
    replays --> games: R
    replays --> leagues: s
    replays --> search: /
    replays --> help: ?
    replays --> search: Ctrl-F
    replays --> [*]: q
    replay_sources --> feeds: Enter
    replay_sources --> search: Esc
    replay_sources --> leagues: s
    replay_sources --> help: ?
    replay_sources --> search: Ctrl-F
    replay_sources --> [*]: q
    channels --> feeds: Enter
    channels --> back_: Esc
    channels --> back_: t
    channels --> leagues: s
    channels --> help: ?
    channels --> search: Ctrl-F
    channels --> [*]: q
    feeds --> origin_: Esc
    feeds --> leagues: s
    feeds --> help: ?
    feeds --> search: Ctrl-F
    feeds --> [*]: q
    search --> feeds: Enter
    search --> replay_sources: Enter
    search --> back_: Esc
    search --> leagues: Esc
    search --> leagues: Tab
    search --> help: ?
    search --> [*]: Ctrl-X
    help --> back_: Esc
    help --> back_: ?
    help --> search: Ctrl-F
    help --> [*]: q
    note right of back_: the screen that opened this one
    note right of origin_: the list the sources came from
    note right of next_: games or replays
```
