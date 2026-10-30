import threading
import time
import unittest
from unittest.mock import patch

from sportscli import app as nba


class FeedActionTests(unittest.TestCase):
    def setUp(self):
        self.app = nba.App(None, {})
        self.app.mode = 'feeds'; self.app.feed_generation = 1
        self.first = nba.Feed('Example', 'First', url='https://example.com/one', kind='direct')
        self.second = nba.Feed('Example', 'Second', url='https://example.com/two', kind='direct')
        self.app.feeds = [self.first, self.second]
        self.addCleanup(self.app.close)

    def wait_for_results(self):
        deadline = time.monotonic() + 3
        while self.app.action_inflight and time.monotonic() < deadline:
            self.app.poll_feed_actions(); time.sleep(.01)
        self.assertFalse(self.app.action_inflight, 'source resolution did not finish')

    def test_opening_resolves_in_background_then_starts_selected_player(self):
        started, release = threading.Event(), threading.Event()
        def resolve(feed):
            started.set(); release.wait(3)
            return feed.url, {'Referer':'https://example.com/'}
        try:
            with patch.object(self.app, 'player_ready', return_value=True), \
                 patch.object(self.app, 'resolve_feed', side_effect=resolve), \
                 patch.object(self.app, 'play') as play:
                start = time.monotonic()
                self.app.begin_feed_action(self.first, 'play')
                self.assertLess(time.monotonic()-start, .5)
                self.assertTrue(started.wait(1))
                play.assert_not_called()
                release.set(); self.wait_for_results()
                play.assert_called_once_with(self.first, resolved=(self.first.url, {'Referer':'https://example.com/'}))
        finally:
            release.set()

    def test_changing_selection_cancels_the_pending_open(self):
        started, release = threading.Event(), threading.Event()
        def resolve(feed):
            started.set(); release.wait(3)
            return feed.url, {}
        try:
            with patch.object(self.app, 'player_ready', return_value=True), \
                 patch.object(self.app, 'resolve_feed', side_effect=resolve), \
                 patch.object(self.app, 'play') as play:
                self.app.begin_feed_action(self.first, 'play')
                self.assertTrue(started.wait(1))
                self.app.fi = 1
                release.set(); self.wait_for_results()
                play.assert_not_called()
                self.assertIn('canceled', self.app.message)
        finally:
            release.set()

    def test_stale_failure_does_not_hide_refreshed_source(self):
        started, release = threading.Event(), threading.Event()
        def resolve(feed):
            started.set(); release.wait(3)
            raise OSError('offline')
        try:
            with patch.object(self.app, 'player_ready', return_value=True), \
                 patch.object(self.app, 'resolve_feed', side_effect=resolve), \
                 patch.object(self.app, 'play') as play:
                self.app.begin_feed_action(self.first, 'play')
                self.assertTrue(started.wait(1))
                self.app.feed_generation += 1; self.app.message = 'Refreshed.'
                release.set(); self.wait_for_results()
                play.assert_not_called()
                self.assertEqual(self.app.visible_feeds(), [self.first, self.second])
                self.assertEqual(self.app.message, 'Refreshed.')
        finally:
            release.set()

    def test_moving_away_then_back_does_not_restore_a_canceled_open(self):
        started, release = threading.Event(), threading.Event()
        def resolve(feed):
            started.set(); release.wait(3)
            return feed.url, {}
        try:
            with patch.object(self.app, 'player_ready', return_value=True), \
                 patch.object(self.app, 'resolve_feed', side_effect=resolve), \
                 patch.object(self.app, 'play') as play:
                self.app.begin_feed_action(self.first, 'play')
                self.assertTrue(started.wait(1))
                self.app.fi = 1
                self.app.cancel_feed_action_if_changed()
                self.app.fi = 0
                release.set(); self.wait_for_results()
                play.assert_not_called()
                self.assertIn('canceled', self.app.message)
        finally:
            release.set()

    def test_leaving_the_source_list_discards_a_completed_open(self):
        started, release = threading.Event(), threading.Event()
        def resolve(feed):
            started.set(); release.wait(3)
            return feed.url, {}
        try:
            with patch.object(self.app, 'player_ready', return_value=True), \
                 patch.object(self.app, 'resolve_feed', side_effect=resolve), \
                 patch.object(self.app, 'play') as play:
                self.app.begin_feed_action(self.first, 'play')
                self.assertTrue(started.wait(1))
                self.app.mode = 'search'; self.app.message = 'Search.'
                release.set(); self.wait_for_results()
                play.assert_not_called()
                self.assertEqual(self.app.message, 'Search.')
        finally:
            release.set()

    def test_latest_request_wins_and_inspection_is_on_ui_thread(self):
        first_started, release = threading.Event(), threading.Event()
        def resolve(feed):
            if feed is self.first:
                first_started.set(); release.wait(3)
            return feed.url, {}
        try:
            with patch.object(self.app, 'player_ready', return_value=True), \
                 patch.object(self.app, 'resolve_feed', side_effect=resolve), \
                 patch.object(self.app, 'play') as play, patch.object(self.app, 'show_stream_url') as show:
                self.app.begin_feed_action(self.first, 'play')
                self.assertTrue(first_started.wait(1))
                self.app.fi = 1
                self.app.begin_feed_action(self.second, 'inspect')
                release.set(); self.wait_for_results()
                play.assert_not_called()
                show.assert_called_once_with(self.second.url, {})
        finally:
            release.set()

    def test_missing_player_does_not_start_network_resolution(self):
        with patch.object(self.app, 'player_ready', return_value=False), \
             patch.object(self.app, 'resolve_feed') as resolve:
            self.app.begin_feed_action(self.first, 'play')
        self.assertFalse(self.app.action_inflight)
        resolve.assert_not_called()

    def test_open_failure_hides_dead_source_but_not_missing_dependency(self):
        with patch.object(self.app, 'player_ready', return_value=True), \
             patch.object(self.app, 'resolve_feed', side_effect=nba.DependencyError('Install resolver')):
            self.app.begin_feed_action(self.first, 'play')
            self.wait_for_results()
        self.assertEqual(self.app.visible_feeds(), [self.first, self.second])
        self.assertEqual(self.app.message, 'Install resolver')
        with patch.object(self.app, 'player_ready', return_value=True), \
             patch.object(self.app, 'resolve_feed', side_effect=OSError('offline')):
            self.app.begin_feed_action(self.first, 'play')
            self.wait_for_results()
        self.assertEqual(self.app.visible_feeds(), [self.second])
        self.assertIn('hidden until refresh', self.app.message.lower())


if __name__ == '__main__':
    unittest.main()
