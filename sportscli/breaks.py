"""What to show while the ad detector reports a commercial break."""
from __future__ import annotations

import subprocess
import threading
import time

MODES = ('mute', 'cover', 'corner')
LABELS = {'mute': 'mute only', 'cover': 'break screen', 'corner': 'other game in a corner'}
OVERLAY_ID = 63
WIDTH, HEIGHT = 1280, 720
# Tokenized links expire; resolve the preview again after this long.
FRESH_FOR = 15 * 60


def _escape(text):
    return ''.join(' ' if ch in '\r\n' else '\\' + ch if ch in '{}\\' else ch for ch in text)


def cover_events(title, detail=''):
    """ASS events that black out the picture and explain the break. mpv omits OSD
    from video screenshots, so the detector still sees the game underneath."""
    box = f'{{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H101010&\\1a&H00&\\p1}}m 0 0 l {WIDTH} 0 {WIDTH} {HEIGHT} 0 {HEIGHT}{{\\p0}}'
    heading = f'{{\\an5\\pos({WIDTH//2},{HEIGHT//2 - 40})\\fs54\\bord0\\shad0\\1c&HFFFFFF&}}Commercial break'
    lines = [box, heading,
             f'{{\\an5\\pos({WIDTH//2},{HEIGHT//2 + 30})\\fs30\\bord0\\shad0\\1c&HBBBBBB&}}{_escape(title)}']
    if detail:
        lines.append(f'{{\\an5\\pos({WIDTH//2},{HEIGHT//2 + 80})\\fs24\\bord0\\shad0\\1c&H888888&}}{_escape(detail)}')
    return '\n'.join(lines)


def show_cover(command, title, detail=''):
    return command('osd-overlay', OVERLAY_ID, 'ass-events', cover_events(title, detail), WIDTH, HEIGHT, 0)


def hide_cover(command):
    return command('osd-overlay', OVERLAY_ID, 'none', '')


def other_live_game(games, current_id):
    """Another live game from the same schedule, or None."""
    return next((game for game in games if game.state == 'live' and game.id != current_id), None)


def corner_command(base):
    """Turn a full mpv command into a small, always-on-top window in the bottom-right corner."""
    separator = base.index('--')
    options = [option for option in base[1:separator] if not option.startswith(('--title=', '--input-ipc-server=', '--stream-record='))]
    return [base[0], *options, '--title=Sports CLI preview', '--ontop', '--no-border',
            '--autofit=32%', '--geometry=-24-48', '--no-osc', '--keep-open=no', *base[separator:]]


class CornerPreview:
    """Resolve another game ahead of time and show it in a corner window during breaks."""
    def __init__(self, title, resolve, build, *, popen=subprocess.Popen, clock=time.monotonic):
        self.title, self.resolve, self.build = title, resolve, build
        self.popen, self.clock = popen, clock
        self.lock = threading.Lock()
        self.source = None; self.resolved_at = None; self.resolving = False
        self.wanted = False; self.process = None; self.closed = False; self.error = None

    def prepare(self):
        with self.lock:
            if self.resolving or self.closed: return
            self.resolving = True
        threading.Thread(target=self._resolve, daemon=True).start()

    def _resolve(self):
        try: source, error = self.resolve(), None
        except Exception as exc: source, error = None, exc  # noqa: BLE001 - any provider failure means no preview
        with self.lock:
            self.resolving = False; self.error = error
            if source: self.source, self.resolved_at = source, self.clock()
            launch = self.wanted and not self.closed and source is not None
        if launch: self._launch()

    def fresh(self):
        return self.source is not None and self.clock() - self.resolved_at < FRESH_FOR

    def show(self):
        with self.lock:
            if self.closed: return False
            self.wanted = True
            ready = self.fresh()
        if ready: return self._launch()
        self.prepare()
        return False

    def _launch(self):
        with self.lock:
            if not self.wanted or self.closed or (self.process and self.process.poll() is None): return False
            url, headers = self.source
            try:
                self.process = self.popen(self.build(url, headers), stdin=subprocess.DEVNULL,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as exc:
                self.error = exc; self.process = None; return False
            return True

    def hide(self):
        with self.lock:
            self.wanted = False
            process, self.process = self.process, None
            if process is not None and process.poll() is not None: self.source = None  # it failed to play
            stale = not self.fresh()
        self._stop(process)
        if stale and not self.closed: self.prepare()

    def close(self):
        with self.lock:
            self.closed = True; self.wanted = False
            process, self.process = self.process, None
        self._stop(process)

    @staticmethod
    def _stop(process):
        if process is None or process.poll() is not None: return
        process.terminate()
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
