"""The app's screen statechart: every screen, the keys that leave it, and where they may go.

``App.handle_key`` implements these transitions; tests/test_screens.py explores
every reachable screen state with every key and fails if the app takes a
transition this chart does not allow, or if a declared transition is never
taken. Keep the two in step: change the chart in the same commit as the code.

Targets written in angle brackets are history states, decided by where the
user came from:

    <back>     the screen that opened this one (help, search, leagues, channels)
    <origin>   the list a source screen was opened from (games, replays,
               channels, search or replay_sources)
    <next>     games or replays, whichever list the sport picker was opened for
"""
from __future__ import annotations

HOME = 'leagues'
EXIT = 'exit'

# screen -> {key: allowed targets}. Keys missing from a screen leave it unchanged.
CHART = {
    'leagues': {
        'Enter': {'<next>'},
        'Esc': {HOME, '<back>'},
        't': {'channels'},
        's': {'search'}, '/': {'search'}, 'Space': {'search'},
        '?': {'help'}, 'Ctrl-F': {'search'}, 'q': {EXIT},
    },
    'games': {
        'Enter': {'feeds'},
        'Esc': {HOME},
        's': {HOME},
        't': {'channels'},
        'R': {'replays'},
        '/': {'search'},
        '?': {'help'}, 'Ctrl-F': {'search'}, 'q': {EXIT},
    },
    'replays': {
        'Enter': {'feeds'},
        'Esc': {'games'}, 'R': {'games'},
        's': {HOME},
        '/': {'search'},
        '?': {'help'}, 'Ctrl-F': {'search'}, 'q': {EXIT},
    },
    'replay_sources': {
        'Enter': {'feeds'},
        'Esc': {'search'},
        's': {HOME},
        '?': {'help'}, 'Ctrl-F': {'search'}, 'q': {EXIT},
    },
    'channels': {
        'Enter': {'feeds'},
        'Esc': {'<back>'}, 't': {'<back>'},
        's': {HOME},
        '?': {'help'}, 'Ctrl-F': {'search'}, 'q': {EXIT},
    },
    'feeds': {
        'Esc': {'<origin>'},
        's': {HOME},
        '?': {'help'}, 'Ctrl-F': {'search'}, 'q': {EXIT},
    },
    'search': {
        'Enter': {'feeds', 'replay_sources'},
        'Esc': {'<back>', HOME},
        'Tab': {HOME},
        '?': {'help'}, 'Ctrl-X': {EXIT},
    },
    'help': {
        'Esc': {'<back>'}, '?': {'<back>'},
        'Ctrl-F': {'search'}, 'q': {EXIT},
    },
}

# Keys that mean the same thing as the named key on every screen except search,
# where letters are typed into the query.
ALIASES = {'Esc': ('Backspace', 'h'), 't': ('T',), 's': ('S',)}

# Transitions the offline exploration cannot take because they need live data:
# a search result opens a game, replay or replay bundle.
NEEDS_LIVE_DATA = {('search', 'Enter')}


def mermaid():
    """The chart as a Mermaid state diagram for docs/screens.md."""
    lines = ['stateDiagram-v2', f'    [*] --> {HOME}']
    for screen, keys in CHART.items():
        for key, targets in keys.items():
            for target in sorted(targets):
                name = '[*]' if target == EXIT else target.strip('<>') + '_' if target.startswith('<') else target
                lines.append(f'    {screen} --> {name}: {key}')
    lines += ['    note right of back_: the screen that opened this one',
              '    note right of origin_: the list the sources came from',
              '    note right of next_: games or replays']
    return '\n'.join(lines)
