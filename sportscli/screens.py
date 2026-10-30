"""The app's screen statechart: every screen, the keys that leave it, and where they may go.

``App.handle_key`` implements these transitions; tests/test_screens.py explores
every reachable screen state with every key and fails if the app takes a
transition this chart does not allow, or if a declared transition is never
taken. Keep the two in step: change the chart in the same commit as the code.

Every screen except search (where keys type) and help also takes the global
keys: 1 live sports, 2 replays, 3 live TV, / search, , settings, ? help, q quit.
They are listed once in GLOBAL rather than on every screen.

Targets written in angle brackets are history states:

    <back>     the screen that opened this one (help, search, settings, a sport picker)
    <origin>   the list a source screen was opened from (games, replays,
               channels, search or replay_sources)
    <section>  games or replays, whichever section the sport list serves
"""
from __future__ import annotations

HOME = 'home'
EXIT = 'exit'

GLOBAL = {'1': {'leagues'}, '2': {'leagues'}, '3': {'channels'},
          '/': {'search'}, ',': {'settings'}, '?': {'help'}, 'q': {EXIT}}

# screen -> {key: allowed targets}. Keys missing from a screen leave it unchanged.
CHART = {
    'home': {'Enter': {'leagues', 'channels', 'search', 'settings'}, 'Esc': {HOME}},
    'leagues': {'Enter': {'<section>'}, 'Esc': {'<back>', HOME}},
    'games': {'Enter': {'feeds'}, 'Esc': {'leagues'}, 's': {'leagues'}},
    'replays': {'Enter': {'feeds'}, 'Esc': {'leagues'}, 's': {'leagues'}},
    'channels': {'Enter': {'feeds'}, 'Esc': {HOME}},
    'replay_sources': {'Enter': {'feeds'}, 'Esc': {'search'}},
    'feeds': {'Esc': {'<origin>'}, 's': {'leagues'}},
    'settings': {'Esc': {'<back>'}},
    'search': {'Enter': {'feeds', 'replay_sources'}, 'Esc': {'<back>', HOME}, 'Ctrl-X': {EXIT}},
    'help': {'Esc': {'<back>'}, '?': {'<back>'}, 'q': {EXIT}},
}
for _screen, _keys in CHART.items():
    if _screen not in ('search', 'help'):
        for _key, _targets in GLOBAL.items(): _keys.setdefault(_key, _targets)

# Keys that mean the same thing as the named key on every screen except search.
ALIASES = {'Esc': ('Backspace', 'Left'), 'Enter': ('Right',)}

# Transitions the offline exploration cannot take because they need live data:
# a search result opens a game, replay or replay bundle.
NEEDS_LIVE_DATA = {('search', 'Enter')}


def mermaid():
    """The chart as a Mermaid state diagram for docs/screens.md."""
    lines = ['stateDiagram-v2', f'    [*] --> {HOME}']
    for screen, keys in CHART.items():
        for key, targets in keys.items():
            if key in GLOBAL and screen != HOME and keys[key] is GLOBAL[key]: continue
            for target in sorted(targets):
                name = '[*]' if target == EXIT else target.strip('<>') + '_' if target.startswith('<') else target
                lines.append(f'    {screen} --> {name}: {key}')
    lines += ['    note right of back_: the screen that opened this one',
              '    note right of origin_: the list the sources came from',
              '    note right of section_: games or replays']
    return '\n'.join(lines)
