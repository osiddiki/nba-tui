"""Fast local intent parsing, team autocomplete and sports-event ranking."""
from __future__ import annotations

import datetime as dt
import difflib
import functools
import json
import pathlib
import re
import unicodedata
from dataclasses import dataclass
from zoneinfo import ZoneInfo


INDEX_PATH = pathlib.Path(__file__).resolve().parent / 'data' / 'teams.json'
LEAGUE_ORDER = ('nba','wnba','nfl','ncaaf','ncaam','ncaaw','mlb','nhl',
                'mls','epl','laliga','bundesliga','seriea','ligue1','ligamx','ucl')
LEAGUE_PRIORITY = {league: index for index, league in enumerate(LEAGUE_ORDER)}
ALIASES = {
    ('nba', 'Dallas Mavericks'): ('mavs', 'dallas mavs'),
    ('nba', 'Golden State Warriors'): ('dubs', 'gsw'),
    ('nba', 'Philadelphia 76ers'): ('sixers', 'philly', 'philly sixers'),
    ('nba', 'Portland Trail Blazers'): ('blazers', 'portland blazers'),
    ('nba', 'Minnesota Timberwolves'): ('wolves', 'twolves'),
    ('nba', 'LA Clippers'): ('clips',),
    ('nba', 'New Orleans Pelicans'): ('pels',),
    ('nfl', 'San Francisco 49ers'): ('niners',),
    ('nfl', 'New England Patriots'): ('pats',),
    ('nfl', 'Tampa Bay Buccaneers'): ('bucs',),
    ('nfl', 'Jacksonville Jaguars'): ('jags',),
    ('nfl', 'Philadelphia Eagles'): ('birds',),
}
MONTHS = {name: number for number, names in enumerate(((),
    ('jan','january'),('feb','february'),('mar','march'),('apr','april'),('may',),
    ('jun','june'),('jul','july'),('aug','august'),('sep','sept','september'),
    ('oct','october'),('nov','november'),('dec','december'))) for name in names}
MONTH_PATTERN = '|'.join(sorted(MONTHS, key=len, reverse=True))
STOP_WORDS = {'show','me','watch','find','get','the','a','an','please','game','games',
              'match','matches','stream','streams','broadcast','broadcasts','sports',
              'full','recent','latest','last','on','for','from','of','live','now',
              'tonight','today','yesterday','tomorrow','replay','replays','vod'}
LEAGUE_TERMS = (
    (r'\bcollege\s+football\b|\bncaaf\b|\bcfb\b', 'ncaaf'),
    (r'\bwnba\b', 'wnba'), (r'\bnba\b', 'nba'), (r'\bnfl\b', 'nfl'),
    (r'\bncaam\b', 'ncaam'), (r'\bncaaw\b', 'ncaaw'),
    (r'\bmlb\b', 'mlb'), (r'\bnhl\b', 'nhl'), (r'\bmls\b', 'mls'),
    (r'\bpremier\s+league\b|\bepl\b', 'epl'), (r'\bla\s+liga\b', 'laliga'),
    (r'\bbundesliga\b', 'bundesliga'), (r'\bserie\s+a\b', 'seriea'),
    (r'\bligue\s+1\b', 'ligue1'), (r'\bliga\s+mx\b', 'ligamx'),
    (r'\bchampions\s+league\b|\bucl\b', 'ucl'),
)


def normalize(text):
    text = unicodedata.normalize('NFKD', str(text).casefold().replace('&', ' and '))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def _date(year, month, day, today):
    if year is not None:
        try: return dt.date(year, month, day)
        except ValueError: return None
    candidates = []
    for candidate_year in (today.year-1, today.year, today.year+1):
        try: candidates.append(dt.date(candidate_year, month, day))
        except ValueError: pass
    return min(candidates, key=lambda value: abs((value-today).days)) if candidates else None


@dataclass(frozen=True)
class Query:
    text: str
    fragments: tuple[str, ...]
    date: dt.date | None = None
    intent: str = 'both'
    league: str | None = None


