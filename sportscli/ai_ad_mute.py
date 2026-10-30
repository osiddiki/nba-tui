"""Optional, explicitly installed local NBA commercial detection for mpv."""
from __future__ import annotations

import hashlib
import json
import math
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
from . import progress

from .ad_mute import MuteState


MODEL_URL = ('https://huggingface.co/plt3/NBA-redzone-ML/resolve/'
             'cd44632d73cd178c975304dbb13502d6a49e3d91/part5_cropped_5-29-24.keras?download=true')
MODEL_SHA256 = '463f8964888ee2d55c176b385f4587eabd7cc508be36813c58db54925460ac83'
MAX_MODEL_BYTES = 160_000_000
WORKER = pathlib.Path(__file__).resolve().with_name('ai_ad_worker.py')
EXPORTER = pathlib.Path(__file__).resolve().parent / 'tools' / 'export_ad_model.py'


def installation_dir():
    base = pathlib.Path(os.environ.get('XDG_DATA_HOME') or pathlib.Path.home() / '.local' / 'share')
    return base / 'sports-live' / 'ad-mute'


def installation_paths():
    root = installation_dir()
    # A locally trained model installed by tools.train_ad_model replaces the original.
    trained = root / 'ad-model.tflite'
    return root / 'venv' / 'bin' / 'python', trained if trained.is_file() else root / 'nba-ads-v1.tflite'


def supported_leagues():
    """Leagues the active model was trained on; the original model covers only the NBA."""
    try:
        document = json.loads((installation_dir() / 'ad-model.json').read_text(encoding='utf-8'))
        leagues = document.get('leagues') if (installation_dir() / 'ad-model.tflite').is_file() else None
    except (OSError, ValueError, AttributeError):
        leagues = None
    if not isinstance(leagues, list) or not all(isinstance(item, str) for item in leagues): return {'nba'}
    return set(leagues) or {'nba'}


def installed():
    python, model = installation_paths()
    return python.is_file() and model.is_file()


def compatible_python():
    if (3, 9) <= sys.version_info[:2] <= (3, 12):
        return sys.executable, sys.version_info[:2]
    for minor in (12, 11, 10, 9):
        executable = shutil.which(f'python3.{minor}')
        if executable: return executable, (3, minor)
    return None, None


def install():
    """Install only when the user explicitly requests the optional model."""
    if installed():
        print(f'Local AI ad detector already installed in {installation_dir()}.')
        return 0
    if sys.platform != 'darwin' and not sys.platform.startswith('linux'):
        print('AI ad detection requires macOS or Linux.', file=sys.stderr); return 1
    interpreter, python_version = compatible_python()
    if not interpreter:
        print('The one-time AI setup needs Python 3.9 through 3.12 and venv.', file=sys.stderr); return 1
    intel_mac = sys.platform == 'darwin' and platform.machine().lower() in ('x86_64', 'amd64')
    root = installation_dir()
    try: root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        print(f'Cannot create detector directory: {exc}', file=sys.stderr); return 1
    if root.exists():
        print(f'Incomplete installation exists at {root}; remove it before retrying.', file=sys.stderr)
        return 1
    print('Installing the optional NBA ad detector. This downloads a 150 MB source model and conversion packages;')
    print('allow about 1.5 GB of temporary space. The final model is about 22 MB.', flush=True)
    if intel_mac: print('Intel macOS needs the larger TensorFlow runtime.')
    try: temporary = pathlib.Path(tempfile.mkdtemp(prefix='ad-mute-', dir=str(root.parent)))
    except OSError as exc:
        print(f'Cannot create temporary installation: {exc}', file=sys.stderr); return 1
    try:
        build = temporary / 'build'; build.mkdir()
        source = build / 'source.keras'
        digest = hashlib.sha256(); total = 0
        with urllib.request.urlopen(MODEL_URL, timeout=45) as response, source.open('wb') as out:
            try: length = int(getattr(response, 'headers', {}).get('Content-Length', ''))
            except (ValueError, TypeError): length = None
            if length and length > MAX_MODEL_BYTES: raise ValueError('Model download exceeded the expected size')
            with progress.Download('Downloading model', length) as download:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk: break
                    total += len(chunk)
                    if total > MAX_MODEL_BYTES: raise ValueError('Model download exceeded the expected size')
                    digest.update(chunk); out.write(chunk)
                    download.update(total)
        if digest.hexdigest() != MODEL_SHA256: raise ValueError('Model checksum did not match')
        converter = build / 'venv'
        with progress.activity('Installing temporary conversion tools'):
            subprocess.run([interpreter, '-m', 'venv', str(converter)], check=True)
            conversion_python = converter / 'bin' / 'python'
            tensorflow = 'tensorflow==2.16.2' if sys.platform == 'darwin' else 'tensorflow-cpu==2.16.2'
            subprocess.run([str(conversion_python), '-m', 'pip', 'install', '--quiet', '--no-cache-dir',
                            tensorflow, 'keras==3.3.3'], check=True)
        env = os.environ.copy()
        env.update({'CUDA_VISIBLE_DEVICES':'-1', 'OMP_NUM_THREADS':'2', 'OPENBLAS_NUM_THREADS':'1',
                    'TF_NUM_INTRAOP_THREADS':'2', 'TF_NUM_INTEROP_THREADS':'1', 'TF_CPP_MIN_LOG_LEVEL':'3'})
        model = temporary / 'nba-ads-v1.tflite'
        with progress.activity('Optimizing the model locally'):
            subprocess.run([str(conversion_python), str(EXPORTER), str(source), str(model)], env=env, check=True)
        if not model.is_file() or not 0 < model.stat().st_size <= 25_000_000:
            raise ValueError('Converted model has an unexpected size')
        shutil.rmtree(build)
        with progress.activity('Installing the isolated detection runtime'):
            subprocess.run([interpreter, '-m', 'venv', str(temporary / 'venv')], check=True)
            python = temporary / 'venv' / 'bin' / 'python'
            runtime = ('tensorflow==2.16.2' if intel_mac else
                       'ai-edge-litert==1.4.0' if python_version == (3, 9) else 'ai-edge-litert==2.3.0')
            subprocess.run([str(python), '-m', 'pip', 'install', '--quiet', '--no-cache-dir', runtime, 'Pillow>=10,<12'], check=True)
        check = subprocess.run([str(python), '-u', str(WORKER), str(model)], input='', capture_output=True,
                               text=True, env=env, timeout=60, check=True)
        if not json.loads(check.stdout.splitlines()[0]).get('ready'):
            raise ValueError('The installed detector could not load the model')
        # Use the venv Python directly; do not rely on relocation-sensitive pip scripts.
        os.rename(temporary, root)
        print('Installed. Run ./sports-cli --ai-ad-mute to enable it for a session.')
        return 0
    except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
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
            # Returning coverage should be audible on the first strong frame.
            self.ad = False
        else:
            self.uncertain += 1; self.ads = self.games = 0
            if self.uncertain >= 3: self.ad = False
        return self.ad


