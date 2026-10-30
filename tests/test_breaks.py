import subprocess
import threading
import unittest
import unittest.mock
from types import SimpleNamespace

from sportscli import app, breaks


class FakeProcess:
    def __init__(self, command):
        self.command = command; self.code = None; self.terminated = False

    def poll(self): return self.code

    def terminate(self): self.terminated = True; self.code = -15

    def wait(self, timeout=None): return self.code

    def kill(self): self.code = -9


class BreakTests(unittest.TestCase):
    def test_cover_escapes_titles_and_draws_full_frame(self):
        events = breaks.cover_events('A {at} B\\', 'line\nbreak')
        self.assertIn(f'l {breaks.WIDTH} 0 {breaks.WIDTH} {breaks.HEIGHT}', events)
        self.assertIn('A \\{at\\} B\\\\', events)
        self.assertNotIn('line\nbreak', events)
        sent = []
        breaks.show_cover(lambda *args: sent.append(args), 'Title')
        breaks.hide_cover(lambda *args: sent.append(args))
        self.assertEqual([args[:2] for args in sent], [('osd-overlay', 63), ('osd-overlay', 63)])
        self.assertEqual(sent[1][2], 'none')

    def test_other_live_game_skips_current_and_finished_games(self):
        games = [SimpleNamespace(id='1', state='live'), SimpleNamespace(id='2', state='upcoming'),
                 SimpleNamespace(id='3', state='live')]
        self.assertEqual(breaks.other_live_game(games, '1').id, '3')
        self.assertIsNone(breaks.other_live_game(games[:2], '1'))

    def test_corner_command_keeps_headers_and_drops_main_window_options(self):
        base = app.mpv_command('https://example.test/a.m3u8', {'Referer': 'https://example.test/'})
        base.insert(1, '--input-ipc-server=/tmp/x.sock'); base.insert(1, '--stream-record=/tmp/r.ts')
        command = breaks.corner_command(base)
        self.assertIn('--http-header-fields-append=Referer: https://example.test/', command)
        self.assertIn('--ontop', command)
        self.assertFalse([item for item in command if item.startswith(('--input-ipc-server', '--stream-record', '--title=Sports CLI'))
                          and item != '--title=Sports CLI preview'])
        self.assertEqual(command[-2:], ['--', 'https://example.test/a.m3u8'])

    def preview(self, resolve):
        started = []
        clock = [0.0]
        def popen(command, **kwargs):
            started.append(FakeProcess(command)); return started[-1]
        preview = breaks.CornerPreview('Other', resolve, lambda url, headers: ['mpv', url],
                                       popen=popen, clock=lambda: clock[0])
        return preview, started, clock

    def wait(self, preview):
        for _ in range(200):
            if not preview.resolving: return
            threading.Event().wait(.01)

    def test_preview_resolves_ahead_and_opens_only_during_breaks(self):
        calls = []
        preview, started, clock = self.preview(lambda: calls.append(1) or ('https://a/1.m3u8', {}))
        preview.prepare(); self.wait(preview)
        self.assertEqual(started, [])
        self.assertTrue(preview.show())
        self.assertEqual(started[0].command, ['mpv', 'https://a/1.m3u8'])
        self.assertFalse(preview.show())  # already open
        preview.hide()
        self.assertTrue(started[0].terminated)
        self.assertEqual(len(calls), 1)
        clock[0] = breaks.FRESH_FOR + 1
        self.assertFalse(preview.show())  # stale link: resolve again, then open
        self.wait(preview)
        self.assertEqual(len(calls), 2); self.assertEqual(len(started), 2)
        preview.close()
        self.assertTrue(started[1].terminated)
        self.assertFalse(preview.show())

    def test_preview_that_failed_to_play_is_resolved_again(self):
        calls = []
        preview, started, _ = self.preview(lambda: calls.append(1) or ('https://a/1.m3u8', {}))
        preview.prepare(); self.wait(preview)
        preview.show(); started[0].code = 1
        preview.hide(); self.wait(preview)
        self.assertEqual(len(calls), 2)

    def test_break_ending_while_resolving_does_not_open_window(self):
        gate = threading.Event()
        preview, started, _ = self.preview(lambda: gate.wait(2) and ('https://a/1.m3u8', {}))
        self.assertFalse(preview.show())
        preview.hide()
        gate.set(); self.wait(preview)
        self.assertEqual(started, [])
        preview.close()

    def test_resolver_failure_leaves_no_preview(self):
        preview, started, _ = self.preview(lambda: (_ for _ in ()).throw(OSError('gone')))
        self.assertFalse(preview.show()); self.wait(preview)
        self.assertEqual(started, [])
        self.assertIsInstance(preview.error, OSError)


class BreakHandlerTests(unittest.TestCase):
    def app(self, mode, games, terminal_video=False):
        return SimpleNamespace(ad_breaks=mode, feed_context='live', games=games, gi=0, config={},
                               terminal_video=terminal_video, cache=15,
                               resolve_feed=lambda feed: ('https://a/' + feed.label, {}))

    def games(self):
        return [SimpleNamespace(id='1', state='live', title='Lakers at Celtics'),
                SimpleNamespace(id='2', state='live', title='Knicks at Bulls')]

    def test_mute_only_adds_nothing(self):
        self.assertEqual(app.App.break_handler(self.app('mute', self.games())), (None, None))

    def test_cover_shows_and_hides_overlay(self):
        on_break, preview = app.App.break_handler(self.app('cover', self.games()))
        self.assertIsNone(preview)
        sent = []
        on_break(True, lambda *args: sent.append(args)); on_break(False, lambda *args: sent.append(args))
        self.assertIn('Lakers at Celtics', sent[0][3])
        self.assertEqual(sent[1][2], 'none')

    def test_corner_resolves_the_other_live_game(self):
        seen = []
        def fetch(game, config):
            seen.append(game.id)
            return [app.Feed('S', 'web', kind='web'), app.Feed('S', 'one', url='u', kind='direct')], []
        with unittest.mock.patch.object(app, 'fetch_feeds', fetch):
            on_break, preview = app.App.break_handler(self.app('corner', self.games()))
            for _ in range(200):
                if preview.source: break
                threading.Event().wait(.01)
        self.assertEqual(seen, ['2'])
        self.assertEqual(preview.source, ('https://a/one', {}))
        sent = []
        with unittest.mock.patch.object(preview, 'popen', lambda command, **kwargs: FakeProcess(command)):
            on_break(True, lambda *args: sent.append(args))
            self.assertIn('Knicks at Bulls is in the corner', sent[0][3])
            self.assertIn('--ontop', preview.process.command)
            on_break(False, lambda *args: sent.append(args))
        preview.close()

    def test_corner_without_another_game_falls_back_to_break_screen(self):
        on_break, preview = app.App.break_handler(self.app('corner', self.games()[:1]))
        self.assertIsNone(preview)
        sent = []
        on_break(True, lambda *args: sent.append(args))
        self.assertIn('No other live game', sent[0][3])


if __name__ == '__main__':
    unittest.main()
