"""Small terminal progress displays; Rich is optional, plain terminals still work."""
from __future__ import annotations

import contextlib
import shutil
import sys
import time

Console = Progress = None
_rich_loaded = False


def _load_rich():
    global _rich_loaded, Console, Progress, BarColumn, DownloadColumn, TaskProgressColumn, TextColumn, TransferSpeedColumn
    if _rich_loaded: return
    _rich_loaded = True
    try:
        from rich.console import Console as console
        from rich.progress import BarColumn as bar, DownloadColumn as download, Progress as progress
        from rich.progress import TaskProgressColumn as percent, TextColumn as text, TransferSpeedColumn as speed
    except ImportError:
        return
    Console, Progress = console, progress
    BarColumn, DownloadColumn, TaskProgressColumn, TextColumn, TransferSpeedColumn = bar, download, percent, text, speed


def size_text(value):
    value = max(0, value)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1000 or unit == 'GB':
            return f'{value:.1f} {unit}' if unit != 'B' else f'{value:.0f} B'
        value /= 1000


class Download:
    def __init__(self, label, total=None, stream=None):
        self.label, self.total = label, total if isinstance(total, int) and total > 0 else None
        self.stream = stream if stream is not None else sys.stdout
        self.terminal = bool(getattr(self.stream, 'isatty', lambda: False)())
        self.current = 0
        self.last_draw = 0.0
        self.progress = self.task = None

    def __enter__(self):
        if self.terminal: _load_rich()
        if self.terminal and Progress is not None:
            console = Console(file=self.stream)
            columns = [
                TextColumn('{task.description}'),
                BarColumn(bar_width=None, style='#30313d', complete_style='#7c81eb',
                          finished_style='#7c81eb', pulse_style='#7c81eb'),
                TaskProgressColumn(), DownloadColumn(),
            ]
            if console.width >= 64: columns.append(TransferSpeedColumn())
            label = ('Downloading' if console.width < 52 and self.label.startswith('Downloading ')
                     else self.label)
            self.progress = Progress(*columns, console=console, auto_refresh=False, expand=True)
            self.progress.start()
            self.task = self.progress.add_task(label, total=self.total)
            self.progress.refresh()
        elif not self.terminal:
            print(self.label + '...', file=self.stream, flush=True)
        else:
            self.draw()
        return self

    def update(self, completed):
        self.current = max(0, completed)
        now = time.monotonic()
        if now-self.last_draw < .1 and (not self.total or self.current < self.total): return
        self.draw()

    def draw(self):
        self.last_draw = time.monotonic()
        if self.progress:
            self.progress.update(self.task, completed=self.current, refresh=True)
        elif self.terminal:
            width = shutil.get_terminal_size((80, 24)).columns
            count = size_text(self.current)
            if self.total:
                ratio = min(1.0, self.current / self.total)
                info = f'{ratio:3.0%}  {count} / {size_text(self.total)}'
                bar_width = max(0, min(24, width - len(self.label) - len(info) - 5))
                filled = round(bar_width * ratio)
                bar = '=' * filled + '-' * (bar_width-filled)
                text = f'{self.label}  {bar}  {info}'
            else:
                text = f'{self.label}  {count}'
            self.stream.write('\r' + text[:max(0, width-1)] + '\x1b[K')
            self.stream.flush()

    def __exit__(self, exc_type, exc, tb):
        if self.progress:
            self.progress.update(self.task, completed=self.current, refresh=True)
            self.progress.stop()
        elif self.terminal:
            self.draw()
            self.stream.write('\n'); self.stream.flush()
        elif exc_type is None:
            print(f'{self.label}: {size_text(self.current)}', file=self.stream, flush=True)
        return False


@contextlib.contextmanager
def activity(label, stream=None):
    output = stream if stream is not None else sys.stdout
    if getattr(output, 'isatty', lambda: False)(): _load_rich()
    if Console is not None and getattr(output, 'isatty', lambda: False)():
        with Console(file=output).status(label, spinner='dots', spinner_style='#7c81eb'):
            yield
    else:
        print(label + '...', file=output, flush=True)
        yield
