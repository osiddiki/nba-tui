"""Live HLS merging: one verified output timeline built from equivalent sources.

The relay downloads each segment before listing it, so the player never sees a
segment that failed. When the active source stalls or fails, the timeline
continues from another source at the closest matching point.
"""
from __future__ import annotations
import datetime
import math
import time
import urllib.parse


class Unsupported(ValueError):
    """The playlist uses a feature the merger does not splice safely."""


class Segment:
    __slots__ = ('seq', 'url', 'duration', 'pdt', 'discontinuity')

    def __init__(self, seq, url, duration, pdt=None, discontinuity=False):
        self.seq, self.url, self.duration = seq, url, duration
        self.pdt, self.discontinuity = pdt, discontinuity

    @property
    def name(self):
        # Re-hosted copies of one upstream usually keep segment file names.
        return urllib.parse.urlsplit(self.url).path.rsplit('/', 1)[-1]


class Playlist:
    __slots__ = ('target', 'segments', 'endlist')

    def __init__(self, target, segments, endlist):
        self.target, self.segments, self.endlist = target, segments, endlist


def _attributes(text):
    out, key, value, quoted, reading_key = {}, '', '', False, True
    for ch in text + ',':
        if reading_key:
            if ch == '=': reading_key = False
            elif ch != ',': key += ch
        elif ch == '"': quoted = not quoted
        elif ch == ',' and not quoted:
            out[key.strip().upper()] = value; key, value, reading_key = '', '', True
        else: value += ch
    return out


