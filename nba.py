#!/usr/bin/env python3
"""Sports terminal stream picker. Python standard library only."""
from __future__ import annotations
import argparse
import curses
import concurrent.futures
import datetime as dt
import json
import os
import pathlib
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import providers
import relay
import grading
import replays
import smart_search
import ad_mute
import ai_ad_mute
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field

UTC = dt.timezone.utc
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports'
LEAGUES = {
    'nba': ('NBA', 'basketball/nba', 'basketball'),
    'wnba': ('WNBA', 'basketball/wnba', 'basketball'),
    'ncaam': ("NCAA men's basketball", 'basketball/mens-college-basketball', 'basketball'),
    'ncaaw': ("NCAA women's basketball", 'basketball/womens-college-basketball', 'basketball'),
    'nfl': ('NFL', 'football/nfl', 'football'),
    'ncaaf': ('NCAA football', 'football/college-football', 'football'),
    'mlb': ('MLB', 'baseball/mlb', 'baseball'),
    'nhl': ('NHL', 'hockey/nhl', 'hockey'),
    'mls': ('Soccer: MLS', 'soccer/usa.1', 'soccer'),
    'epl': ('Soccer: Premier League', 'soccer/eng.1', 'soccer'),
    'laliga': ('Soccer: La Liga', 'soccer/esp.1', 'soccer'),
    'bundesliga': ('Soccer: Bundesliga', 'soccer/ger.1', 'soccer'),
    'seriea': ('Soccer: Serie A', 'soccer/ita.1', 'soccer'),
    'ligue1': ('Soccer: Ligue 1', 'soccer/fra.1', 'soccer'),
    'ligamx': ('Soccer: Liga MX', 'soccer/mex.1', 'soccer'),
    'ucl': ('Soccer: Champions League', 'soccer/uefa.champions', 'soccer'),
}
PPV = 'https://api.ppv.st/api/streams'
SF = 'https://streamfree.top/streams'
SF_ROOT = 'https://streamfree.top'
NTV = 'https://ntv.st'
RESOLVER = 'http://127.0.0.1:38765'
CONFIG = pathlib.Path(os.environ.get('XDG_CONFIG_HOME', pathlib.Path.home() / '.config')) / 'nba-tui' / 'config.json'
HELP_LINES = [
    'SEARCH         Type a team or matchup    arrows: select    Enter: open',
    'GLOBAL         Ctrl-F: search from anywhere    Tab: browse sports',
    'NAVIGATE       Up/Down or j/k: move    Enter: select    Esc: back',
    'SCHEDULE       s: sport    [ / ]: date    /: team search    l: Lakers',
    'REPLAYS        R: replay archive    s: sport    /: search titles',
    'SOURCES        f: broadcast side    o: provider    /: search choices',
    'CHECKS         t: test selected source    g: rank by your checks',
    'PLAYERS        p: player    c: cache    v: terminal video (mpv)',
    'AD MUTE        --ad-mute: marked replays in mpv only',
    'AI ADS         --ai-ad-mute: optional local NBA detector in mpv',
    'MORE           i: show media URL    u: play a pasted media URL',
    'SETUP          a: sports add-on    d: local PPV resolver',
    'REFRESH        r: reload current list    q: quit',
    'Finished games and explicitly offline sources are hidden from live lists.',
    'Keep this terminal open while playing a local relay stream.',
]


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
    def normalize(value):
        text = unicodedata.normalize('NFKD', str(value).casefold())
        text = ''.join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r'\bstate\b', 'st', text)
        return re.sub(r'[^a-z0-9]+', ' ', text).strip()

    text = normalize(title)
    def spans(names):
        found = []
        for name in names:
            name = normalize(name)
            variants = [name]
            if game.category == 'soccer':
                # ESPN sometimes includes FC/CF while a directory leaves it out.
                variants.append(re.sub(r'\b(?:fc|cf)\b', '', name).strip())
            for variant in variants:
                variant = ' '.join(variant.split())
                if len(variant) >= 3:
                    found.extend(m.span() for m in re.finditer(r'\b' + re.escape(variant) + r'\b', text))
        return found

    home = spans([game.home_nickname, *game.home_aliases])
    away = spans([game.away_nickname, *game.away_aliases])
    # Distinct occurrences prevent a shared location or college nickname from
    # matching both teams when only one is actually present.
    return any(a[1] <= b[0] or b[1] <= a[0] for a in home for b in away)


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
    league: str = 'nba'
    category: str = 'basketball'
    home_aliases: list[str] = field(default_factory=list)
    away_aliases: list[str] = field(default_factory=list)
    state: str = 'unknown'

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
    kind: str = 'web'  # Resolve sources on selection so short-lived links are fresh.
    headers: dict = field(default_factory=dict)
    note: str = ''
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FeedDisplay:
    name: str
    side: str
    quality: str
    check: str
    detail: str


def describe_feed(feed, record=None, automatic=None):
    """Turn provider-specific labels into consistent, readable stream rows."""
    parts = [part.strip() for part in feed.label.split('|') if part.strip()]
    server = re.sub(r'\s*\((?:home|away)\)\s*$', '', parts[0] if parts else feed.label, flags=re.I)
    details, listed_quality = [], ''
    for part in parts[1:]:
        if re.fullmatch(r'\d{3,4}p|4k|hd|sd', part, re.I):
            listed_quality = part.upper() if part.lower() in ('hd','sd','4k') else part.lower()
        elif part.lower() == 'live':
            details.append('Provider reports live')
        elif part.lower() != 'status unknown':
            details.append(part)
    record = record if isinstance(record, dict) else {}
    height = record.get('height')
    quality = f'{height}p' if isinstance(height, int) and height >= 144 else f'~{listed_quality}' if listed_quality else '-'
    status = {'checking':'Checking', 'OK':'OK', '?':'Unverified'}.get(automatic, automatic or 'Unverified')
    grade = grading.summary(record)
    if grade:
        grade = re.sub(r'\s+\d+p$', '', grade)
        status += f' {grade}'
    if not details and feed.kind == 'candidate': details.append('Player resolves on selection')
    return FeedDisplay(f'{feed.source} / {server}', feed.side.upper() if feed.side != 'unknown' else '-',
                       quality, status, ' | '.join(details))


class DependencyError(RuntimeError):
    """The stream has not been checked because a local dependency is missing."""


def games_from_espn(data, now=None, league='nba'):
    result = []
    for e in data.get('events', []):
        start = parse_date(e.get('date'))
        comps = e.get('competitions') or []
        if not start or not comps:
            continue
        comp = comps[0]
        status = (e.get('status') or {}).get('type') or (comp.get('status') or {}).get('type') or {}
        # ESPN explicitly marks finished/canceled events; do not infer from
        # their start time because games can run long or be delayed.
        if (status.get('completed') is True or status.get('state') == 'post'
                or status.get('name') in ('STATUS_CANCELED', 'STATUS_CANCELLED')):
            continue
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
        def aliases(team):
            return [team.get(key, '') for key in ('displayName', 'location', 'shortDisplayName')]
        state = {'in':'live', 'pre':'upcoming'}.get(status.get('state'), 'unknown')
        result.append(Game(str(e.get('id', '')), e.get('name', f'{away_name} at {home_name}'), start, home_name, away_name, home_nick, away_nick, broadcasts, league, LEAGUES[league][2], aliases(home), aliases(away), state))
    return sorted(result, key=lambda g: g.start)


def default_day():
    try: return dt.datetime.now(ZoneInfo('America/New_York')).date()
    except Exception: return dt.datetime.now().date()


def get_games(day=None, league='nba'):
    day = day or default_day()
    path = LEAGUES[league][1]
    return games_from_espn(request(f'{ESPN}/{path}/scoreboard?dates={day:%Y%m%d}&limit=300'), league=league)


