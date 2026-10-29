import os
import pathlib
import hashlib
import io
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sportscli import ai_ad_mute, app as nba


class AiAdMuteTests(unittest.TestCase):
    def test_repeated_predictions_and_uncertain_frames_are_conservative(self):
        decision = ai_ad_mute.Decision()
        self.assertFalse(decision.update(.1))
        self.assertTrue(decision.update(.05))
        self.assertTrue(decision.update(.9))
        self.assertFalse(decision.update(.95))
        self.assertFalse(decision.update(.1))
        self.assertTrue(decision.update(.1))
        self.assertTrue(decision.update(.5))
        self.assertTrue(decision.update(.5))
        self.assertFalse(decision.update(.5))

    def test_playback_gate_ignores_paused_stalled_and_invalid_positions(self):
        gate = ai_ad_mute.PlaybackGate()
        self.assertTrue(gate.accept(False, 10.0))
        self.assertFalse(gate.accept(True, 10.5))
        self.assertFalse(gate.accept(False, 10.0))
        self.assertFalse(gate.accept(False, None))
        self.assertFalse(gate.accept(False, float('nan')))
        self.assertFalse(gate.accept(None, 10.5))
        self.assertTrue(gate.accept(False, 10.5))
        self.assertTrue(gate.accept(False, 3.0))  # Seeking backwards is valid.

    def test_model_and_runtime_are_external_and_never_enabled_by_config(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'XDG_DATA_HOME':root}):
            python, model = ai_ad_mute.installation_paths()
            self.assertTrue(python.is_relative_to(pathlib.Path(root)))
            self.assertTrue(model.is_relative_to(pathlib.Path(root)))
            self.assertFalse(ai_ad_mute.installed())
            self.assertFalse(nba.App(None, {'ai_ad_mute':True}).ai_ad_mute)
            self.assertTrue(nba.App(None, {}, ai_ad_mute_enabled=True).ai_ad_mute)

    def test_explicit_installer_checks_download_before_installing(self):
        contents = b'local test model'
        def run(args, **kwargs):
            if len(args) > 3 and args[1:3] == ['-m', 'venv']:
                python = pathlib.Path(args[3]) / 'bin' / 'python'
                python.parent.mkdir(parents=True)
                python.write_text('test interpreter')
            elif len(args) > 3 and args[1] == str(ai_ad_mute.EXPORTER):
                pathlib.Path(args[3]).write_bytes(b'converted model')
            return SimpleNamespace(stdout='{"ready":true}\n', returncode=0)
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'XDG_DATA_HOME':root}), \
             patch.object(ai_ad_mute.urllib.request, 'urlopen', side_effect=lambda *a, **k:io.BytesIO(contents)), \
             patch.object(ai_ad_mute.subprocess, 'run', side_effect=run) as execute, \
             patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO):
            with patch.object(ai_ad_mute, 'MODEL_SHA256', 'wrong-checksum'):
                self.assertEqual(ai_ad_mute.install(), 1)
            self.assertFalse(ai_ad_mute.installed())
            execute.assert_not_called()
            with patch.object(ai_ad_mute, 'MODEL_SHA256', hashlib.sha256(contents).hexdigest()):
                self.assertEqual(ai_ad_mute.install(), 0)
            self.assertTrue(ai_ad_mute.installed())
            self.assertEqual(execute.call_count, 6)

    def test_other_sports_play_without_nba_classifier(self):
        class Screen:
            def refresh(self): pass
        app = nba.App(Screen(), {}, ai_ad_mute_enabled=True)
        app.league = 'nfl'; app.render = lambda: None
        app.resolve_feed = lambda feed: ('https://example.com/video', {})
        feed = nba.Feed('Example', 'Football', kind='direct')
        with patch.object(ai_ad_mute, 'installed', return_value=True), \
             patch.object(ai_ad_mute, 'Monitor') as monitor, \
             patch.object(nba.shutil, 'which', return_value='/usr/bin/mpv'), \
             patch.object(nba.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
             patch.object(nba.curses, 'def_prog_mode'), patch.object(nba.curses, 'endwin'), \
             patch.object(nba.curses, 'reset_prog_mode'):
            app.play(feed)
        monitor.assert_not_called()
        self.assertIn('limited to NBA', app.message)

    def test_observe_mode_shows_predictions_without_changing_audio(self):
        with tempfile.TemporaryDirectory(prefix='observe-test-', dir='/tmp') as root:
            worker = pathlib.Path(root) / 'worker.py'
            worker.write_text('import json,sys\nprint(json.dumps({"ready":True}),flush=True)\n'
                              'for line in sys.stdin: print(json.dumps({"score":0.01}),flush=True)\n')
            path = str(pathlib.Path(root) / 'player.sock')
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(path); server.listen(1)
            commands = []; showed_ad = threading.Event()
            def serve():
                connection, _ = server.accept()
                with connection, connection.makefile('rb') as reader:
                    position = 0
                    for line in reader:
                        request = json.loads(line); command = request['command']; commands.append(command)
                        data = None
                        if command[:2] == ['get_property','pause']: data = False
                        elif command[:2] == ['get_property','time-pos']:
                            position += 1; data = position
                        elif command[0] == 'screenshot-to-file': pathlib.Path(command[1]).write_bytes(b'frame')
                        elif command[0] == 'show-text' and 'Possible ad' in command[1]: showed_ad.set()
                        response = {'request_id':request['request_id'], 'error':'success', 'data':data}
                        connection.sendall((json.dumps(response)+'\n').encode())
            thread = threading.Thread(target=serve, daemon=True); thread.start()
            monitor = ai_ad_mute.Monitor(path, root, python=sys.executable, model='unused', interval=.05, mute=False)
            try:
                with patch.object(ai_ad_mute, 'WORKER', worker):
                    monitor.start()
                    self.assertTrue(showed_ad.wait(3), 'No ad prediction was displayed')
                    monitor.stop()
                self.assertFalse(any(command[:2] == ['set_property','mute'] for command in commands))
            finally:
                monitor.stop(); server.close(); thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
