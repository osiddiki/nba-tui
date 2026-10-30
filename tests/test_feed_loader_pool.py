import datetime as dt
import threading
import time
import unittest
from unittest.mock import patch

from sportscli import app as nba


class FeedLoaderPoolTests(unittest.TestCase):
    def test_repeated_refreshes_bound_work_and_keep_latest_results(self):
        app = nba.App(None, {})
        self.addCleanup(app.close)
        app.mode = 'feeds'
        app.games = [nba.Game('1', 'Away at Home', dt.datetime.now(dt.timezone.utc),
                              'Home', 'Away', 'Home', 'Away')]
        release, all_started = threading.Event(), threading.Event()
        lock = threading.Lock()
        active = 0
        peak = 0
        def operation():
            nonlocal active, peak
            with lock:
                active += 1; peak = max(peak, active)
                if active == 6: all_started.set()
            release.wait(3)
            with lock: active -= 1
            return [nba.Feed('Example', 'Ready', kind='direct')]
        tasks = [(f'Source {i}', operation) for i in range(6)]
        try:
            with patch.object(nba, 'feed_tasks', return_value=tasks), patch.object(app, 'start_auto_checks'):
                app.refresh_feeds()
                self.assertTrue(all_started.wait(1))
                for _ in range(20): app.refresh_feeds()
                self.assertEqual(len(app.feed_workers), 6)
                self.assertLessEqual(app.feed_jobs.qsize(), len(tasks))
                release.set()
                deadline = time.monotonic() + 3
                while app.feed_pending and time.monotonic() < deadline:
                    app.poll_feeds(); time.sleep(.01)
                self.assertEqual(app.feed_pending, 0)
                self.assertEqual(len(app.feeds), 6)
                self.assertLessEqual(peak, 6)
        finally:
            release.set()


if __name__ == '__main__':
    unittest.main()
