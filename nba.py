#!/usr/bin/env python3
"""NBA terminal stream picker. Python standard library only."""
from __future__ import annotations
import argparse
import curses
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field

UTC = dt.timezone.utc
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'
PPV = 'https://api.ppv.st/api/streams'
SF = 'https://streamfree.top/streams'
RESOLVER = 'http://127.0.0.1:38765'
CONFIG = pathlib.Path(os.environ.get('XDG_CONFIG_HOME', pathlib.Path.home() / '.config')) / 'nba-tui' / 'config.json'


def request(url, *, data=None, headers=None, timeout=12):
    h = {'User-Agent': UA, 'Accept': 'application/json,*/*'}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError('Response too large')
    return json.loads(raw)


def load_config():
    try:
        x = json.loads(CONFIG.read_text())
        return x if isinstance(x, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(config):
    CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(config, f, indent=2)


def parse_date(s):
    try:
        return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(UTC)
    except (AttributeError, ValueError):
        return None


def safe_url(url):
    try:
        p = urllib.parse.urlsplit(url)
        return p.scheme in ('http', 'https') and bool(p.netloc) and not p.username and not p.password
    except (ValueError, TypeError):
        return False


def title_matches(title, game):
    text = re.sub(r'[^a-z0-9]+', ' ', str(title).lower()).strip()
    def has_team(nickname):
        normalized = re.sub(r'[^a-z0-9]+', ' ', nickname.lower()).strip()
        return bool(normalized and re.search(r'\b' + re.escape(normalized) + r'\b', text))
    return has_team(game.home_nickname) and has_team(game.away_nickname)


def feed_side(label):
    text = str(label).lower()
    if re.search(r'\bhome\b', text) and not re.search(r'\baway\b', text):
        return 'home'
    if re.search(r'\baway\b', text) and not re.search(r'\bhome\b', text):
        return 'away'
    return 'unknown'


@dataclass
class Game:
    id: str
    title: str
    start: dt.datetime
    home: str
    away: str
    home_nickname: str
    away_nickname: str
    broadcasts: list[str] = field(default_factory=list)

    @property
    def lakers_side(self):
        if 'lakers' in self.home.lower(): return 'home'
        if 'lakers' in self.away.lower(): return 'away'
        return ''


@dataclass
class Feed:
    source: str
    label: str
    side: str = 'unknown'
    url: str = ''
    kind: str = 'web'  # ppv: resolve at playback, direct: media URL, web: browser only
    headers: dict = field(default_factory=dict)
    note: str = ''


def games_from_espn(data, now=None):
    result = []
    for e in data.get('events', []):
        start = parse_date(e.get('date'))
        comps = e.get('competitions') or []
        if not start or not comps:
            continue
        comp = comps[0]
        teams = {c.get('homeAway'): c.get('team', {}) for c in comp.get('competitors', [])}
        home, away = teams.get('home', {}), teams.get('away', {})
        home_name, away_name = home.get('displayName', ''), away.get('displayName', '')
        if not home_name or not away_name:
            continue
        home_nick = home.get('name') or home.get('shortDisplayName') or home_name.split()[-1]
        away_nick = away.get('name') or away.get('shortDisplayName') or away_name.split()[-1]
        broadcasts = []
        for b in comp.get('broadcasts', []):
            market = b.get('market', '')
            if isinstance(market, dict): market = market.get('type', '')
            names = b.get('names', []) or [b.get('media', {}).get('shortName', '')]
            for channel in names:
                if channel:
                    label = channel + (f' ({market.capitalize()})' if market.lower() in ('home', 'away') else '')
                    if label not in broadcasts: broadcasts.append(label)
        result.append(Game(str(e.get('id', '')), e.get('name', f'{away_name} at {home_name}'), start, home_name, away_name, home_nick, away_nick, broadcasts))
    return sorted(result, key=lambda g: g.start)


def default_day():
    try: return dt.datetime.now(ZoneInfo('America/New_York')).date()
    except Exception: return dt.datetime.now().date()


def get_games(day=None):
    day = day or default_day()
    return games_from_espn(request(ESPN + '?dates=' + day.strftime('%Y%m%d')))


def ppv_feeds(data, game):
    feeds = []
    for group in data.get('streams', []):
        for event in group.get('streams', []):
            if not title_matches(event.get('name', ''), game):
                continue
            try:
                event_start = dt.datetime.fromtimestamp(int(event.get('starts_at', 0)), UTC)
            except (TypeError, ValueError, OverflowError, OSError):
                continue
            if abs((event_start - game.start).total_seconds()) > 6 * 3600:
                continue
            for src in [event, *(event.get('substreams') or [])]:
                url = src.get('iframe', '')
                if not safe_url(url):
                    continue
                label = src.get('source_tag') or src.get('name') or 'Broadcast'
                feeds.append(Feed('PPV', label, feed_side(label), url, 'ppv', note='local resolver for mpv; browser available'))
    return feeds


def sf_feeds(data, game):
    out = []
    for event in data.get('streams', {}).get('basketball', []):
        if not title_matches(event.get('name', ''), game):
            continue
        try:
            t = dt.datetime.fromtimestamp(int(event.get('match_timestamp', 0)), UTC)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if abs((t - game.start).total_seconds()) <= 6 * 3600:
            # Its index is accessible even when a player's embed is unavailable.
            out.append(Feed('StreamFree', 'Game listing', url='https://streamfree.top/', kind='web', note='find the game on this site; browser only'))
    return out


def addon_base(manifest):
    manifest = manifest.strip().replace('stremio://', 'https://', 1)
    if not safe_url(manifest):
        raise ValueError('Enter a valid HTTP(S) manifest URL')
    parts = urllib.parse.urlsplit(manifest)
    if not parts.path.endswith('/manifest.json') or parts.query or parts.fragment:
        raise ValueError('The add-on URL must end in /manifest.json')
    return manifest[:-len('/manifest.json')]


def addon_feeds(manifest, game):
    base = addon_base(manifest)
    meta = request(manifest.replace('stremio://', 'https://', 1))
    catalogs = meta.get('catalogs', [])
    # Only use basketball/sports catalogs; do not fan out across an arbitrary add-on.
    candidates = [c for c in catalogs if re.search(r'basketball|sports.*today|sports.*live|live.*sport', str(c.get('id', '')) + ' ' + str(c.get('name', '')), re.I)]
    if not candidates:
        candidates = [c for c in catalogs if c.get('type') in ('sport', 'tv')][:3]
    found = {}
    for cat in candidates[:4]:
        typ, ident = str(cat.get('type', '')), str(cat.get('id', ''))
        if not re.fullmatch(r'[\w.-]+', typ) or not re.fullmatch(r'[\w.-]+', ident):
            continue
        try:
            data = request(f'{base}/catalog/{typ}/{ident}.json')
        except (OSError, ValueError):
            continue
        for item in data.get('metas', []):
            if title_matches(item.get('name', ''), game):
                found[(typ, str(item.get('id', '')))] = item
    if len(found) != 1:
        if len(found) > 1:
            raise ValueError('Add-on returned more than one matching game; no match selected')
        return []
    (typ, ident), item = next(iter(found.items()))
    if not ident:
        return []
    url = f'{base}/stream/{typ}/{urllib.parse.quote(ident, safe=":")}.json'
    data = request(url, timeout=20)
    out = []
    for s in data.get('streams', []):
        label = ' '.join(str(s.get(k, '')).replace('\n', ' ') for k in ('name', 'title', 'description')).strip()
        if re.search(r'please reinstall|no streams|no sources|visit .*configure', label, re.I):
            continue
        url = s.get('url', '')
        hints = s.get('behaviorHints') or {}
        headers = (hints.get('proxyHeaders') or {}).get('request') or {}
        if not isinstance(headers, dict):
            headers = {}
        if safe_url(url):
            out.append(Feed('Add-on', label or 'Stream', feed_side(label), url, 'direct', headers, 'media link from add-on; availability not yet checked'))
        elif safe_url(s.get('externalUrl', '')):
            out.append(Feed('Add-on', label or 'Web player', feed_side(label), s['externalUrl'], 'web', note='browser only'))
    return out


def fetch_feeds(game, config):
    out, errors = [], []
    for name, url, parser in [('PPV', PPV, ppv_feeds), ('StreamFree', SF, sf_feeds)]:
        try:
            out.extend(parser(request(url), game))
        except (OSError, ValueError, KeyError, TypeError) as e:
            errors.append(f'{name}: {type(e).__name__}')
    if config.get('addon'):
        try:
            out.extend(addon_feeds(config['addon'], game))
        except (OSError, ValueError, KeyError, TypeError) as e:
            errors.append(f'Add-on: {type(e).__name__}')
    return out, errors


def mpv_command(url, headers=None, *, cache=15, terminal_video=False):
    cmd = ['mpv', '--force-window=yes', '--title=NBA Live', '--demuxer-lavf-o=allowed_extensions=ALL,allowed_segment_extensions=ALL,extension_picky=0', '--cache=yes', f'--cache-secs={cache}', '--demuxer-max-bytes=256MiB', '--demuxer-readahead-secs=' + str(cache)]
    if terminal_video:
        cmd.append('--vo=tct')
    for name, value in (headers or {}).items():
        if not isinstance(name, str) or not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9-]+', name) or '\n' in value or '\r' in value or ',' in value:
            continue
        cmd.append(f'--http-header-fields-append={name}: {value}')
    cmd.extend(['--', url])
    return cmd