def parse_query(text, today=None):
    today = today or dt.datetime.now(ZoneInfo('America/New_York')).date()
    remaining = str(text).casefold()
    intent = 'replay' if re.search(r'\b(?:replays?|vod|yesterday|last\s+night|last\s+games?)\b', remaining) else 'both'
    if intent == 'both' and re.search(r'\b(?:live|now|tonight|today|tomorrow)\b', remaining):
        intent = 'live'
    selected_date = None
    relative = re.search(r'\b(today|tonight|yesterday|tomorrow)\b', remaining)
    if relative:
        offset = {'today':0, 'tonight':0, 'yesterday':-1, 'tomorrow':1}[relative.group(1)]
        selected_date = today + dt.timedelta(days=offset)
        remaining = remaining[:relative.start()] + ' ' + remaining[relative.end():]
    elif re.search(r'\blast\s+night\b', remaining):
        selected_date = today - dt.timedelta(days=1)
        remaining = re.sub(r'\blast\s+night\b', ' ', remaining)
    patterns = [
        (r'(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)', 'iso'),
        (r'(?<!\d)(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?!\d)', 'numeric'),
        (rf'\b({MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b', 'month'),
        (rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_PATTERN})\.?(?:,?\s+(\d{{4}}))?\b', 'day'),
    ]
    for pattern, kind in patterns:
        match = re.search(pattern, remaining, re.I)
        if not match: continue
        if kind == 'iso': year, month, day = map(int, match.groups())
        elif kind == 'numeric':
            month, day = map(int, match.groups()[:2]); year = int(match.group(3)) if match.group(3) else None
            if year is not None and year < 100: year += 2000
        elif kind == 'month':
            month = MONTHS[match.group(1).lower()]; day = int(match.group(2)); year = int(match.group(3)) if match.group(3) else None
        else:
            day = int(match.group(1)); month = MONTHS[match.group(2).lower()]; year = int(match.group(3)) if match.group(3) else None
        parsed = _date(year, month, day, today)
        if parsed is not None:
            selected_date = parsed
            remaining = remaining[:match.start()] + ' ' + remaining[match.end():]
        break
    league = None
    for pattern, candidate in LEAGUE_TERMS:
        if re.search(pattern, remaining, re.I):
            league = candidate; remaining = re.sub(pattern, ' ', remaining, flags=re.I); break
    parts = re.split(r'\s+(?:vs?\.?|versus|against|at)\s*|\s*@\s*', remaining, maxsplit=1)
    fragments = []
    for part in parts:
        words = [word for word in normalize(part).split() if word not in STOP_WORDS]
        if words: fragments.append(' '.join(words))
    # Keep the first team's results while the second name is only one letter.
    if len(fragments) > 1 and len(fragments[-1]) < 2:
        fragments.pop()
    return Query(str(text), tuple(fragments), selected_date, intent, league)


@dataclass(frozen=True)
class Team:
    league: str
    id: str
    display: str
    location: str
    nickname: str
    short: str
    abbreviation: str
    aliases: tuple[str, ...]