def ppv_feeds(data, game, now=None):
    feeds = []
    now = now or dt.datetime.now(UTC)
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
            try:
                ends_at = int(event.get('ends_at') or 0)
            except (TypeError, ValueError, OverflowError):
                ends_at = 0
            if ends_at and ends_at <= now.timestamp() and not event.get('always_live'):
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
    for event in data.get('streams', {}).get(game.category, []):
        if not title_matches(event.get('name', ''), game):
            continue
        try:
            t = dt.datetime.fromtimestamp(int(event.get('match_timestamp', 0)), UTC)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if abs((t - game.start).total_seconds()) > 6 * 3600:
            continue
        key = event.get('stream_key', '')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', key):
            continue
        sources = request(SF_ROOT + '/api/v1/sources/' + urllib.parse.quote(key))
        live_sources = sources.get('live_sources')
        live = set(live_sources) if isinstance(live_sources, list) else None
        for source in sources.get('sources', [])[:20]:
            if live is not None and source not in live:
                continue
            parts = urllib.parse.urlsplit(source)
            variant = parts.path.rsplit('/', 1)[-1]
            match = re.fullmatch(re.escape(key) + r'(\d+p)(\d*)', variant)
            if not match or not parts.path.startswith('/embed/' + game.category + '/'):
                continue
            quality, number = match.groups()
            number = number or '1'
            embed = SF_ROOT + parts.path
            status = 'live' if live is not None else 'status unknown'
            out.append(Feed('StreamFree', f'Source {number} | {quality} | {status}', url=embed,
                            kind='sf', metadata={'key': key, 'quality': quality, 'variant': variant, 'category': game.category}))
    return out


def request_text(url, *, headers=None, timeout=12, limit=1_000_000):
    h = {'User-Agent': UA, 'Accept': '*/*'}
    if headers:
        h.update(headers)
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as res:
        data = res.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Response too large')
    return data.decode('utf-8', 'replace')


def resolve_streamfree(feed, *, timeout=12):
    key = feed.metadata['key']
    quality = feed.metadata['quality']
    variant = feed.metadata['variant']
    category = feed.metadata.get('category', 'basketball')
    embed_headers = {'Referer': f'{SF_ROOT}/player/{category}/{key}', 'Origin': SF_ROOT}
    page = request_text(feed.url, headers=embed_headers, timeout=timeout)
    match = re.search(r'const\s+_0x\s*=\s*(\{.*?\})\s*;', page, re.S)
    if not match:
        raise ValueError('StreamFree player did not provide playlist tokens')
    tokens = json.loads(match.group(1)).get(quality)
    if not isinstance(tokens, dict) or not all(key in tokens for key in ('_t', '_e', '_n')):
        raise ValueError('StreamFree playlist tokens are missing')
    info = request(SF_ROOT + '/get-stream-key/' + urllib.parse.quote(key), headers=embed_headers, timeout=timeout)
    if info.get('is_external') and info.get('external_url'):
        url = info['external_url']
        if not safe_url(url):
            raise ValueError('Invalid external stream URL')
    else:
        server = info.get('server_name') or 'origin'
        route = 'live-externalcdn' if server == 'externalcdn' else 'live-cdn' if server != 'origin' else 'live'
        query = urllib.parse.urlencode({k: tokens[k] for k in ('_t', '_e', '_n')})
        url = f'{SF_ROOT}/{route}/{urllib.parse.quote(variant)}/index.m3u8?{query}'
    headers = {'Referer': feed.url, 'Origin': SF_ROOT, 'User-Agent': UA}
    return url, headers


def check_playlist(url, headers=None):
    manifest = request_text(url, headers=headers, timeout=10)
    if not manifest.lstrip().startswith('#EXTM3U'):
        raise ValueError('Provider did not return an HLS playlist')
    if not any(line.strip() and not line.lstrip().startswith('#') for line in manifest.splitlines()):
        raise ValueError('Playlist has no media yet')
    return manifest


def streamfree_wraps_segments(url, manifest, headers):
    """Detect StreamFree's PNG transport-stream chunks using a small segment sample."""
    if any(tag in manifest for tag in ('#EXT-X-STREAM-INF', '#EXT-X-MAP', '#EXT-X-KEY', '#EXT-X-BYTERANGE')):
        return False
    segments = [line.strip() for line in manifest.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if not segments: return False
    segment = urllib.parse.urljoin(url, segments[-2] if len(segments) > 1 else segments[-1])
    if not providers.public_url(segment): raise ValueError('Invalid StreamFree segment URL')
    req = urllib.request.Request(segment, headers=headers)
    with urllib.request.build_opener(providers.PublicRedirect()).open(req, timeout=8) as response:
        sample = response.read(256)
    if not sample.startswith(b'\x89PNG\r\n\x1a\n'): return False
    pos = 8
    while pos + 8 <= len(sample):
        size = int.from_bytes(sample[pos:pos+4], 'big')
        tag = sample[pos+4:pos+8]
        if tag == b'tsDa': return True
        if size > len(sample)-pos-12: break
        pos += size+12
    return False


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
    # Only query the selected sport and generic sports catalogs.
    pattern = re.escape(game.category) + r'|sports.*today|sports.*live|live.*sport'
    candidates = [c for c in catalogs if re.search(pattern, str(c.get('id', '')) + ' ' + str(c.get('name', '')), re.I)]
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
    return out


def feed_tasks(game, config):
    tasks = [('StreamFree', lambda: sf_feeds(request(SF), game)),
             ('PPV', lambda: ppv_feeds(request(PPV), game)),
             ('NTV', lambda: ntv_feeds(game))]
    if game.league == 'nba':
        tasks.extend([('NBA Monster', lambda: monster_feeds(game)),
                      ('NBA Bite', lambda: directory_feeds(game))])
    if config.get('addon'):
        tasks.append(('Add-on', lambda: addon_feeds(config['addon'], game)))
    return tasks


def fetch_feeds(game, config):
    out, errors = [], []
    tasks = feed_tasks(game, config)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [(name, pool.submit(fn)) for name, fn in tasks]
        for name, future in futures:
            try:
                out.extend(future.result())
            except (OSError, ValueError, KeyError, TypeError) as e:
                errors.append(f'{name}: {type(e).__name__}')
    return out, errors


def channel_side(channel, game):
    explicit = feed_side(channel)
    if explicit != 'unknown': return explicit
    # A generic League Pass label may carry either side; do not guess.
    if 'league pass' in channel.lower(): return 'unknown'
    clean = lambda x: re.sub(r'[^a-z0-9]', '', x.lower())
    candidate = clean(channel)
    sides = set()
    for broadcast in game.broadcasts:
        side = feed_side(broadcast)
        name = clean(re.sub(r'\s*\((?:Home|Away)\)\s*$', '', broadcast, flags=re.I))
        if side != 'unknown' and len(name) >= 6 and name in candidate: sides.add(side)
    return next(iter(sides)) if len(sides) == 1 else 'unknown'


def directory_feeds(game):
    out = []
    for item in providers.nbabite_entries(game, title_matches):
        channel = item['channel'] or 'Unknown channel'
        label = f"{item['name']} | {channel} | {item['quality']} | {item['language']}"
        out.append(Feed('NBA Bite', label, channel_side(channel, game), item['url'], 'candidate',
                        note='directory listing; resolved when selected', metadata={'referer':providers.NBABITE+'/'}))
    return out


def monster_feeds(game):
    return [Feed('NBA Monster', item['name'], url=item['url'], kind='candidate',
                 note='directory listing; resolved when selected', metadata={'referer':providers.MONSTER+'/'})
            for item in providers.monster_entries(game)]


def ntv_feeds(game):
    def fetch_server(server):
        data = request(f'{NTV}/api/get-matches?server={server}&type=both',
                       headers={'Referer':NTV+'/'}, timeout=12)
        if not data.get('success'): raise ValueError('NTV directory unavailable')
        out = []
        for event in data.get('all', []):
            if not title_matches(event.get('title', ''), game): continue
            if event.get('live') is False or str(event.get('status', '')).lower() in ('upcoming', 'offline', 'ended', 'finished'):
                continue
            try: event_time = dt.datetime.fromtimestamp(int(event.get('date', 0))/1000, UTC)
            except (ValueError, TypeError, OverflowError, OSError): continue
            if abs((event_time-game.start).total_seconds()) > 6*3600: continue
            for source in event.get('sources', [])[:25]:
                url = source.get('url', '')
                if not providers.public_url(url): continue
                channel = source.get('channelName') or source.get('source') or 'Stream'
                label = f'{server.title()} | {channel}'
                out.append(Feed('NTV', label, channel_side(channel,game), url, 'candidate',
                                note='directory listing; resolved when selected',
                                metadata={'referer':NTV+'/', 'provider':server + '/' + str(source.get('source',''))
                                          + '/' + str(source.get('channelId') or channel)}))
        return out
    out = []
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(fetch_server, server) for server in ('phoenix', 'falcon')]
        for future in futures:
            try: out.extend(future.result())
            except (OSError, ValueError, TypeError, KeyError) as exc: failures.append(exc)
    if len(failures) == len(futures): raise failures[0]
    seen = set()
    return [f for f in out if not (f.url in seen or seen.add(f.url))]


