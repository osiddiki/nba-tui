import os
import pathlib
import hashlib
import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ai_ad_mute
import nba


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
        def make_venv(path, with_pip):
            python = pathlib.Path(path) / 'bin' / 'python'
            python.parent.mkdir(parents=True)
            python.write_text('test interpreter')
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'XDG_DATA_HOME':root}), \
             patch.object(ai_ad_mute.urllib.request, 'urlopen', side_effect=lambda *a, **k:io.BytesIO(contents)), \
             patch.object(ai_ad_mute.venv, 'create', side_effect=make_venv) as create_venv, \
             patch.object(ai_ad_mute.subprocess, 'run') as pip, \
             patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO):
            with patch.object(ai_ad_mute, 'MODEL_SHA256', 'wrong-checksum'):
                self.assertEqual(ai_ad_mute.install(), 1)
            self.assertFalse(ai_ad_mute.installed())
            create_venv.assert_not_called(); pip.assert_not_called()
            with patch.object(ai_ad_mute, 'MODEL_SHA256', hashlib.sha256(contents).hexdigest()):
                self.assertEqual(ai_ad_mute.install(), 0)
            self.assertTrue(ai_ad_mute.installed())
            create_venv.assert_called_once(); pip.assert_called_once()

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


if __name__ == '__main__':
    unittest.main()