class TeamIndex:
    def __init__(self, data):
        self.teams = []
        self.prefixes = {}
        self.second_prefixes = {}
        for league, rows in data.get('leagues', {}).items():
            for row in rows:
                if not isinstance(row, list) or len(row) != 6: continue
                ident, display, location, nickname, short, abbreviation = row
                values = [display, location, nickname, short, abbreviation]
                values.extend(ALIASES.get((league, display), ()))
                if ident == '245' and league in ('ncaaf','ncaam','ncaaw'):
                    values.extend(('tamu','texas am','texas a m','texas a and m'))
                aliases = tuple(dict.fromkeys(value for value in map(normalize, values) if len(value) >= 3))
                team = Team(league, ident, display, location, nickname, short, abbreviation, aliases)
                number = len(self.teams); self.teams.append(team)
                prefixes = {word[:2] for alias in aliases for word in alias.split() if len(word) >= 2}
                for prefix in prefixes: self.prefixes.setdefault(prefix, set()).add(number)
                second = {word[1:3] for alias in aliases for word in alias.split() if len(word) >= 4}
                for prefix in second: self.second_prefixes.setdefault(prefix, set()).add(number)

    @classmethod
    def load(cls, path=INDEX_PATH):
        try:
            data = json.loads(pathlib.Path(path).read_text(encoding='utf8'))
            if not isinstance(data, dict): data = {}
        except (OSError, ValueError): data = {}
        return cls(data)

    @functools.lru_cache(maxsize=512)
    def resolve(self, fragment):
        fragment = normalize(fragment)
        if len(fragment) < 2: return ()
        candidates = self.prefixes.get(fragment[:2], set())
        if len(fragment) >= 4:
            candidates = candidates | self.second_prefixes.get(fragment[1:3], set())
        found = []
        for number in candidates:
            team = self.teams[number]
            best = 0.0
            for alias in team.aliases:
                if fragment == alias: score = 1.0
                elif alias.startswith(fragment) or any(word.startswith(fragment) for word in alias.split()):
                    score = .9 if len(fragment) <= 3 else .85 + .12 * min(1, len(fragment)/len(alias))
                elif len(fragment) >= 4 and abs(len(fragment)-len(alias)) <= max(3, len(fragment)//3):
                    ratio = difflib.SequenceMatcher(None, fragment, alias).ratio()
                    score = .65 + ratio*.2 if ratio >= .74 else 0.0
                else: score = 0.0
                best = max(best, score)
            if best >= .79: found.append((team, best))
        found.sort(key=lambda item: (-item[1], LEAGUE_PRIORITY.get(item[0].league, 99), item[0].display))
        return tuple(found[:120])


@functools.lru_cache(maxsize=1)
def default_index():
    return TeamIndex.load()


@dataclass(frozen=True)
class Plan:
    query: Query
    leagues: tuple[str, ...]
    primary: Team | None


def make_plan(index, query, limit=3):
    if len(query.fragments) == 1:
        fragment = query.fragments[0]
        whole = index.resolve(fragment)
        if not whole or whole[0][1] < .99:
            words = fragment.split()
            for position in range(1, len(words)):
                left, right = ' '.join(words[:position]), ' '.join(words[position:])
                first = [team for team, score in index.resolve(left) if score >= .99]
                second = [team for team, score in index.resolve(right) if score >= .99]
                if any(a.league == b.league and a.id != b.id for a in first for b in second):
                    query = Query(query.text, (left, right), query.date, query.intent, query.league)
                    break
    resolved = [index.resolve(fragment) for fragment in query.fragments]
    usable = [items for items in resolved if items]
    primary = usable[0][0][0] if usable else None
    if query.league:
        primary = next((team for items in usable for team, _ in items if team.league == query.league), None)
        return Plan(query, (query.league,), primary)
    if not usable:
        return Plan(query, (), primary)
    weights = {}
    for items in usable:
        by_league = {}
        for team, score in items:
            by_league[team.league] = max(by_league.get(team.league, 0.0), score)
        if not weights: weights = by_league
        else: weights = {league: score + by_league[league] for league, score in weights.items() if league in by_league}
    if not weights:
        for team, score in usable[0]: weights[team.league] = max(weights.get(team.league, 0.0), score)
    best = max(weights.values())
    weights = {league: score for league, score in weights.items() if score >= best-.08}
    ordered = sorted(weights, key=lambda league: (-weights[league], LEAGUE_PRIORITY.get(league, 99)))
    return Plan(query, tuple(ordered[:limit]), primary)


def replay_date(title, today=None):
    return parse_query(title, today=today).date


def _fragment_matches(index, fragment, league, title):
    normalized = ' ' + normalize(title) + ' '
    found = []
    for team, score in index.resolve(fragment):
        if team.league != league: continue
        for alias in team.aliases:
            position = normalized.find(' ' + alias + ' ')
            if position >= 0:
                found.append((score, (position, position+len(alias)+2)))
                break
    if not found and len(fragment) >= 2:
        for match in re.finditer(r'\b' + re.escape(fragment) + r'\w*\b', normalized):
            found.append((.8, match.span()))
    return found


def _match(index, query, league, title):
    if not query.fragments: return 1.0
    matches = [_fragment_matches(index, fragment, league, title) for fragment in query.fragments]
    if any(not part for part in matches): return 0.0
    if len(matches) == 1: return max(score for score, _ in matches[0])
    return max((a[0]+b[0])/2 for a in matches[0] for b in matches[1]
               if a[1][1] <= b[1][0] or b[1][1] <= a[1][0]) if any(
                   a[1][1] <= b[1][0] or b[1][1] <= a[1][0]
                   for a in matches[0] for b in matches[1]) else 0.0


@dataclass(frozen=True)
class Hit:
    kind: str
    league: str
    title: str
    item: object
    score: float = 0.0
    date: dt.date | None = None

    @property
    def key(self):
        if self.kind == 'team': return ('team', self.item.league, self.item.id)
        if self.kind == 'replay': return ('replay', self.item.url)
        return ('game', self.league, self.item.id)


def rank(index, plan, games, archived, today=None, limit=50):
    query = plan.query
    today = today or dt.datetime.now(ZoneInfo('America/New_York')).date()
    hits, seen = [], set()
    for game in games:
        if game.league not in plan.leagues or query.intent == 'replay': continue
        date = game.start.astimezone(ZoneInfo('America/New_York')).date()
        if query.date and date != query.date: continue
        score = _match(index, query, game.league, game.title)
        if score:
            hit = Hit('live' if game.state == 'live' else 'upcoming', game.league, game.title, game, score, date)
            if hit.key not in seen: hits.append(hit); seen.add(hit.key)
    for league, item in archived:
        if league not in plan.leagues or query.intent == 'live': continue
        date = replay_date(item.title, today)
        if query.date and date != query.date: continue
        score = _match(index, query, league, item.title)
        if score:
            hit = Hit('replay', league, item.title, item, score, date)
            if hit.key not in seen: hits.append(hit); seen.add(hit.key)
    group = {'live':0, 'upcoming':1, 'replay':2, 'team':3}
    hits.sort(key=lambda hit: (group[hit.kind], -hit.score,
                               -(hit.date.toordinal() if hit.kind == 'replay' and hit.date else 0), hit.title))
    if len(query.fragments) == 1 and query.date is None:
        matches = index.resolve(query.fragments[0])
        top = matches[0][1] if matches else 0
        for team, score in matches:
            if score < top-.08: break
            if query.league and team.league != query.league: continue
            hit = Hit('team', team.league, team.display, team, score)
            if hit.key not in seen: hits.append(hit); seen.add(hit.key)
            if sum(item.kind == 'team' for item in hits) >= 8: break
    return hits[:limit]


def archive_search_term(team):
    if team is None: return ''
    if team.league in ('ncaaf','ncaam','ncaaw'): return team.location or team.display
    if team.league in ('mls','epl','laliga','bundesliga','seriea','ligue1','ligamx','ucl'):
        return team.display
    return team.nickname or team.short or team.display