class PlaybackGate:
    """Count evidence only when the player is running and its timeline changes."""
    def __init__(self):
        self.position = None
        self.sampled_at = None
        self.discontinuity = False

    def accept(self, paused, position):
        self.discontinuity = False
        if paused is not False or isinstance(position, bool) or not isinstance(position, (int, float)):
            return False
        if not math.isfinite(position): return False
        if self.position is not None and abs(position - self.position) < .05: return False
        now = time.monotonic()
        if self.position is not None:
            elapsed = now - self.sampled_at
            difference = position - self.position
            self.discontinuity = difference < 0 or difference > max(5, elapsed * 3 + 1)
        self.position = position
        self.sampled_at = now
        return True


class Monitor:
    def __init__(self, socket_path, directory, python=None, model=None, interval=2, mute=True, on_break=None):
        default_python, default_model = installation_paths()
        self.path, self.directory = socket_path, pathlib.Path(directory)
        self.python, self.model = pathlib.Path(python or default_python), pathlib.Path(model or default_model)
        self.interval = interval
        self.mute = mute
        # Called as on_break(active, command) when a muted break starts or ends.
        self.on_break = on_break
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
        sock = None; reader = None; state = MuteState(); command = None; on_break = False
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
            reader = sock.makefile('rb'); request_id = 0; playback_epoch = 0
            def invoke(*args):
                nonlocal request_id, playback_epoch
                request_id += 1
                sock.sendall((json.dumps({'command':args, 'request_id':request_id})+'\n').encode())
                deadline = time.monotonic() + 2
                # Cleanup must still be able to use IPC after stop() is requested.
                while time.monotonic() < deadline:
                    raw = reader.readline(100_000)
                    if not raw: raise OSError('mpv disconnected')
                    response = json.loads(raw)
                    if response.get('event') in ('seek', 'start-file', 'file-loaded', 'end-file'):
                        playback_epoch += 1
                    if response.get('request_id') == request_id: return response
                raise OSError('mpv did not respond')
            command = invoke
            if not self._read_worker(30).get('ready'): raise OSError('AI detector failed to load')
            command('show-text', 'Local NBA ad detection active' if self.mute else 'Ad detection preview: audio unchanged', 2000)
            decision = Decision(); playback = PlaybackGate(); failures = 0; seen_epoch = playback_epoch
            manual_override = False
            def sync_break():
                nonlocal on_break
                if not self.on_break or state.in_ad == on_break: return
                on_break = state.in_ad
                try: self.on_break(on_break, command)
                except (OSError, ValueError, TypeError): pass
            def reset_detection():
                nonlocal state, decision, manual_override
                if state.applied:
                    muted = command('get_property', 'mute')
                    if muted.get('error') != 'success' or not isinstance(muted.get('data'), bool):
                        raise OSError('Could not read the player mute state')
                    if not muted['data']: manual_override = True
                    if muted['data'] and command('set_property', 'mute', False).get('error') != 'success':
                        raise OSError('Could not restore the player mute state')
                state = MuteState(); decision = Decision()
                sync_break()
            def unavailable_frame():
                nonlocal failures
                failures += 1
                reset_detection()
                if failures == 3:
                    command('show-text', 'Ad detection paused: frames unavailable', 3000)
            while not self.stopped.is_set():
                started = time.monotonic()
                paused = command('get_property', 'pause')
                position = command('get_property', 'time-pos')
                if playback_epoch != seen_epoch:
                    reset_detection(); playback = PlaybackGate(); manual_override = False
                    seen_epoch = playback_epoch
                if not playback.accept(paused.get('data') if paused.get('error') == 'success' else None,
                                       position.get('data') if position.get('error') == 'success' else None):
                    reset_detection()
                    self.stopped.wait(self.interval); continue
                if playback.discontinuity:
                    reset_detection(); manual_override = False
                frame_epoch = playback_epoch
                frame_position = position['data']
                captured_at = time.monotonic()
                image.unlink(missing_ok=True)
                result = command('screenshot-to-file', str(image), 'video')
                if result.get('error') != 'success' or not image.exists():
                    unavailable_frame()
                    self.stopped.wait(self.interval); continue
                self.process.stdin.write(json.dumps({'image':str(image)})+'\n'); self.process.stdin.flush()
                response = self._read_worker(3)
                image.unlink(missing_ok=True)
                score = response.get('score')
                if isinstance(score, bool) or not isinstance(score, (int,float)) or not 0 <= score <= 1:
                    unavailable_frame()
                    self.stopped.wait(self.interval); continue
                # mpv may have sought, changed files, or paused while inference ran.
                current_pause = command('get_property', 'pause')
                current_position = command('get_property', 'time-pos')
                current = current_position.get('data')
                elapsed = time.monotonic() - captured_at
                if (self.stopped.is_set() or playback_epoch != frame_epoch or
                    current_pause.get('error') != 'success' or current_pause.get('data') is not False or
                    current_position.get('error') != 'success' or isinstance(current, bool) or
                    not isinstance(current, (int, float)) or not math.isfinite(current) or
                    current < frame_position or current - frame_position > max(2, elapsed * 3 + 1)):
                    reset_detection(); playback = PlaybackGate(); manual_override = False
                    seen_epoch = playback_epoch
                    self.stopped.wait(self.interval); continue
                failures = 0
                was_ad = decision.ad
                in_ad = decision.update(score)
                if score >= .8: manual_override = False
                if self.mute:
                    muted = command('get_property', 'mute')
                    muted = muted.get('data') if muted.get('error') == 'success' else None
                    if not isinstance(muted, bool): raise OSError('Could not read the player mute state')
                    if self.stopped.is_set() or playback_epoch != frame_epoch:
                        reset_detection(); playback = PlaybackGate(); manual_override = False
                        seen_epoch = playback_epoch
                        continue
                    if state.applied and not muted: manual_override = True
                    previous = state.in_ad, state.applied
                    action = state.update(in_ad and not manual_override, muted)
                    if action is not None and command('set_property', 'mute', action).get('error') != 'success':
                        state.in_ad, state.applied = previous
                        raise OSError('Could not change the player mute state')
                    if self.stopped.is_set() or playback_epoch != frame_epoch:
                        # A seek can arrive with the mute command's reply. Undo
                        # a newly applied mute before waiting or sampling again.
                        reset_detection(); playback = PlaybackGate(); manual_override = False
                        seen_epoch = playback_epoch
                        continue
                    sync_break()
                if in_ad != was_ad:
                    label = ('Possible ad: auto-mute' if self.mute else 'Possible ad: audio unchanged') if in_ad else 'Broadcast detected'
                    command('show-text', label, 2000)
                self.stopped.wait(max(0, self.interval-(time.monotonic()-started)))
        except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.SubprocessError):
            if command and not self.stopped.is_set():
                try: command('show-text', 'Local ad detector stopped', 3000)
                except (OSError, ValueError): pass
        finally:
            if self.on_break and on_break:
                try: self.on_break(False, command)
                except (OSError, ValueError, TypeError): pass
            # Never strand a player muted if detection fails while it is still open.
            if command and state.applied:
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
                for stream in (self.process.stdin, self.process.stdout):
                    if stream:
                        try: stream.close()
                        except OSError: pass
