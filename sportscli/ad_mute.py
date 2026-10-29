"""Optional mpv muting for replay playlists with explicit HLS ad cues."""
from __future__ import annotations

import json
import re
import socket
import threading
import time
import urllib.parse
import urllib.request

from . import grading


def cue_intervals(manifest):
    """Return ad offsets only for complete playlists with explicit cue markers."""
    if not manifest.lstrip().startswith('#EXTM3U') or '#EXT-X-ENDLIST' not in manifest:
        return []
    position, start, duration, intervals = 0.0, None, None, []
    for line in manifest.splitlines():
        line = line.strip()
        if line.startswith('#EXT-X-CUE-OUT:') and start is None:
            start = position
            value = line.split(':', 1)[1]
            match = re.search(r'(?:DURATION=)?([0-9]+(?:\.[0-9]+)?)', value, re.I)
            duration = float(match.group(1)) if match else None
        elif line == '#EXT-X-CUE-OUT' and start is None:
            start, duration = position, None
        elif line.startswith('#EXT-X-CUE-IN') and start is not None:
            if position > start: intervals.append((start, position))
            start, duration = None, None
        elif line.startswith('#EXTINF:'):
            try: position += max(0.0, float(line[8:].split(',', 1)[0]))
            except ValueError: return []
    if start is not None and duration is not None and duration > 0:
        end = min(position, start+duration)
        if end > start: intervals.append((start, end))
    return intervals


def marked_replay_intervals(url, headers=None):
    """Follow a bounded HLS playlist chain, respecting public and local URLs."""
    parsed = urllib.parse.urlsplit(url)
    local_port = parsed.port if parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1','localhost') else None
    opener = urllib.request.build_opener(grading._Redirect(local_port))
    request_headers = {'User-Agent':'Mozilla/5.0', 'Accept':'*/*'}
    request_headers.update(headers or {})
    for _ in range(3):
        if not grading._permitted(url, local_port): raise ValueError('Invalid playlist URL')
        with opener.open(urllib.request.Request(url, headers=request_headers), timeout=5) as response:
            raw = response.read(1_000_001); url = response.geturl()
        if len(raw) > 1_000_000: raise ValueError('Playlist too large')
        manifest = raw.decode('utf8','replace')
        if not manifest.lstrip().startswith('#EXTM3U'): return []
        if '#EXT-X-STREAM-INF' not in manifest:
            return cue_intervals(manifest)
        lines = [line.strip() for line in manifest.splitlines() if line.strip()]
        variants = []
        for i, line in enumerate(lines):
            if line.startswith('#EXT-X-STREAM-INF:') and i+1 < len(lines) and not lines[i+1].startswith('#'):
                match = re.search(r'RESOLUTION=\d+x(\d+)',line,re.I)
                variants.append((int(match.group(1)) if match else 0,lines[i+1]))
        if not variants: return []
        url = urllib.parse.urljoin(url,max(variants)[1])
    return []


class MuteState:
    """Only undo our own mute; respect an already-muted or manually unmuted player."""
    def __init__(self):
        self.in_ad = False
        self.applied = False

    def update(self, in_ad, muted):
        action = None
        if in_ad and not self.in_ad:
            self.applied = not muted
            if self.applied: action = True
        elif in_ad and self.applied and not muted:
            self.applied = False
        elif not in_ad and self.in_ad:
            if self.applied and muted: action = False
            self.applied = False
        self.in_ad = in_ad
        return action


class Monitor:
    def __init__(self, socket_path, intervals):
        self.path, self.intervals = socket_path, intervals
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread.is_alive(): self.thread.join(timeout=2)

    def run(self):
        deadline = time.monotonic()+10
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(.5)
        try:
            while not self.stopped.is_set():
                try: sock.connect(self.path); break
                except OSError:
                    if time.monotonic() >= deadline: return
                    self.stopped.wait(.1)
            else: return
            reader = sock.makefile('rb')
            request_id = 0
            def command(*args):
                nonlocal request_id
                request_id += 1
                sock.sendall((json.dumps({'command':args,'request_id':request_id})+'\n').encode())
                while not self.stopped.is_set():
                    line = reader.readline(100_000)
                    if not line: raise OSError('mpv disconnected')
                    response = json.loads(line)
                    if response.get('request_id') == request_id:
                        return response.get('data') if response.get('error') == 'success' else None
                return None
            state = MuteState()
            while not self.stopped.is_set():
                position = command('get_property','time-pos')
                muted = command('get_property','mute')
                if isinstance(position,(int,float)) and isinstance(muted,bool):
                    in_ad = any(start <= position < end for start,end in self.intervals)
                    action = state.update(in_ad, muted)
                    if action is not None: command('set_property','mute',action)
                self.stopped.wait(.3)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        finally:
            sock.close()
