"""Developer-only: record chosen live games at low resolution for ad-detector training.

    python3 -m sportscli.tools.record_games ~/ad-data/recordings nba:Knicks nhl:Jets ncaaf:Baylor

Each argument is ``league:team`` (any part of either team's name). The tool waits
for each of today's matching games to start, resolves sources the way the app
does, and records with ffmpeg at 384x216, 10 fps, about 200 MB per hour, until
ESPN marks the game finished. If a source fails it moves to the next one and
starts a new part file. Recordings stay local and must never be committed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import signal
import subprocess
import sys
import threading
import time

from sportscli import app

ENCODE = ['-vf', 'scale=-2:216,fps=10', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30',
          '-c:a', 'aac', '-b:a', '48k', '-ac', '1', '-f', 'mpegts']
HLS = ['-allowed_extensions', 'ALL', '-allowed_segment_extensions', 'ALL', '-extension_picky', '0',
       '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '10']
MAX_HOURS = 4.5


def log(*parts):
    print(f'{dt.datetime.now():%H:%M:%S}', *parts, flush=True)


def find_game(games, team):
    """The first game whose home or away name contains ``team``, ignoring case."""
    needle = team.casefold()
    return next((game for game in games if needle in game.home.casefold() or needle in game.away.casefold()), None)


def state(league, game_id):
    try: return next((game.state for game in app.get_games(league=league) if game.id == game_id), 'unknown')
    except (OSError, ValueError): return 'live'  # a schedule hiccup is not the final whistle


def command(url, headers, output):
    header_text = ''.join(f'{name}: {value}\r\n' for name, value in headers.items() if name != 'User-Agent')
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-user_agent', headers.get('User-Agent', app.UA)]
    if header_text: cmd += ['-headers', header_text]
    return cmd + [*HLS, '-i', url, *ENCODE, str(output)]


def sources(player, game):
    feeds, _ = app.fetch_feeds(game, dict(player.config))
    # PPV needs the local resolver, so try it only after direct sources.
    for feed in sorted((item for item in feeds if item.kind != 'web'), key=lambda item: item.kind == 'ppv'):
        try: yield feed, player.resolve_feed(feed)
        except Exception as exc:  # noqa: BLE001 - providers fail in many ways; try the next one
            log(game.title, 'source failed:', feed.source, type(exc).__name__)


def record(player, league, game, folder, stop):
    slug = re.sub(r'[^a-z0-9]+', '-', f'{dt.date.today()}-{league}-{game.away_nickname}-at-{game.home_nickname}'.lower())
    start = game.start.timestamp()
    while not stop.is_set() and time.time() < start - 120:
        stop.wait(min(60, start - 120 - time.time()))
    deadline = time.time() + MAX_HOURS * 3600; part = 0; failures = 0
    while not stop.is_set() and time.time() < deadline:
        current = state(league, game.id)
        if current not in ('live', 'upcoming'): log(game.title, 'finished'); return
        recorded = False
        for feed, (url, headers) in sources(player, game):
            part += 1
            output = folder / f'{slug}-part{part:02d}.ts'
            log(game.title, 'recording', feed.source, '->', output.name)
            process = subprocess.Popen(command(url, headers, output), stdin=subprocess.DEVNULL)
            started = time.time()
            while process.poll() is None and not stop.is_set():
                if stop.wait(60): break
                if state(league, game.id) not in ('live', 'upcoming') or time.time() > deadline:
                    stop_process(process); log(game.title, 'finished'); return
            stop_process(process)
            ran = time.time() - started
            log(game.title, f'source ended after {ran / 60:.1f} min')
            if ran > 120: recorded = True; break
            if output.exists() and output.stat().st_size < 100_000: output.unlink()
        failures = 0 if recorded else failures + 1
        # No working source yet, usually before tip-off; try again shortly.
        stop.wait(30 if recorded else min(300, 60 * failures))


def stop_process(process):
    if process.poll() is not None: return
    process.terminate()
    try: process.wait(timeout=10)
    except subprocess.TimeoutExpired: process.kill(); process.wait()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folder', type=pathlib.Path)
    parser.add_argument('games', nargs='+', help='league:team, for example nba:Knicks')
    args = parser.parse_args(argv)
    folder = args.folder.expanduser(); folder.mkdir(parents=True, exist_ok=True)
    player = app.App(None, app.load_config())
    stop = threading.Event(); threads = []
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    for choice in args.games:
        league, _, team = choice.partition(':')
        if league not in app.LEAGUES or not team: parser.error(f'Use league:team, not {choice!r}')
        game = find_game(app.get_games(league=league), team)
        if not game: log('No game today for', choice); continue
        log('Queued', league, game.title, game.start.astimezone().strftime('%H:%M'))
        thread = threading.Thread(target=record, args=(player, league, game, folder, stop), daemon=True)
        thread.start(); threads.append(thread)
    try:
        while any(thread.is_alive() for thread in threads): time.sleep(5)
    except KeyboardInterrupt:
        stop.set()
        for thread in threads: thread.join(timeout=20)
    finally:
        player.close()  # stops the relay and any PPV helper this process started
    return 0


if __name__ == '__main__':
    sys.exit(main())