def mpv_command(url, headers=None, *, cache=15, terminal_video=False):
    cmd = ['mpv', '--no-ytdl', '--force-window=yes', '--title=Sports Live', '--demuxer-lavf-o=allowed_extensions=ALL,allowed_segment_extensions=ALL,extension_picky=0', '--cache=yes', f'--cache-secs={cache}', '--demuxer-max-bytes=256MiB', '--demuxer-readahead-secs=' + str(cache)]
    if terminal_video:
        cmd.append('--vo=tct')
    for name, value in (headers or {}).items():
        if not isinstance(name, str) or not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9-]+', name) or '\n' in value or '\r' in value or ',' in value:
            continue
        cmd.append(f'--http-header-fields-append={name}: {value}')
    cmd.extend(['--', url])
    return cmd


def find_iina():
    if sys.platform != 'darwin': return None
    for candidate in (shutil.which('iina-cli'), shutil.which('iina'),
                      '/Applications/IINA.app/Contents/MacOS/iina-cli',
                      str(pathlib.Path.home() / 'Applications/IINA.app/Contents/MacOS/iina-cli')):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK): return candidate
    return None


def iina_command(executable, url, headers=None, *, cache=15):
    cmd = [executable, '--no-stdin', '--mpv-ytdl=no', '--mpv-force-media-title=Sports Live',
           '--mpv-cache=yes', f'--mpv-cache-secs={cache}', '--mpv-demuxer-max-bytes=256MiB',
           '--mpv-demuxer-lavf-o=allowed_extensions=ALL,allowed_segment_extensions=ALL,extension_picky=0']
    fields = []
    for name, value in (headers or {}).items():
        if isinstance(name, str) and isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9-]+', name) and not any(c in value for c in '\r\n,'):
            fields.append(f'{name}: {value}')
    if fields: cmd.append('--mpv-http-header-fields=' + ','.join(fields))
    cmd.append(url)
    return cmd


def find_celluloid():
    return shutil.which('celluloid') if sys.platform.startswith('linux') else None


def celluloid_command(executable, url, headers=None, *, cache=15):
    # Use a separate instance so each stream's mpv options and headers apply to
    # its own window even when the user already has Celluloid running.
    cmd = [executable, '--no-existing-session', '--mpv-ytdl=no',
           '--mpv-force-media-title=Sports Live', '--mpv-cache=yes',
           f'--mpv-cache-secs={cache}', '--mpv-demuxer-max-bytes=256MiB',
           '--mpv-demuxer-lavf-o=allowed_extensions=ALL,allowed_segment_extensions=ALL,extension_picky=0']
    fields = []
    for name, value in (headers or {}).items():
        # Celluloid internally wraps option values in single quotes and parses
        # backslash escapes. Reject values that could change that parsing.
        if (isinstance(name, str) and isinstance(value, str) and
                re.fullmatch(r'[A-Za-z0-9-]+', name) and not any(c in value for c in "\r\n,'\\")):
            fields.append(f'{name}: {value}')
    if fields: cmd.append('--mpv-http-header-fields=' + ','.join(fields))
    cmd.append(url)
    return cmd


def quick_probe_feed(feed):
    """Resolve a source and sample one segment without using shared player state."""
    temporary_relay = None
    try:
        if feed.kind == 'sf':
            url, headers = resolve_streamfree(feed, timeout=4)
        elif feed.kind == 'direct':
            url, headers = feed.url, feed.headers
        elif feed.kind == 'candidate':
            found = providers.extract_player(feed.url, max_pages=3,
                                             referer=feed.metadata.get('referer'), timeout=4)
            if found['kind'] == 'relay':
                temporary_relay = relay.Relay()
                url = temporary_relay.add(found['url'], found['edge'], found['channel'], found['referer'])
                headers = {}
            elif found['kind'] == 'sf':
                source = Feed(feed.source, feed.label, feed.side, found['url'], 'sf',
                              metadata={key:found[key] for key in ('key','quality','variant','category')})
                url, headers = resolve_streamfree(source, timeout=4)
            elif found['kind'] == 'direct':
                ref = found['referer']; parts = urllib.parse.urlsplit(ref)
                url = found['url']
                headers = {'Referer':ref, 'Origin':parts.scheme+'://'+parts.netloc, 'User-Agent':UA}
            else:
                return None
        else:
            return None
        grading.inspect_stream(url, headers, quick=True)
        return True
    finally:
        if temporary_relay: temporary_relay.close()