class App:
    def __init__(self, screen, config):
        self.scr, self.config = screen, config
        self.games, self.all_games, self.feeds = [], [], []
        self.day = default_day()
        self.search = ''
        self.gi = self.fi = 0
        self.mode = 'games'
        self.filter = 'all'
        self.message = 'Loading games...'
        self.errors = []
        self.helper = None
        self.resolver_owned = False
        self.cache = int(config.get('cache', 15)) if str(config.get('cache', 15)) in ('5','15','30') else 15
        self.terminal_video = bool(config.get('terminal_video', False))

    def put(self, y, x, s, attr=0):
        h, w = self.scr.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        try:
            self.scr.addnstr(y, x, str(s), max(0, w-x-1), attr)
        except curses.error:
            pass

    def visible_feeds(self):
        if self.filter == 'all':
            return self.feeds
        side = self.games[self.gi].lakers_side if self.filter == 'lakers' else self.filter
        return [f for f in self.feeds if f.side == side]

    def render(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        self.put(0, 1, 'NBA / LIVE', curses.A_BOLD)
        self.put(1, 1, 'Games' if self.mode == 'games' else 'Broadcasts', curses.A_BOLD)
        if h < 12 or w < 48:
            self.put(3, 1, 'Please enlarge your terminal to at least 48 x 12.')
            self.put(h-2, 1, 'q quit')
            self.scr.refresh(); return
        if self.mode == 'games':
            self.put(2, 1, f'{self.day:%a %b %d, %Y} (NBA date / ET)  |  local times  |  search: {self.search or "all"}')
            rows = max(1, h-7)
            start = max(0, self.gi-rows+1)
            for y, game in enumerate(self.games[start:start+rows], 3):
                selected = start+y-3 == self.gi
                when = game.start.astimezone().strftime('%a %b %d  %I:%M %p %Z')
                self.put(y, 2, f'{">" if selected else " "} {when}  {game.title}', curses.A_REVERSE if selected else 0)
            if not self.games:
                self.put(4, 2, 'No matching games. Change date or search.')
            self.put(h-4, 1, 'Enter streams   [ ] date   / search   r refresh')
            self.put(h-3, 1, 'a add-on   s resolver   q quit')
        else:
            game = self.games[self.gi]
            self.put(2, 1, f'{game.title}  |  {game.start.astimezone().strftime("%a %b %d %I:%M %p %Z")}')
            self.put(3, 1, 'TV: ' + (', '.join(game.broadcasts) or 'not listed'))
            self.put(4, 1, f'Filter: {self.filter}   |   Cache: {self.cache}s   |   Video: {"terminal" if self.terminal_video else "window"}')
            fs = self.visible_feeds()
            self.fi = min(self.fi, max(0, len(fs)-1))
            rows = max(1, h-10)
            start = max(0, self.fi-rows+1)
            for y, feed in enumerate(fs[start:start+rows], 6):
                selected = start+y-6 == self.fi
                side = feed.side.upper() if feed.side != 'unknown' else '?'
                kind = {'ppv':'MPV* / WEB', 'direct':'MPV', 'web':'WEB'}[feed.kind]
                self.put(y, 2, f'{">" if selected else " "} [{side:7}] {feed.source:10} {feed.label} [{kind}]', curses.A_REVERSE if selected else 0)
            if not fs:
                self.put(6, 2, 'No matching feeds. Try refresh near tipoff or change the filter.')
            self.put(h-4, 1, 'Enter play   b browser   f filter   r refresh   Esc back')
            self.put(h-3, 1, 'c cache   v video   u URL   a add-on   s resolver   q quit')
        self.put(h-1, 1, self.message)
        self.scr.refresh()

    def refresh_games(self):
        self.message = 'Loading NBA games for this date...'; self.render()
        try:
            self.all_games = get_games(self.day); self.apply_search()
            self.message = f'{len(self.games)} games shown. Select one.'
        except Exception as e:
            self.message = f'Schedule unavailable: {type(e).__name__}. Press r to retry.'

    def apply_search(self):
        query = self.search.lower()
        self.games = [g for g in self.all_games if query in (g.title + ' ' + g.home + ' ' + g.away).lower()]
        self.gi = min(self.gi, max(0, len(self.games)-1))

    def refresh_feeds(self):
        self.message = 'Checking sources...'; self.render()
        self.feeds, self.errors = fetch_feeds(self.games[self.gi], self.config)
        self.fi = 0
        self.message = f'{len(self.feeds)} choices found' + (' | ' + ', '.join(self.errors) if self.errors else '')
        if self.config.get('addon') and not any(f.source == 'Add-on' for f in self.feeds):
            self.message += ' | no add-on streams returned'

    def prompt(self, label, initial=''):
        # A normal terminal prompt accepts long manifest URLs and lets the user paste.
        curses.def_prog_mode()
        curses.endwin()
        try:
            return input('\n' + label + ' ').strip()
        except EOFError:
            return ''
        finally:
            curses.reset_prog_mode()
            self.scr.clear()
            self.scr.refresh()

    def configure_addon(self):
        value = self.prompt('Add-on manifest URL (blank clears):')
        if value:
            try: addon_base(value)
            except ValueError as e: self.message = str(e); return
            self.config['addon'] = value
        else:
            self.config.pop('addon', None)
        save_config(self.config)
        self.message = 'Add-on saved.' if value else 'Add-on removed.'
        if self.mode == 'feeds': self.refresh_feeds()

    def configure_resolver(self):
        value = self.prompt('Resolver folder (blank clears):')
        if value:
            path = pathlib.Path(value).expanduser().resolve()
            if not (path / 'src/server.js').is_file():
                self.message = 'Folder must contain src/server.js'; return
            self.config['resolver_dir'] = str(path)
        else:
            self.config.pop('resolver_dir', None)
        save_config(self.config)
        self.message = 'Resolver folder saved.' if value else 'Resolver folder cleared.'

    def helper_running(self):
        try:
            with socket.create_connection(('127.0.0.1', 38765), timeout=0.3): return True
        except OSError:
            return False

    def ensure_helper(self):
        if self.helper_running(): return
        directory = self.config.get('resolver_dir') or os.environ.get('NBA_RESOLVER_DIR', '') or str(pathlib.Path(__file__).resolve().parent / 'resolver')
        if not directory:
            raise RuntimeError('Set up the resolver and press s to select its folder; see README.')
        entry = pathlib.Path(directory).expanduser() / 'src/server.js'
        if not entry.is_file() or not (entry.parent.parent / 'node_modules').is_dir():
            raise RuntimeError('Resolver or dependencies missing; see README.')
        if not shutil.which('node'):
            raise RuntimeError('Node.js is required for the resolver.')
        env = os.environ.copy(); env.update({'HOST':'127.0.0.1', 'PORT':'38765', 'NODE_USE_ENV_PROXY':'1'})
        self.helper = subprocess.Popen(['node', str(entry.resolve())], cwd=str(entry.parent.parent), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.resolver_owned = True
        for _ in range(35):
            if self.helper.poll() is not None: raise RuntimeError('Resolver failed to start; run npm install in its folder.')
            if self.helper_running(): return
            time.sleep(.1)
        raise RuntimeError('Resolver did not start on localhost:38765.')

    def play(self, feed):
        if feed.kind == 'web':
            self.message = 'Browser-only source. Press b to open it.'; return
        if not shutil.which('mpv'):
            self.message = 'mpv is not installed or not on PATH.'; return
        url, headers = feed.url, feed.headers
        if feed.kind == 'ppv':
            self.message = 'Resolving selected broadcast...'; self.render()
            try:
                self.ensure_helper()
                data = request(RESOLVER + '/api/embed', data={'iframe':feed.url}, timeout=35)
                url = data.get('proxiedUrl', '')
                if not data.get('ok') or not safe_url(url):
                    raise RuntimeError(data.get('error', 'No playable URL returned'))
                # Only trust the local helper's relay, not a URL to an unrelated host.
                u = urllib.parse.urlsplit(url)
                if u.hostname not in ('localhost','127.0.0.1') or u.port != 38765:
                    raise RuntimeError('Unexpected resolver URL')
                headers = {}
            except (OSError, ValueError, RuntimeError) as e:
                self.message = f'Resolver failed: {e}'; return
        self.message = 'Starting mpv. Press q in mpv to return.'; self.render()
        curses.def_prog_mode(); curses.endwin()
        try:
            result = subprocess.run(mpv_command(url, headers, cache=self.cache, terminal_video=self.terminal_video), check=False)
            self.message = 'Returned from mpv.' if result.returncode == 0 else f'mpv exited with status {result.returncode}; try another feed.'
        except OSError as e:
            self.message = f'Could not start mpv: {e}'
        finally:
            curses.reset_prog_mode(); self.scr.refresh()

    def close(self):
        if self.resolver_owned and self.helper and self.helper.poll() is None:
            self.helper.terminate()
            try: self.helper.wait(timeout=3)
            except subprocess.TimeoutExpired: self.helper.kill(); self.helper.wait()

    def run(self):
        try:
            curses.curs_set(0)
        except curses.error: pass
        self.scr.keypad(True)
        self.refresh_games()
        try:
            while True:
                self.render(); key = self.scr.getch()
                if key in (ord('q'),): break
                if key in (curses.KEY_UP, ord('k')):
                    if self.mode == 'games': self.gi = max(0, self.gi-1)
                    else: self.fi = max(0, self.fi-1)
                elif key in (curses.KEY_DOWN, ord('j')):
                    if self.mode == 'games': self.gi = min(max(0,len(self.games)-1), self.gi+1)
                    else: self.fi = min(max(0,len(self.visible_feeds())-1), self.fi+1)
                elif key in (10,13,curses.KEY_ENTER):
                    if self.mode == 'games' and self.games:
                        self.mode = 'feeds'; self.filter = 'all'; self.refresh_feeds()
                    elif self.mode == 'feeds' and self.visible_feeds(): self.play(self.visible_feeds()[self.fi])
                elif key in (27, curses.KEY_BACKSPACE, 127, ord('h')) and self.mode == 'feeds':
                    self.mode = 'games'; self.message = 'Select a game.'
                elif key == ord('r'):
                    if self.mode == 'games': self.refresh_games()
                    else: self.refresh_feeds()
                elif self.mode == 'games' and key in (ord('['), ord(']')):
                    self.day += dt.timedelta(days=-1 if key == ord('[') else 1); self.gi = 0; self.refresh_games()
                elif self.mode == 'games' and key == ord('/'):
                    self.search = self.prompt('Team search (blank clears):'); self.apply_search(); self.message = f'{len(self.games)} games shown.'
                elif key == ord('a'): self.configure_addon()
                elif key == ord('s'): self.configure_resolver()
                elif self.mode == 'feeds' and key == ord('f'):
                    filters = ['all','home','away','unknown'];
                    if self.games[self.gi].lakers_side: filters.insert(1, 'lakers')
                    self.filter = filters[(filters.index(self.filter)+1)%len(filters)]; self.fi=0
                elif self.mode == 'feeds' and key == ord('b') and self.visible_feeds():
                    feed = self.visible_feeds()[self.fi]
                    if feed.kind == 'direct': self.message = 'This is a media URL; press Enter for mpv.'
                    else:
                        try: self.message = 'Opened browser.' if webbrowser.open(feed.url) else 'Could not open a browser.'
                        except Exception: self.message = 'Could not open a browser.'
                elif self.mode == 'feeds' and key == ord('c'):
                    self.cache = {5:15,15:30,30:5}[self.cache]; self.config['cache']=self.cache; save_config(self.config)
                elif self.mode == 'feeds' and key == ord('v'):
                    self.terminal_video = not self.terminal_video; self.config['terminal_video']=self.terminal_video; save_config(self.config)
                elif self.mode == 'feeds' and key == ord('u'):
                    value = self.prompt('Direct media URL:')
                    if safe_url(value): self.play(Feed('Manual','Pasted URL',url=value,kind='direct'))
                    else: self.message = 'Enter a valid HTTP(S) media URL.'
        finally:
            self.close()


def main():
    parser = argparse.ArgumentParser(description='Browse NBA games and choose streams.')
    parser.add_argument('--list', action='store_true', help='Print upcoming games and feed listings without a terminal UI')
    parser.add_argument('--date', help='NBA schedule date in YYYY-MM-DD (Eastern time)')
    parser.add_argument('--addon', help='Stremio sports add-on manifest URL for this run')
    parser.add_argument('--resolver-dir', help='Local ppv-hls-proxy checkout for this run')
    args = parser.parse_args(); config = load_config()
    if args.addon: config['addon'] = args.addon
    if args.resolver_dir: config['resolver_dir'] = args.resolver_dir
    if args.list:
        try:
            day = dt.date.fromisoformat(args.date) if args.date else default_day()
            games = get_games(day)
            if not games: print('No NBA games found for that date.'); return 0
            for i, game in enumerate(games, 1):
                print(f'{i:2}. {game.start.astimezone():%Y-%m-%d %H:%M %Z}  {game.title}')
            g = next((game for game in games if game.lakers_side), games[0])
            print('\nStreams for:', g.title)
            print('TV:', ', '.join(g.broadcasts) or 'not listed')
            feeds, errors = fetch_feeds(g, config)
            for f in feeds:
                print(f'[{f.side.upper():7}] {f.source}: {f.label} ({f.kind})')
            for e in errors: print('Source error:', e, file=sys.stderr)
            if not feeds: print('No feeds found yet. Try again closer to tipoff.')
            return 0
        except Exception as e:
            print(f'Could not load schedule: {type(e).__name__}: {e}', file=sys.stderr); return 1
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('An interactive terminal is required; use --list for plain output.', file=sys.stderr); return 2
    try:
        def run_ui(screen):
            app = App(screen, config)
            if args.date: app.day = dt.date.fromisoformat(args.date)
            app.run()
        curses.wrapper(run_ui)
    except KeyboardInterrupt:
        pass
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
