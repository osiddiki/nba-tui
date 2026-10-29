#!/usr/bin/env python3
"""Refresh the small bundled ESPN team-name index used by global search."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import pathlib
import sys

import nba


def fetch(league):
    path = nba.LEAGUES[league][1]
    data = nba.request(f'{nba.ESPN}/{path}/teams?limit=1000', timeout=20)
    teams = [row.get('team', {}) for sport in data.get('sports', [])
             for group in sport.get('leagues', []) for row in group.get('teams', [])]
    result = []
    for team in teams:
        if not team.get('id') or not team.get('displayName'):
            continue
        result.append([str(team['id']), *(str(team.get(key) or '') for key in
                       ('displayName', 'location', 'name', 'shortDisplayName', 'abbreviation'))])
    if not result:
        raise ValueError(f'No teams returned for {league}')
    return sorted(result, key=lambda item: (item[1].casefold(), item[0]))


def main():
    leagues = list(nba.LEAGUES)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        try:
            records = dict(zip(leagues, pool.map(fetch, leagues)))
        except Exception as exc:
            print(f'Team index not updated: {type(exc).__name__}: {exc}', file=sys.stderr)
            return 1
    target = pathlib.Path(__file__).resolve().parent / 'data' / 'teams.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'updated': dt.date.today().isoformat(), 'leagues': records},
                                 ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf8')
    print(f'Updated {sum(map(len, records.values()))} teams in {target}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