def _timestamp(text):
    try:
        return datetime.datetime.fromisoformat(text.strip().replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def variant_url(text, base):
    """Return the highest-bandwidth variant of a master playlist, or None for media playlists."""
    if '#EXT-X-STREAM-INF' not in text: return None
    best, bandwidth = None, None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('#EXT-X-MEDIA:'):
            attrs = _attributes(line[len('#EXT-X-MEDIA:'):])
            if attrs.get('TYPE') == 'AUDIO' and attrs.get('URI'):
                raise Unsupported('separate audio renditions')
        elif line.startswith('#EXT-X-STREAM-INF:'):
            try: bandwidth = int(_attributes(line[len('#EXT-X-STREAM-INF:'):]).get('BANDWIDTH') or 0)
            except ValueError: bandwidth = 0
        elif line and not line.startswith('#') and bandwidth is not None:
            if best is None or bandwidth > best[0]: best = (bandwidth, urllib.parse.urljoin(base, line))
            bandwidth = None
    if not best: raise Unsupported('master playlist has no variants')
    return best[1]


def parse_media(text, base):
    if not text.lstrip().startswith('#EXTM3U'): raise ValueError('invalid playlist')
    sequence, target, segments, endlist = 0, 6.0, [], False
    duration, next_pdt, discontinuity = None, None, False
    for raw in text.splitlines():
        line = raw.strip()
        if not line: continue
        if line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
            sequence = int(line.split(':', 1)[1])
        elif line.startswith('#EXT-X-TARGETDURATION:'):
            target = float(line.split(':', 1)[1])
        elif line.startswith('#EXTINF:'):
            duration = float(line[len('#EXTINF:'):].split(',', 1)[0])
        elif line.startswith('#EXT-X-PROGRAM-DATE-TIME:'):
            next_pdt = _timestamp(line.split(':', 1)[1])
        elif line == '#EXT-X-DISCONTINUITY':
            discontinuity = True
        elif line == '#EXT-X-ENDLIST':
            endlist = True
        elif line.startswith('#EXT-X-KEY:'):
            if _attributes(line[len('#EXT-X-KEY:'):]).get('METHOD', 'NONE') != 'NONE':
                raise Unsupported('encrypted playlist')
        elif line.startswith(('#EXT-X-MAP', '#EXT-X-BYTERANGE', '#EXT-X-STREAM-INF')):
            raise Unsupported(line.split(':', 1)[0][1:].lower())
        elif not line.startswith('#'):
            length = duration if duration and duration > 0 else target
            segments.append(Segment(sequence + len(segments), urllib.parse.urljoin(base, line),
                                    length, next_pdt, discontinuity))
            next_pdt = next_pdt + length if next_pdt is not None else None
            duration, discontinuity = None, False
    return Playlist(target, segments, endlist)


def first_pts(data):
    """First presentation timestamp (90 kHz) in a transport stream, preferring video."""
    audio = None
    for pos in range(0, min(len(data), 188 * 4000) - 187, 188):
        if data[pos] != 0x47 or not data[pos + 1] & 0x40: continue
        start = pos + 4
        if data[pos + 3] & 0x20: start += 1 + data[pos + 4]
        pes = data[start:pos + 188]
        if len(pes) < 14 or pes[:3] != b'\x00\x00\x01' or not pes[7] & 0x80: continue
        p = pes[9:14]
        pts = ((p[0] >> 1) & 7) << 30 | p[1] << 22 | (p[2] >> 1) << 15 | p[3] << 7 | p[4] >> 1
        if 0xE0 <= pes[3] <= 0xEF: return pts
        if audio is None and 0xC0 <= pes[3] <= 0xDF: audio = pts
    return audio


def pts_seconds(later, earlier):
    """Signed difference between two 33-bit timestamps, in seconds."""
    difference = (later - earlier) % (1 << 33)
    if difference >= 1 << 32: difference -= 1 << 33
    return difference / 90000


def realign(segments, position, measured, expected, tolerance=.5):
    """Index of the first segment that does not repeat already-played media.

    Returns len(segments) when the matching segment is not published yet; the
    caller then waits rather than replaying earlier media.
    """
    starts, offset = {}, 0.0
    for index in range(position, len(segments)):
        starts[index] = offset; offset += segments[index].duration
    offset = 0.0
    for index in range(position - 1, -1, -1):
        offset -= segments[index].duration; starts[index] = offset
    behind = pts_seconds(expected, measured)
    for index in range(len(segments)):
        if starts[index] >= behind - tolerance: return index
    return len(segments)


class Timeline:
    """Output segments the relay has already downloaded, across source switches."""

    def __init__(self, window=6, keep=24, start=3):
        self.window, self.keep, self.start = window, keep, start
        self.entries = []          # (output sequence, key, duration, discontinuity)
        self.next_seq = 0
        self.dropped_discontinuities = 0
        self.cursor = {}           # source index -> last committed source sequence
        self.last = None           # last committed Segment
        self.last_source = None
        self.edge_gap, self.edge_time = 0.0, time.monotonic()

    def observe(self, index, playlist):
        """Track how far the output trails its source's live edge."""
        if index != self.last_source or self.last is None: return
        self.edge_gap = sum(s.duration for s in playlist.segments if s.seq > self.last.seq)
        self.edge_time = time.monotonic()

    def plan(self, index, playlist):
        """Segments to download next from this source, with their discontinuity flags."""
        segments = playlist.segments
        if not segments: return []
        if index == self.last_source and index in self.cursor:
            pending = [s for s in segments if s.seq > self.cursor[index]]
            # A provider that restarts its sequence numbering needs a fresh resume point.
            if pending or segments[-1].seq >= self.cursor[index]:
                return [(s, s.discontinuity) for s in pending]
        if self.last is None:
            return [(s, s.discontinuity) for s in segments[-self.start:]]
        names = [s.name for s in segments]
        if self.last.name in names:
            following = segments[names.index(self.last.name) + 1:]
            return [(s, s.discontinuity) for s in following]
        if self.last.pdt is not None and all(s.pdt is not None for s in segments):
            end = self.last.pdt + self.last.duration - .25
            following = [s for s in segments if s.pdt >= end]
            if following and following[0].pdt - end < max(30, 4 * playlist.target):
                return [(s, i == 0 or s.discontinuity) for i, s in enumerate(following)]
        # No shared names or clocks: keep the same distance from the live edge.
        gap = self.edge_gap + (time.monotonic() - self.edge_time)
        position, remaining = len(segments) - 1, segments[-1].duration
        while position > 0 and remaining + segments[position - 1].duration <= gap + .5:
            position -= 1; remaining += segments[position].duration
        return [(s, i == 0 or s.discontinuity) for i, s in enumerate(segments[position:])]

    def skip(self, index, segment):
        """Move past a segment no source could supply; the next one starts a discontinuity."""
        self.cursor[index], self.last, self.last_source = segment.seq, segment, index
        self.gap = True

    gap = False

    end_pts = None

    def needs_alignment(self, index, plan):
        """True when this plan starts on another source without a shared name or clock."""
        if not plan or self.last is None or index == self.last_source or self.end_pts is None: return False
        return bool(plan[0][1])

    def commit(self, index, segment, discontinuity, key, pts=None):
        self.end_pts = (pts + round(segment.duration * 90000)) % (1 << 33) if pts is not None else None
        discontinuity = discontinuity or self.gap; self.gap = False
        self.entries.append((self.next_seq, key, segment.duration, bool(discontinuity and self.entries)))
        self.next_seq += 1
        self.cursor[index], self.last, self.last_source = segment.seq, segment, index
        while len(self.entries) > self.keep:
            if self.entries.pop(0)[3]: self.dropped_discontinuities += 1

    def keys(self):
        return {entry[1] for entry in self.entries}

    def render(self, segment_url):
        shown = self.entries[-self.window:]
        if not shown: raise ValueError('no verified segments yet')
        hidden = self.entries[:len(self.entries) - len(shown)]
        lines = ['#EXTM3U', '#EXT-X-VERSION:3',
                 f'#EXT-X-TARGETDURATION:{max(1, math.ceil(max(e[2] for e in shown)))}',
                 f'#EXT-X-MEDIA-SEQUENCE:{shown[0][0]}',
                 f'#EXT-X-DISCONTINUITY-SEQUENCE:{self.dropped_discontinuities + sum(e[3] for e in hidden)}']
        for _, key, duration, discontinuity in shown:
            if discontinuity: lines.append('#EXT-X-DISCONTINUITY')
            lines.append(f'#EXTINF:{duration:.3f},')
            lines.append(segment_url(key))
        return '\n'.join(lines) + '\n'