class App:
    def __init__(self, screen, config, *, ad_mute_enabled=False, ai_ad_mute_enabled=False):
        self.scr, self.config = screen, config
        self.games, self.all_games, self.feeds = [], [], []
        self.replays = []
        self.search_index = smart_search.default_index()
        self.search_query = ''
        self.search_plan = smart_search.make_plan(self.search_index, smart_search.parse_query(''))
        self.search_results = []
        self.search_position = 0
        self.search_touched = False
        self.search_return = None
        self.search_cache = {}
        self.search_needed = set()
        self.search_work = []
        self.search_inflight = set()
        self.search_queue = queue.Queue()
        self.search_jobs = queue.Queue()
        self.search_workers_started = False
        self.search_sources = {}
        self.search_due = None
        self.day = default_day()
        self.league = 'nba'
        self.league_index = 0
        self.league_return = 'games'
        self.league_cancel = None
        self.search = ''
        self.feed_search = ''
        self.replay_search = ''
        self.gi = self.fi = self.ri = 0
        self.mode = 'search'
        self.feed_context = 'live'
        self.feed_return = None
        self.current_replay = None
        self.help_return = 'games'
        self.help_scroll = 0
        self.live_color = 0
        self.loading_games = False
        self.filter = 'all'
        self.provider_filter = 'all'
        self.message = 'Start typing a team, matchup, or league.'
        self.errors = []
        self.feed_queue = queue.Queue()
        self.feed_generation = 0
        self.feed_sections = {}
        self.feed_order = []
        self.feed_pending = 0
        self.feed_selection_touched = False
        self.hidden_feeds = set()
        self.auto_checks = {}
        self.auto_queue = queue.Queue()
        self.auto_slots = threading.BoundedSemaphore(3)
        self.replay_queue = queue.Queue()
        self.replay_generation = 0
        self.replay_sections = {}
        self.replay_order = []
        self.replay_pending = 0
        self.replay_errors = []
        self.replay_selection_touched = False
        self.helper = None
        self.relay = None
        self.gui_players = []
        self.resolver_owned = False
        self.cache = int(config.get('cache', 15)) if str(config.get('cache', 15)) in ('5','15','30') else 15
        self.terminal_video = bool(config.get('terminal_video', False))
        self.ad_mute = ad_mute_enabled
        self.ai_ad_mute = ai_ad_mute_enabled
        self.player = config.get('player', 'mpv') if config.get('player', 'mpv') in ('mpv', 'iina', 'celluloid') else 'mpv'
        self.rank_by_checks = False

    def put(self, y, x, s, attr=0):
        h, w = self.scr.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        try:
            self.scr.addnstr(y, x, str(s), max(0, w-x-1), attr)
        except curses.error:
            pass

    def read_key(self):
        try:
            raw = self.scr.get_wch() if hasattr(self.scr, 'get_wch') else self.scr.getch()
        except curses.error:
            return -1, None
        if isinstance(raw, str):
            return ord(raw), raw if raw.isprintable() else None
        return raw, chr(raw) if 32 <= raw <= 126 else None

    def visible_feeds(self):
        side = self.games[self.gi].lakers_side if self.filter == 'lakers' and self.feed_context == 'live' else self.filter
        query = self.feed_search.casefold().strip()
        feeds = [f for f in self.feeds if id(f) not in self.hidden_feeds and (self.filter == 'all' or f.side == side)
                 and (self.provider_filter == 'all' or f.source == self.provider_filter)
                 and (not query or query in (f.source + ' ' + f.label).casefold())]
        if self.rank_by_checks:
            history = self.config.get('health') if isinstance(self.config.get('health'), dict) else {}
            feeds.sort(key=lambda feed: grading.score(history.get(grading.source_key(feed), {})), reverse=True)
        return feeds

    def render(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        self.put(0, 1, 'SPORTS LIVE', curses.A_BOLD)
        heading = {'search':'Find a game', 'leagues':'Choose a sport or league', 'games':'Games', 'replays':'Replays', 'feeds':'Broadcasts', 'help':'Help'}
        self.put(1, 1, heading.get(self.mode, ''), curses.A_BOLD)
        if h < 12 or w < 48:
            self.put(3, 1, 'Please enlarge your terminal to at least 48 x 12.')
            self.put(h-2, 1, 'Ctrl-X quit' if self.mode == 'search' else 'q quit')
            self.scr.refresh(); return
        if self.mode == 'search':
            self.put(2, 1, 'Search: ' + (self.search_query or '') + '_', curses.A_BOLD)
            rows = max(1, h-7)
            start = max(0, self.search_position-rows+1)
            for y, hit in enumerate(self.search_results[start:start+rows], 3):
                selected = start+y-3 == self.search_position
                badge = {'live':'LIVE', 'upcoming':'UPCOMING', 'replay':'REPLAY', 'team':'TEAM'}[hit.kind]
                league = LEAGUES.get(hit.league, (hit.league,))[0]
                extra = f'  |  {hit.item.source}' if hit.kind == 'replay' else ''
                attr = curses.A_REVERSE if selected else self.live_color if hit.kind == 'live' else 0
                self.put(y, 2, f'{">" if selected else " "} [{badge:8}] {hit.title}  |  {league}{extra}', attr)
            if not self.search_results:
                text = 'Try: lakers today  |  mavs vs rockets  |  tamu vs alabama' if not self.search_query else 'Looking for matches...' if self.search_inflight & self.search_needed else 'Keep typing a team or league.'
                self.put(4, 2, text)
            self.put(h-4, 1, 'Type to search   Up/Down select   Enter open')
            self.put(h-3, 1, 'Tab sports   Ctrl-U clear   ? help   Ctrl-X quit')
        elif self.mode == 'help':
            rows = max(1, h-6)
            for y, line in enumerate(HELP_LINES[self.help_scroll:self.help_scroll+rows], 3):
                self.put(y, 2, line)
            self.put(h-3, 1, 'j/k scroll   ? or Esc back   q quit')
        elif self.mode == 'leagues':
            keys = list(LEAGUES)
            rows = max(1, h-6)
            start = max(0, self.league_index-rows+1)
            for y, key in enumerate(keys[start:start+rows], 3):
                selected = start+y-3 == self.league_index
                self.put(y, 2, f'{">" if selected else " "} {LEAGUES[key][0]}', curses.A_REVERSE if selected else 0)
            self.put(h-3, 1, 'Enter select   Esc back   ? help   q quit')
        elif self.mode == 'games':
            self.put(2, 1, f'{LEAGUES[self.league][0]}  |  {self.day:%a %b %d} (ET date)  |  search: {self.search or "all"}')
            rows = max(1, h-7)
            start = max(0, self.gi-rows+1)
            for y, game in enumerate(self.games[start:start+rows], 3):
                selected = start+y-3 == self.gi
                when = game.start.astimezone().strftime('%a %b %d  %I:%M %p %Z')
                status = {'live':'LIVE', 'upcoming':'UPCOMING'}.get(game.state, '?')
                attr = curses.A_REVERSE if selected else self.live_color if game.state == 'live' else 0
                self.put(y, 2, f'{">" if selected else " "} [{status:8}] {when}  {game.title}', attr)
            if not self.games:
                self.put(4, 2, 'Loading schedule...' if self.loading_games else 'No upcoming or live games. Change date or search.')
            self.put(h-4, 1, 'Enter streams   R replays   s sport   [ ] date')
            self.put(h-3, 1, '/ search   l Lakers   r refresh   ? help   q quit')
        elif self.mode == 'replays':
            self.put(2, 1, f'{LEAGUES[self.league][0]}  |  recent replays  |  search: {self.replay_search or "all"}')
            rows = max(1, h-7)
            start = max(0, self.ri-rows+1)
            for y, item in enumerate(self.replays[start:start+rows], 3):
                selected = start+y-3 == self.ri
                self.put(y, 2, f'{">" if selected else " "} [{item.source}] {item.title}', curses.A_REVERSE if selected else 0)
            if not self.replays:
                self.put(4, 2, 'Searching replay catalogs...' if self.replay_pending else 'No replays found. Try another search or league.')
            self.put(h-4, 1, 'Enter servers   s sport   / search   r refresh')
            self.put(h-3, 1, 'R live games   ? help   q quit')
        else:
            if self.feed_context == 'replay':
                self.put(2, 1, self.current_replay.title)
                self.put(3, 1, f'Replay servers from {self.current_replay.source}')
            else:
                game = self.games[self.gi]
                self.put(2, 1, f'{game.title}  |  {game.start.astimezone().strftime("%a %b %d %I:%M %p %Z")}')
                self.put(3, 1, 'TV: ' + (', '.join(game.broadcasts) or 'not listed'))
            rank = '  |  ranked' if self.rank_by_checks else ''
            ad_mode = 'AI NBA' if self.ai_ad_mute else 'marked replays' if self.ad_mute else 'off'
            self.put(4, 1, f'{self.player.upper()}  |  side: {self.filter}  |  source: {self.provider_filter}  |  search: {self.feed_search or "all"}  |  cache: {self.cache}s  |  ad mute: {ad_mode}{rank}')
            fs = self.visible_feeds()
            self.fi = min(self.fi, max(0, len(fs)-1))
            name_width = max(14, min(50, w-40))
            self.put(5, 4, f'{"SOURCE / SERVER":<{name_width}}  {"SIDE":5} {"QUALITY":7} CHECK', curses.A_DIM)
            rows = max(1, (h-11)//2)
            start = max(0, self.fi-rows+1)
            for index, feed in enumerate(fs[start:start+rows]):
                y = 6 + index*2
                selected = start+index == self.fi
                history = self.config.get('health') if isinstance(self.config.get('health'), dict) else {}
                view = describe_feed(feed, history.get(grading.source_key(feed), {}), self.auto_checks.get(id(feed)))
                short_name = view.name if len(view.name) <= name_width else view.name[:name_width-1] + '…'
                attr = curses.A_REVERSE if selected else 0
                self.put(y, 2, f'{">" if selected else " "} {short_name:<{name_width}}  {view.side:5} {view.quality:7} {view.check}', attr)
                if y+1 < h-5:
                    fallback = {'ppv':'Uses local resolver', 'web':'Browser-only; no media URL'}.get(feed.kind, 'Direct stream')
                    detail = view.detail or fallback
                    if feed.kind == 'web' and view.detail: detail = fallback + ' | ' + view.detail
                    if short_name != view.name: detail = view.name + ' | ' + detail
                    self.put(y+1, 4, detail, attr if selected else curses.A_DIM)
            if not fs:
                self.put(6, 2, 'Looking for streams...' if self.feed_pending else 'No available feeds. Refresh near game time or change the filter.')
            self.put(h-5, 1, 'Enter play   / search   t test   g rank   o source')
            self.put(h-4, 1, 'f side   i inspect   p player   s sport   r refresh')
            self.put(h-3, 1, 'c cache   v video   u URL   ? help   Esc back   q quit')
        self.put(h-1, 1, self.message)
        self.scr.refresh()

    def refresh_games(self):
        selected_id = self.games[self.gi].id if self.games and self.gi < len(self.games) else None
        self.all_games = []; self.games = []; self.gi = 0; self.loading_games = True
        self.message = 'Loading games for this date...'; self.render()
        try:
            self.all_games = get_games(self.day, self.league); self.apply_search()
            if selected_id:
                self.gi = next((i for i, game in enumerate(self.games) if game.id == selected_id), 0)
            self.message = f'{len(self.games)} games shown. Select one.'
        except Exception as e:
            self.all_games = []; self.games = []; self.gi = 0
            self.message = f'Schedule unavailable: {type(e).__name__}. Press r to retry.'
        finally:
            self.loading_games = False

    def apply_search(self):
        query = self.search.lower()
        self.games = [g for g in self.all_games if query in (g.title + ' ' + g.home + ' ' + g.away).lower()]
        self.gi = min(self.gi, max(0, len(self.games)-1))

    def update_global_search(self):
        today = default_day()
        query = smart_search.parse_query(self.search_query, today)
        self.search_plan = smart_search.make_plan(self.search_index, query)
        query = self.search_plan.query
        work, sources = [], {}
        day = query.date or today
        if query.intent != 'replay' and day >= today:
            work.extend(('games', league, day) for league in self.search_plan.leagues)
        if query.intent != 'live':
            for league in self.search_plan.leagues:
                for spec in replays.catalogs(league):
                    key = ('replays', spec, '')
                    sources.setdefault(key, []).append(league)
                    if key not in work: work.append(key)
            # A specific matchup/date can require searching beyond the recent catalog.
            if (query.date or len(query.fragments) > 1) and self.search_plan.primary:
                term = smart_search.archive_search_term(self.search_plan.primary)
                for league in self.search_plan.leagues:
                    for spec in replays.catalogs(league):
                        host = urllib.parse.urlsplit(spec[1]).hostname
                        if host not in ('basketball-video.com','nfl-video.com','fullmatchshows.com','watchreplay.net'):
                            continue
                        key = ('replays', spec, term)
                        sources.setdefault(key, []).append(league)
                        if key not in work: work.append(key)
        self.search_sources = sources
        self.search_work = work
        self.search_needed = set(work)
        self.search_due = time.monotonic() + .2 if work else None
        self.search_position = 0; self.search_touched = False
        self.rebuild_global_results()

    def rebuild_global_results(self):
        selected = (self.search_results[self.search_position].key if self.search_touched
                    and self.search_position < len(self.search_results) else None)
        games, archived = [], []
        for key in self.search_work:
            cached = self.search_cache.get(key)
            if not cached or cached[2]: continue
            if key[0] == 'games': games.extend(cached[1])
            else:
                archived.extend((league, item) for league in self.search_sources.get(key, ()) for item in cached[1])
        self.search_results = smart_search.rank(self.search_index, self.search_plan, games, archived, default_day())
        keys = [item.key for item in self.search_results]
        if selected in keys:
            self.search_position = keys.index(selected)
        elif not self.search_touched:
            self.search_position = 0
        else:
            self.search_position = min(self.search_position, max(0, len(keys)-1))
        if self.mode != 'search': return
        pending = sum(1 for key in self.search_needed
                      if key in self.search_inflight or key not in self.search_cache)
        count = sum(item.kind != 'team' for item in self.search_results)
        if not self.search_query:
            self.message = 'Start typing a team, matchup, or league.'
        elif pending:
            self.message = f'{count} games and replays found | searching {pending} sources...'
        elif count:
            self.message = f'{count} games and replays found. Choose one or keep typing.'
        elif self.search_plan.leagues:
            self.message = 'No matching games or replays found. Try another team or date.'
        else:
            self.message = 'Keep typing a team, matchup, or league.'

    def start_global_search(self):
        if self.mode != 'search': return
        if self.search_due is None or time.monotonic() < self.search_due: return
        self.search_due = None
        if not self.search_workers_started:
            self.search_workers_started = True
            for _ in range(3):
                threading.Thread(target=self.global_search_worker, daemon=True).start()
        now = time.monotonic()
        for key in self.search_work:
            cached = self.search_cache.get(key)
            if key in self.search_inflight or (cached and cached[0] > now): continue
            self.search_inflight.add(key)
            self.search_jobs.put(key)
        self.rebuild_global_results()

    def global_search_worker(self):
        while True:
            key = self.search_jobs.get()
            if key is None: return
            if key not in self.search_needed:
                self.search_queue.put((key, None, None, True)); continue
            try:
                if key[0] == 'games': value = get_games(key[2], key[1])
                else: value = replays.listing(key[1], key[2])
                self.search_queue.put((key, value, None, False))
            except Exception as exc:
                self.search_queue.put((key, [], type(exc).__name__, False))

    def poll_global_search(self):
        changed = False
        while True:
            try: key, value, error, canceled = self.search_queue.get_nowait()
            except queue.Empty: break
            self.search_inflight.discard(key)
            if not canceled:
                ttl = 20 if error else 60 if key[0] == 'games' else 300
                self.search_cache[key] = (time.monotonic()+ttl, value, error)
                while len(self.search_cache) > 96:
                    self.search_cache.pop(next(iter(self.search_cache)))
            elif key in self.search_needed:
                self.search_due = time.monotonic()
            changed = True
        if changed: self.rebuild_global_results()
        return changed

    def open_global_result(self):
        if not self.search_results: return
        hit = self.search_results[self.search_position]
        if hit.kind == 'team':
            self.search_query = hit.item.display
            self.update_global_search()
            return
        self.league = hit.league
        self.search_return = None
        self.feed_return = 'search'
        self.filter = 'all'; self.provider_filter = 'all'; self.feed_search = ''
        if hit.kind == 'replay':
            self.current_replay = hit.item; self.feed_context = 'replay'
        else:
            self.games = [hit.item]; self.all_games = [hit.item]; self.gi = 0
            self.day = hit.date or self.day; self.feed_context = 'live'
        self.mode = 'feeds'; self.refresh_feeds()

    def refresh_replays(self):
        self.replay_generation += 1
        generation = self.replay_generation
        specs = replays.catalogs(self.league)
        self.replays = []; self.ri = 0; self.replay_sections = {}; self.replay_errors = []
        self.replay_order = [spec[0] for spec in specs]
        self.replay_pending = len(specs); self.replay_selection_touched = False
        self.message = 'Searching replay catalogs...' if specs else 'No replay catalog configured for this league.'
        for spec in specs:
            def worker(spec=spec, query=self.replay_search):
                try: self.replay_queue.put((generation, spec[0], replays.listing(spec, query), None))
                except Exception as exc: self.replay_queue.put((generation, spec[0], [], type(exc).__name__))
            threading.Thread(target=worker, daemon=True).start()

    def poll_replays(self):
        active = (self.mode == 'replays' or (self.mode == 'feeds' and self.feed_context == 'replay')
                  or (self.mode == 'leagues' and self.league_return == 'replays')
                  or (self.mode == 'search' and (self.search_return == 'replays'
                      or (self.search_return == 'feeds' and self.feed_context == 'replay')))
                  or (self.mode == 'help' and (self.help_return == 'replays'
                      or (self.help_return == 'feeds' and self.feed_context == 'replay')
                      or (self.help_return == 'leagues' and self.league_return == 'replays'))))
        changed = False
        while True:
            try: generation, name, items, error = self.replay_queue.get_nowait()
            except queue.Empty: break
            if generation != self.replay_generation or not active: continue
            selected = self.replays[self.ri] if self.replay_selection_touched and self.ri < len(self.replays) else None
            self.replay_sections[name] = items
            self.replay_pending = max(0, self.replay_pending-1)
            self.replays = [item for source in self.replay_order for item in self.replay_sections.get(source, [])]
            self.ri = self.replays.index(selected) if selected in self.replays else min(self.ri, max(0, len(self.replays)-1))
            if error: self.replay_errors.append(f'{name}: {error}')
            changed = True
        if changed and self.mode == 'replays':
            self.message = f'{len(self.replays)} replays found'
            if self.replay_pending: self.message += f' | checking {self.replay_pending} catalogs...'
            elif self.replay_errors: self.message += ' | ' + ', '.join(self.replay_errors)
        return changed

    def refresh_feeds(self):
        self.feed_generation += 1
        generation = self.feed_generation
        if self.feed_context == 'replay':
            item = self.current_replay
            def replay_servers():
                return [Feed(item.source, server.label, url=server.url, kind='candidate',
                             note='replay server; resolved when selected',
                             metadata={'referer':server.referer, 'provider':urllib.parse.urlsplit(server.url).hostname or ''})
                        for server in replays.servers(item)]
            tasks = [('Replay servers', replay_servers)]
        else:
            tasks = feed_tasks(self.games[self.gi], dict(self.config))
        self.feeds = []; self.errors = []; self.fi = 0
        self.hidden_feeds.clear()
        self.auto_checks.clear()
        self.feed_sections = {}; self.feed_order = [name for name, _ in tasks]
        self.feed_pending = len(tasks); self.feed_selection_touched = False
        self.message = 'Checking sources...'
        for name, operation in tasks:
            def worker(name=name, operation=operation):
                try:
                    self.feed_queue.put((generation, name, operation(), None))
                except Exception as exc:
                    self.feed_queue.put((generation, name, [], type(exc).__name__))
            threading.Thread(target=worker, daemon=True).start()

    def poll_feeds(self):
        active = (self.mode == 'feeds' or (self.mode == 'leagues' and self.league_cancel == 'feeds')
                  or (self.mode == 'search' and self.search_return == 'feeds')
                  or (self.mode == 'help' and (self.help_return == 'feeds'
                      or (self.help_return == 'leagues' and self.league_cancel == 'feeds'))))
        changed = False
        while True:
            try: generation, name, feeds, error = self.feed_queue.get_nowait()
            except queue.Empty: break
            if generation != self.feed_generation or not active: continue
            visible = self.visible_feeds()
            selected = visible[self.fi] if self.feed_selection_touched and self.fi < len(visible) else None
            self.feed_sections[name] = feeds
            self.feed_pending = max(0, self.feed_pending-1)
            if error: self.errors.append(f'{name}: {error}')
            self.feeds = [feed for source in self.feed_order for feed in self.feed_sections.get(source, [])]
            self.start_auto_checks(generation, feeds)
            visible = self.visible_feeds()
            if selected is not None and selected in visible:
                self.fi = visible.index(selected)
            else:
                self.fi = 0 if selected is None else min(self.fi, max(0, len(visible)-1))
            changed = True
        if changed and self.mode == 'feeds':
            self.message = f'{len(self.feeds)} choices found'
            if self.feed_pending: self.message += f' | checking {self.feed_pending} sources...'
            elif self.errors: self.message += ' | ' + ', '.join(self.errors)
        return changed

    def start_auto_checks(self, generation, feeds):
        for feed in [feed for feed in feeds if feed.kind in ('sf', 'direct', 'candidate')][:2]:
            self.auto_checks[id(feed)] = 'checking'
            def worker(feed=feed):
                with self.auto_slots:
                    if generation != self.feed_generation: return
                    try:
                        result = quick_probe_feed(feed)
                        status = 'OK' if result else '?'
                    except urllib.error.HTTPError as exc:
                        status = f'HTTP {exc.code}'
                    except Exception:
                        status = '?'
                    self.auto_queue.put((generation, feed, status))
            threading.Thread(target=worker, daemon=True).start()

    def poll_auto_checks(self):
        changed = False
        while True:
            try: generation, feed, status = self.auto_queue.get_nowait()
            except queue.Empty: break
            if generation != self.feed_generation or id(feed) not in self.auto_checks: continue
            self.auto_checks[id(feed)] = status
            changed = True
        return changed

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
            raise DependencyError('Set up the resolver and press d to select its folder; see README.')
        entry = pathlib.Path(directory).expanduser() / 'src/server.js'
        if not entry.is_file() or not (entry.parent.parent / 'node_modules').is_dir():
            raise DependencyError('Resolver or dependencies missing; see README.')
        if not shutil.which('node'):
            raise DependencyError('Node.js is required for the resolver.')
        env = os.environ.copy(); env.update({'HOST':'127.0.0.1', 'PORT':'38765', 'NODE_USE_ENV_PROXY':'1'})
        self.helper = subprocess.Popen(['node', str(entry.resolve())], cwd=str(entry.parent.parent), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.resolver_owned = True
        for _ in range(35):
            if self.helper.poll() is not None: raise DependencyError('Resolver failed to start; run npm install in its folder.')
            if self.helper_running(): return
            time.sleep(.1)
        raise DependencyError('Resolver did not start on localhost:38765.')

    def hide_feed(self, feed):
        self.hidden_feeds.add(id(feed))
        self.fi = min(self.fi, max(0, len(self.visible_feeds()) - 1))

    def resolve_feed(self, feed):
        url, headers = feed.url, feed.headers
        if feed.kind == 'candidate':
            found = providers.extract_player(feed.url, referer=feed.metadata.get('referer'))
            if found['kind'] == 'sf':
                feed = Feed(feed.source, feed.label, feed.side, found['url'], 'sf',
                            metadata={k:found[k] for k in ('key','quality','variant','category')})
            elif found['kind'] == 'ppv':
                feed = Feed(feed.source, feed.label, feed.side, found['url'], 'ppv')
            elif found['kind'] == 'relay':
                if self.relay is None: self.relay = relay.Relay()
                url = self.relay.add(found['url'],found['edge'],found['channel'],found['referer'])
                check_playlist(url)
                return url, {}
            else:
                referer = found['referer']
                p = urllib.parse.urlsplit(referer)
                headers = {'Referer':referer, 'Origin':p.scheme+'://'+p.netloc, 'User-Agent':UA}
                url = found['url']; check_playlist(url, headers)
                return url, headers
            url, headers = feed.url, feed.headers
        if feed.kind == 'sf':
            for attempt in range(2):
                try:
                    url, headers = resolve_streamfree(feed)
                    manifest = check_playlist(url, headers)
                    wrapped = streamfree_wraps_segments(url, manifest, headers)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code != 403 or attempt: raise
            if wrapped:
                if self.relay is None: self.relay = relay.Relay()
                url = self.relay.add_streamfree(url, headers['Referer'],
                                                lambda: resolve_streamfree(feed), manifest)
                check_playlist(url)
                return url, {}
        if feed.kind == 'ppv':
            self.ensure_helper()
            data = request(RESOLVER + '/api/embed', data={'iframe':feed.url}, timeout=35)
            url = data.get('proxiedUrl', '')
            if not data.get('ok') or not safe_url(url):
                raise RuntimeError(data.get('error', 'No playable URL returned'))
            u = urllib.parse.urlsplit(url)
            if u.hostname not in ('localhost','127.0.0.1') or u.port != 38765:
                raise RuntimeError('Unexpected resolver URL')
            headers = {}
            check_playlist(url)
        return url, headers

    def play(self, feed):
        if feed.kind == 'web':
            self.message = 'This add-on supplied a browser-only source.'; return
        if self.ai_ad_mute and self.player != 'mpv':
            self.message = 'AI ad mute requires mpv. Press p to switch players.'; return
        if self.ai_ad_mute and not ai_ad_mute.installed():
            self.message = 'AI detector not installed. Run ./sports_live --install-ad-model.'; return
        iina = find_iina() if self.player == 'iina' else None
        celluloid = find_celluloid() if self.player == 'celluloid' else None
        if self.player == 'iina' and not iina:
            self.message = 'IINA not found. Install it or press p to switch to mpv.'; return
        if self.player == 'celluloid' and not celluloid:
            self.message = 'Celluloid not found. Install it or press p to switch to mpv.'; return
        if self.player == 'mpv' and not shutil.which('mpv'):
            self.message = 'mpv is not installed or not on PATH.'; return
        self.message = 'Resolving selected stream...'; self.render()
        try:
            url, headers = self.resolve_feed(feed)
        except (OSError, ValueError, KeyError, RuntimeError) as e:
            if not isinstance(e, DependencyError):
                self.hide_feed(feed)
                self.message = f'Stream unavailable: {e}. Hidden until refresh.'
            else:
                self.message = str(e)
            return
        if self.player == 'iina':
            try:
                result = subprocess.run(iina_command(iina, url, headers, cache=self.cache),
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=10, check=False)
                self.message = ('Opened IINA. Keep this terminal open for local streams.' if result.returncode == 0
                                else f'IINA could not start (status {result.returncode}).')
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.message = f'Could not start IINA: {type(exc).__name__}'
            return
        if self.player == 'celluloid':
            try:
                process = subprocess.Popen(celluloid_command(celluloid, url, headers, cache=self.cache),
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, start_new_session=True)
                self.gui_players.append(process)
                self.message = 'Launched Celluloid. Keep this terminal open for local streams.'
            except OSError as exc:
                self.message = f'Could not start Celluloid: {type(exc).__name__}'
            return
        intervals, ad_note = [], ''
        if self.ad_mute:
            if self.feed_context == 'replay':
                self.message = 'Checking replay for explicit ad markers...'; self.render()
                try:
                    intervals = ad_mute.marked_replay_intervals(url, headers)
                except (OSError, ValueError, TypeError):
                    pass
                if not intervals: ad_note = ' No marked ads found; ad mute was inactive.'
            else:
                ad_note = ' Ad mute is available only for marked replays.'
        ai_active = self.ai_ad_mute and self.league == 'nba'
        if self.ai_ad_mute and not ai_active:
            ad_note = ' AI ad mute is currently limited to NBA broadcasts.'
        temporary, monitor = None, None
        command = mpv_command(url, headers, cache=self.cache, terminal_video=self.terminal_video)
        if intervals or ai_active:
            try:
                temporary = tempfile.TemporaryDirectory(prefix='sports-mpv-', dir='/tmp')
                socket_path = os.path.join(temporary.name, 'mpv.sock')
                monitor = ai_ad_mute.Monitor(socket_path, temporary.name) if ai_active else ad_mute.Monitor(socket_path, intervals)
                monitor.start()
                command.insert(1, '--input-ipc-server=' + socket_path)
            except OSError:
                if temporary: temporary.cleanup(); temporary = None
                ad_note = ' Ad mute could not start.'
        self.message = 'Starting mpv. Press q in mpv to return.' + ad_note; self.render()
        curses.def_prog_mode(); curses.endwin()
        try:
            result = subprocess.run(command, check=False)
            if result.returncode == 0:
                self.message = 'Returned from mpv.' + ad_note
            else:
                self.hide_feed(feed)
                self.message = f'mpv exited with status {result.returncode}; feed hidden until refresh.'
        except OSError as e:
            self.message = f'Could not start mpv: {e}'
        finally:
            if monitor: monitor.stop()
            if temporary: temporary.cleanup()
            curses.reset_prog_mode(); self.scr.refresh()

    def test_feed(self, feed):
        if feed.kind == 'web':
            self.message = 'This source has no playable media URL.'; return
        self.message = 'Testing source and measuring quality...'; self.render()
        result = {}; error = None
        try:
            url, headers = self.resolve_feed(feed)
            result = grading.inspect_stream(url, headers)
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            error = exc
        history = self.config.get('health')
        if not isinstance(history, dict): history = {}; self.config['health'] = history
        key = grading.source_key(feed)
        record = history.get(key)
        if not isinstance(record, dict): record = {}; history[key] = record
        checks = record.get('checks') if isinstance(record.get('checks'), list) else []
        if isinstance(error, DependencyError):
            self.message = str(error)
            return
        record['checks'] = (checks + [error is None])[-20:]
        if error is None: record['latency_ms'] = result['latency_ms']
        if result.get('height'): record['height'] = result['height']
        save_config(self.config)
        visible = self.visible_feeds()
        if feed in visible: self.fi = visible.index(feed)
        label = grading.summary(record)
        if error:
            self.hide_feed(feed)
            self.message = f'Test failed ({str(error) or type(error).__name__}); hidden until refresh. | {label}'
        else:
            self.message = f'Segment reachable in {record["latency_ms"]} ms | {label}'

    def close(self):
        if self.search_workers_started:
            for _ in range(3): self.search_jobs.put(None)
        if self.relay: self.relay.close()
        if self.resolver_owned and self.helper and self.helper.poll() is None:
            self.helper.terminate()
            try: self.helper.wait(timeout=3)
            except subprocess.TimeoutExpired: self.helper.kill(); self.helper.wait()

    def poll_gui_players(self):
        running = []
        for process in self.gui_players:
            status = process.poll()
            if status is None: running.append(process)
            elif status: self.message = f'Celluloid exited with status {status}.'
        self.gui_players = running

    def run(self):
        try:
            curses.curs_set(0)
            if curses.has_colors():
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_GREEN, -1)
                self.live_color = curses.color_pair(1) | curses.A_BOLD
        except curses.error: pass
        self.scr.keypad(True)
        self.scr.timeout(150)
        if self.mode == 'games': self.refresh_games()
        try:
            while True:
                self.poll_global_search(); self.start_global_search()
                self.poll_replays(); self.poll_feeds(); self.poll_auto_checks(); self.poll_gui_players(); self.render(); key, typed = self.read_key()
                if key == -1: continue
                if self.mode == 'search':
                    if key in (17, 24): break  # Ctrl-Q or Ctrl-X
                    if key == ord('?'):
                        self.help_return = 'search'; self.help_scroll = 0; self.mode = 'help'
                        self.message = 'Controls and setup.'
                    elif key in (curses.KEY_UP, 16):
                        self.search_position = max(0, self.search_position-1); self.search_touched = True
                    elif key in (curses.KEY_DOWN, 14):
                        self.search_position = min(max(0, len(self.search_results)-1), self.search_position+1); self.search_touched = True
                    elif key in (10, 13, curses.KEY_ENTER):
                        self.open_global_result()
                    elif key in (9, 27):
                        if key == 27 and self.search_return:
                            self.mode = self.search_return; self.search_return = None; self.message = 'Returned to list.'
                        else:
                            self.league_index = list(LEAGUES).index(self.league)
                            self.league_cancel = 'search'; self.league_return = 'games'
                            self.mode = 'leagues'; self.message = 'Choose a sport or league.'
                    elif key in (curses.KEY_BACKSPACE, 127, 8):
                        self.search_query = self.search_query[:-1]; self.update_global_search()
                    elif key == 21:  # Ctrl-U
                        self.search_query = ''; self.update_global_search()
                    elif key == 18:  # Ctrl-R
                        for work in self.search_needed: self.search_cache.pop(work, None)
                        self.search_due = time.monotonic(); self.rebuild_global_results()
                    elif typed:
                        self.search_query += typed; self.update_global_search()
                    continue
                if key == 6:  # Ctrl-F searches from any view.
                    self.search_return = self.mode; self.mode = 'search'; self.update_global_search()
                    continue
                if key in (ord('q'),): break
                if self.mode == 'help':
                    if key in (ord('?'), 27, curses.KEY_BACKSPACE, 127, ord('h')):
                        self.mode = self.help_return; self.message = 'Returned to list.'
                    elif key in (curses.KEY_UP, ord('k')): self.help_scroll = max(0, self.help_scroll-1)
                    elif key in (curses.KEY_DOWN, ord('j')): self.help_scroll = min(len(HELP_LINES)-1, self.help_scroll+1)
                    continue
                if key == ord('?'):
                    self.help_return = self.mode; self.help_scroll = 0; self.mode = 'help'
                    self.message = 'Controls and setup.'
                    continue
                if key in (curses.KEY_UP, ord('k')):
                    if self.mode == 'leagues': self.league_index = max(0, self.league_index-1)
                    elif self.mode == 'games': self.gi = max(0, self.gi-1)
                    elif self.mode == 'replays': self.ri = max(0, self.ri-1); self.replay_selection_touched = True
                    else: self.fi = max(0, self.fi-1); self.feed_selection_touched = True
                elif key in (curses.KEY_DOWN, ord('j')):
                    if self.mode == 'leagues': self.league_index = min(len(LEAGUES)-1, self.league_index+1)
                    elif self.mode == 'games': self.gi = min(max(0,len(self.games)-1), self.gi+1)
                    elif self.mode == 'replays': self.ri = min(max(0,len(self.replays)-1), self.ri+1); self.replay_selection_touched = True
                    else: self.fi = min(max(0,len(self.visible_feeds())-1), self.fi+1); self.feed_selection_touched = True
                elif key in (10,13,curses.KEY_ENTER):
                    if self.mode == 'leagues':
                        self.league = list(LEAGUES)[self.league_index]
                        if self.league_cancel == 'feeds':
                            self.feed_generation += 1; self.feed_pending = 0
                        self.search = ''; self.gi = 0; self.mode = self.league_return
                        if self.mode == 'replays': self.replay_search = ''; self.refresh_replays()
                        else: self.refresh_games()
                    elif self.mode == 'games' and self.games:
                        self.feed_return = None; self.feed_context = 'live'; self.mode = 'feeds'; self.filter = 'all'
                        self.provider_filter = 'all'; self.feed_search = ''; self.refresh_feeds()
                    elif self.mode == 'replays' and self.replays:
                        self.current_replay = self.replays[self.ri]; self.replay_selection_touched = True
                        self.feed_return = None; self.feed_context = 'replay'; self.mode = 'feeds'; self.filter = 'all'
                        self.provider_filter = 'all'; self.feed_search = ''; self.refresh_feeds()
                    elif self.mode == 'feeds' and self.visible_feeds():
                        self.feed_selection_touched = True; self.play(self.visible_feeds()[self.fi])
                elif key in (27, curses.KEY_BACKSPACE, 127, ord('h')) and self.mode == 'feeds':
                    self.feed_generation += 1; self.feed_pending = 0
                    if self.feed_return == 'search':
                        self.feed_return = None; self.mode = 'search'; self.rebuild_global_results()
                    else:
                        self.mode = 'replays' if self.feed_context == 'replay' else 'games'
                        self.message = 'Select a replay.' if self.mode == 'replays' else 'Select a game.'
                elif key in (27, curses.KEY_BACKSPACE, 127, ord('h')) and self.mode == 'leagues':
                    if self.league_cancel is None:
                        self.message = 'Choose a sport or press q to quit.'
                    else:
                        self.mode = self.league_cancel; self.message = 'Returned to list.'
                elif key in (27, curses.KEY_BACKSPACE, 127, ord('h'), ord('R')) and self.mode == 'replays':
                    self.replay_generation += 1; self.replay_pending = 0
                    self.mode = 'games'; self.refresh_games()
                elif self.mode in ('games', 'replays', 'feeds') and key in (ord('s'), ord('S')):
                    self.league_index = list(LEAGUES).index(self.league)
                    self.league_cancel = self.mode
                    self.league_return = 'replays' if (self.mode == 'replays' or
                        (self.mode == 'feeds' and self.feed_context == 'replay')) else 'games'
                    self.mode = 'leagues'; self.message = 'Choose a sport or league.'
                elif self.mode == 'games' and key == ord('R'):
                    self.mode = 'replays'; self.replay_search = ''; self.refresh_replays()
                elif self.mode in ('games', 'feeds', 'replays') and key == ord('r'):
                    if self.mode == 'games': self.refresh_games()
                    elif self.mode == 'replays': self.refresh_replays()
                    else: self.refresh_feeds()
                elif self.mode == 'games' and key in (ord('['), ord(']')):
                    self.day += dt.timedelta(days=-1 if key == ord('[') else 1); self.gi = 0; self.refresh_games()
                elif self.mode in ('games', 'replays') and key == ord('/'):
                    self.search_return = self.mode; self.mode = 'search'; self.search_query = ''; self.update_global_search()
                elif self.mode == 'games' and key == ord('l') and self.league == 'nba':
                    self.search = '' if self.search.casefold() == 'lakers' else 'Lakers'
                    self.apply_search(); self.message = f'{len(self.games)} games shown.'
                elif key == ord('a'): self.configure_addon()
                elif key == ord('d'): self.configure_resolver()
                elif self.mode == 'feeds' and key == ord('f') and self.feed_context == 'live':
                    filters = ['all','home','away','unknown'];
                    if self.games[self.gi].lakers_side: filters.insert(1, 'lakers')
                    self.filter = filters[(filters.index(self.filter)+1)%len(filters)]; self.fi=0; self.feed_selection_touched=True
                elif self.mode == 'feeds' and key == ord('o'):
                    names = ['all'] + list(dict.fromkeys(f.source for f in self.feeds if id(f) not in self.hidden_feeds))
                    if self.provider_filter in names:
                        self.provider_filter = names[(names.index(self.provider_filter)+1)%len(names)]
                    else:
                        self.provider_filter = 'all'
                    self.fi = 0; self.feed_selection_touched = True
                    self.message = f'Source: {self.provider_filter}.'
                elif self.mode == 'feeds' and key == ord('/'):
                    self.feed_search = self.prompt('Search providers or channels (blank clears):')
                    self.fi = 0; self.feed_selection_touched = True
                    self.message = f'{len(self.visible_feeds())} matching choices.'
                elif self.mode == 'feeds' and key == ord('t') and self.visible_feeds():
                    self.feed_selection_touched = True; self.test_feed(self.visible_feeds()[self.fi])
                elif self.mode == 'feeds' and key == ord('g'):
                    visible = self.visible_feeds()
                    selected = visible[self.fi] if self.fi < len(visible) else None
                    self.rank_by_checks = not self.rank_by_checks
                    visible = self.visible_feeds()
                    self.fi = visible.index(selected) if selected in visible else 0
                    self.feed_selection_touched = True
                    self.message = 'Ranked by your checks.' if self.rank_by_checks else 'Directory order.'
                elif self.mode == 'feeds' and key == ord('i') and self.visible_feeds():
                    feed = self.visible_feeds()[self.fi]
                    self.message = 'Resolving selected stream...'; self.render()
                    try:
                        if feed.kind == 'web': raise ValueError('No media URL for this source')
                        url, headers = self.resolve_feed(feed)
                        curses.def_prog_mode(); curses.endwin()
                        try:
                            print('\nMedia URL (may expire; localhost links need this app open):\n'+url)
                            for name, value in headers.items(): print(name+': '+value)
                            input('\nPress Enter to return...')
                        finally:
                            curses.reset_prog_mode(); self.scr.clear(); self.scr.refresh()
                        self.message = 'Stream link shown.'
                    except (OSError, ValueError, KeyError, RuntimeError) as e:
                        self.message = f'Stream unavailable: {e}'
                elif self.mode == 'feeds' and key == ord('c'):
                    self.cache = {5:15,15:30,30:5}[self.cache]; self.config['cache']=self.cache; save_config(self.config)
                elif self.mode == 'feeds' and key == ord('v'):
                    if self.player != 'mpv':
                        self.message = 'Switch to mpv for terminal video.'
                    else:
                        self.terminal_video = not self.terminal_video; self.config['terminal_video']=self.terminal_video; save_config(self.config)
                        self.message = 'Terminal video enabled.' if self.terminal_video else 'Window video enabled.'
                elif self.mode == 'feeds' and key == ord('p'):
                    if self.player != 'mpv':
                        self.player = 'mpv'
                    elif sys.platform == 'darwin' and find_iina():
                        self.player = 'iina'
                    elif sys.platform.startswith('linux') and find_celluloid():
                        self.player = 'celluloid'
                    elif sys.platform == 'darwin':
                        self.message = 'IINA not found. Install it with: brew install --cask iina'
                        continue
                    elif sys.platform.startswith('linux'):
                        self.message = 'Celluloid not found. Install it with your package manager.'
                        continue
                    else:
                        self.message = 'No alternate player configured on this platform.'
                        continue
                    self.config['player'] = self.player; save_config(self.config)
                    self.message = f'Player: {self.player.upper()}.'
                elif self.mode == 'feeds' and key == ord('u'):
                    value = self.prompt('Direct media URL:')
                    if safe_url(value): self.play(Feed('Manual','Pasted URL',url=value,kind='direct'))
                    else: self.message = 'Enter a valid HTTP(S) media URL.'
        finally:
            self.close()


def main():
    parser = argparse.ArgumentParser(description='Browse sports games and choose streams.')
    parser.add_argument('--list', action='store_true', help='Print upcoming games and feed listings without a terminal UI')
    parser.add_argument('--date', help='Schedule date in YYYY-MM-DD (Eastern time)')
    parser.add_argument('--league', choices=LEAGUES, help='Open a league directly (default: search in the app; nba for --list)')
    parser.add_argument('--addon', help='Stremio sports add-on manifest URL for this run')
    parser.add_argument('--resolver-dir', help='Local ppv-hls-proxy checkout for this run')
    mute = parser.add_mutually_exclusive_group()
    mute.add_argument('--ad-mute', action='store_true', help='Mute explicitly marked replay ad breaks in mpv for this run')
    mute.add_argument('--ai-ad-mute', action='store_true', help='Use the optional experimental local NBA ad detector in mpv')
    parser.add_argument('--install-ad-model', action='store_true', help='Explicitly download and install the optional local NBA ad detector')
    args = parser.parse_args(); config = load_config()
    if args.install_ad_model: return ai_ad_mute.install()
    if args.ai_ad_mute and not ai_ad_mute.installed():
        print('AI ad detector not installed. Run ./sports_live --install-ad-model first.', file=sys.stderr)
        return 2
    if args.addon: config['addon'] = args.addon
    if args.resolver_dir: config['resolver_dir'] = args.resolver_dir
    if args.list:
        try:
            league = args.league or 'nba'
            day = dt.date.fromisoformat(args.date) if args.date else default_day()
            games = get_games(day, league)
            if not games: print(f'No live or upcoming {LEAGUES[league][0]} games found for that date.'); return 0
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
            app = App(screen, config, ad_mute_enabled=args.ad_mute, ai_ad_mute_enabled=args.ai_ad_mute)
            if args.league:
                app.league = args.league
                app.league_index = list(LEAGUES).index(args.league)
                app.mode = 'games'
            if args.date: app.day = dt.date.fromisoformat(args.date)
            app.run()
        curses.wrapper(run_ui)
    except KeyboardInterrupt:
        pass
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
