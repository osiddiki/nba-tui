"""Optional, explicitly installed local NBA commercial detection for mpv."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import platform
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import venv

from ad_mute import MuteState


MODEL_URL = 'https://github.com/osiddiki/nba-tui/releases/download/ad-model-v1/nba-ads-v1.tflite'
MODEL_SHA256 = '301e528cdf3f00d5d76e6a051dc1de0e64a9b4293beb2fbdb667d8373d1d46df'
MAX_MODEL_BYTES = 25_000_000
WORKER = pathlib.Path(__file__).resolve().with_name('ai_ad_worker.py')


def installation_dir():
    base = pathlib.Path(os.environ.get('XDG_DATA_HOME') or pathlib.Path.home() / '.local' / 'share')
    return base / 'sports-live' / 'ad-mute'


def installation_paths():
    root = installation_dir()
    return root / 'venv' / 'bin' / 'python', root / 'nba-ads-v1.tflite'


def installed():
    python, model = installation_paths()
    return python.is_file() and model.is_file()


def install():
    """Install only when the user explicitly requests the optional model."""
    if installed():
        print(f'Local AI ad detector already installed in {installation_dir()}.')
        return 0
    if sys.platform != 'darwin' and not sys.platform.startswith('linux'):
        print('AI ad detection requires macOS or Linux.', file=sys.stderr); return 1
    if sys.version_info < (3, 9):
        print('AI ad detection requires Python 3.9 or newer.', file=sys.stderr); return 1
    intel_mac = sys.platform == 'darwin' and platform.machine().lower() in ('x86_64', 'amd64')
    if intel_mac and sys.version_info >= (3, 13):
        print('AI detection on Intel Macs requires Python 3.9 through 3.12.', file=sys.stderr); return 1
    root = installation_dir()
    try: root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        print(f'Cannot create detector directory: {exc}', file=sys.stderr); return 1
    if root.exists():
        print(f'Incomplete installation exists at {root}; remove it before retrying.', file=sys.stderr)
        return 1
    print('Installing the optional local NBA ad detector; this downloads a 22 MB model and Python packages.')
    if intel_mac: print('Intel macOS needs the larger TensorFlow runtime.')
    try: temporary = pathlib.Path(tempfile.mkdtemp(prefix='ad-mute-', dir=str(root.parent)))
    except OSError as exc:
        print(f'Cannot create temporary installation: {exc}', file=sys.stderr); return 1
    try:
        model = temporary / 'nba-ads-v1.tflite'
        digest = hashlib.sha256(); total = 0
        with urllib.request.urlopen(MODEL_URL, timeout=45) as response, model.open('wb') as out:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk: break
                total += len(chunk)
                if total > MAX_MODEL_BYTES: raise ValueError('Model download exceeded the expected size')
                digest.update(chunk); out.write(chunk)
        if digest.hexdigest() != MODEL_SHA256: raise ValueError('Model checksum did not match')
        venv.create(str(temporary / 'venv'), with_pip=True)
        python = temporary / 'venv' / 'bin' / 'python'
        runtime = ('tensorflow==2.16.2' if intel_mac else
                   'ai-edge-litert==1.4.0' if sys.version_info[:2] == (3, 9) else 'ai-edge-litert==2.3.0')
        subprocess.run([str(python), '-m', 'pip', 'install', '--no-cache-dir', runtime, 'Pillow>=10,<12'], check=True)
        # Use the venv Python directly; do not rely on relocation-sensitive pip scripts.
        os.rename(temporary, root)
        print('Installed. Run ./sports_live --ai-ad-mute to enable it for a session.')
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'Optional AI detector installation failed: {exc}', file=sys.stderr)
        return 1
    finally:
        if temporary.exists(): shutil.rmtree(temporary)


class Decision:
    """Require repeated evidence and release mute if predictions stay uncertain."""
    def __init__(self):
        self.ad = False
        self.ads = self.games = self.uncertain = 0

    def update(self, score):
        if score <= .2:
            self.ads += 1; self.games = self.uncertain = 0
            if self.ads >= 2: self.ad = True
        elif score >= .8:
            self.games += 1; self.ads = self.uncertain = 0
            if self.games >= 2: self.ad = False
        else:
            self.uncertain += 1; self.ads = self.games = 0
            if self.uncertain >= 3: self.ad = False
        return self.ad


class Monitor:
    def __init__(self, socket_path, directory, python=None, model=None, interval=2):
        default_python, default_model = installation_paths()
        self.path, self.directory = socket_path, pathlib.Path(directory)
        self.python, self.model = pathlib.Path(python or default_python), pathlib.Path(model or default_model)
        self.interval = interval
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.process = None

    def start(self): self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.process and self.process.poll() is None:
            try: self.process.terminate()
            except ProcessLookupError: pass
        if self.thread.is_alive(): self.thread.join(timeout=3)
        if self.process and self.process.poll() is None:
            try: self.process.kill(); self.process.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired): pass

    def _read_worker(self, timeout):
        deadline = time.monotonic() + timeout
        while not self.stopped.is_set() and time.monotonic() < deadline:
            if self.process.poll() is not None: raise OSError('AI detector exited')
            if select.select([self.process.stdout], [], [], .2)[0]:
                value = json.loads(self.process.stdout.readline())
                if isinstance(value, dict): return value
        raise OSError('AI detector did not respond')

    def run(self):
        sock = None; reader = None; state = MuteState(); command = None
        image = self.directory / 'current-frame.jpg'
        try:
            env = os.environ.copy()
            env.update({'CUDA_VISIBLE_DEVICES':'-1', 'OMP_NUM_THREADS':'2', 'OPENBLAS_NUM_THREADS':'1',
                        'TF_NUM_INTRAOP_THREADS':'2', 'TF_NUM_INTEROP_THREADS':'1', 'TF_CPP_MIN_LOG_LEVEL':'3'})
            self.process = subprocess.Popen([str(self.python), '-u', str(WORKER), str(self.model)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); sock.settimeout(2)
            deadline = time.monotonic() + 10
            while not self.stopped.is_set():
                try: sock.connect(self.path); break
                except OSError:
                    if time.monotonic() >= deadline: raise
                    self.stopped.wait(.1)
            else: return
            reader = sock.makefile('rb'); request_id = 0
            def invoke(*args):
                nonlocal request_id
                request_id += 1
                sock.sendall((json.dumps({'command':args, 'request_id':request_id})+'\n').encode())
                while not self.stopped.is_set():
                    raw = reader.readline(100_000)
                    if not raw: raise OSError('mpv disconnected')
                    response = json.loads(raw)
                    if response.get('request_id') == request_id: return response
                raise OSError('stopped')
            command = invoke
            if not self._read_worker(30).get('ready'): raise OSError('AI detector failed to load')
            command('show-text', 'Local NBA ad detection active', 2000)
            decision = Decision()
            while not self.stopped.is_set():
                started = time.monotonic()
                image.unlink(missing_ok=True)
                result = command('screenshot-to-file', str(image), 'video')
                if result.get('error') != 'success' or not image.exists():
                    self.stopped.wait(self.interval); continue
                self.process.stdin.write(json.dumps({'image':str(image)})+'\n'); self.process.stdin.flush()
                response = self._read_worker(15)
                image.unlink(missing_ok=True)
                score = response.get('score')
                if not isinstance(score, (int,float)) or not 0 <= score <= 1:
                    self.stopped.wait(self.interval); continue
                was_ad = decision.ad
                in_ad = decision.update(score)
                muted = command('get_property', 'mute')
                muted = muted.get('data') if muted.get('error') == 'success' else None
                if isinstance(muted, bool):
                    action = state.update(in_ad, muted)
                    if action is not None: command('set_property', 'mute', action)
                    if in_ad != was_ad:
                        command('show-text', 'Ad detected: auto-mute' if in_ad else 'Broadcast detected: ad break ended', 2000)
                self.stopped.wait(max(0, self.interval-(time.monotonic()-started)))
        except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.SubprocessError):
            if command and not self.stopped.is_set():
                try: command('show-text', 'Local ad detector stopped', 3000)
                except (OSError, ValueError): pass
        finally:
            # Never strand a player muted if detection fails while it is still open.
            if command and state.applied and not self.stopped.is_set():
                try:
                    muted = command('get_property', 'mute')
                    if muted.get('data') is True: command('set_property', 'mute', False)
                except (OSError, ValueError): pass
            try: image.unlink(missing_ok=True)
            except OSError: pass
            if reader:
                try: reader.close()
                except OSError: pass
            if sock: sock.close()
            if self.process:
                if self.process.poll() is None:
                    try: self.process.terminate()
                    except ProcessLookupError: pass
                try: self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try: self.process.kill(); self.process.wait()
                    except ProcessLookupError: pass
