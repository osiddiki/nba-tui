import datetime as dt
import unittest
from unittest.mock import patch
import nba

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.start = dt.datetime(2026, 10, 29, 2, 30, tzinfo=dt.timezone.utc)
        self.game = nba.Game('1', 'Los Angeles Lakers at LA Clippers', self.start,
                             'LA Clippers', 'Los Angeles Lakers', 'Clippers', 'Lakers')

    def test_match_requires_both_teams(self):
        self.assertTrue(nba.title_matches('Los Angeles Lakers vs. LA Clippers', self.game))
        self.assertFalse(nba.title_matches('Los Angeles Lakers vs. Chicago Bulls', self.game))
        self.assertFalse(nba.title_matches('LA Clippers vs. Chicago Bulls', self.game))

    def test_feed_sides_and_time_matching(self):
        def event(start):
            return {'name': 'Lakers vs Clippers', 'starts_at': int(start.timestamp()),
                    'iframe': 'https://example.com/embed/game', 'source_tag': 'KTLA (Home)',
                    'substreams': [{'iframe': 'https://example.com/embed/away', 'source_tag': 'League Pass (Away)'}]}
        data = {'streams': [{'streams': [event(self.start), event(self.start + dt.timedelta(days=2))]}]}
        feeds = nba.ppv_feeds(data, self.game)
        self.assertEqual([(f.side, f.kind) for f in feeds], [('home', 'ppv'), ('away', 'ppv')])
        self.assertEqual(self.game.lakers_side, 'away')

    def test_scoreboard_handles_any_team_and_broadcasts(self):
        data = {'events': [{'id':'x', 'date':'2026-10-28T23:00Z', 'name':'Miami Heat at Atlanta Hawks',
                            'competitions':[{'competitors':[{'homeAway':'home', 'team':{'name':'Hawks','displayName':'Atlanta Hawks'}},
                                                            {'homeAway':'away', 'team':{'name':'Heat','displayName':'Miami Heat'}}],
                                              'broadcasts':[{'market':'away','names':['Example TV']}]}]}]}
        g, = nba.games_from_espn(data)
        self.assertTrue(nba.title_matches('Miami Heat vs. Atlanta Hawks', g))
        self.assertEqual(g.broadcasts, ['Example TV (Away)'])
        self.assertEqual(g.lakers_side, '')

    def test_fetch_streams_is_game_specific_and_reports_source_failure(self):
        def fetch(url, **kwargs):
            if url == nba.PPV:
                return {'streams':[{'streams':[{'name':'Lakers vs Clippers', 'starts_at':int(self.start.timestamp()),
                    'iframe':'https://example.com/embed/game', 'source_tag':'Home'}]}]}
            raise OSError('unavailable')
        with patch.object(nba, 'request', side_effect=fetch):
            feeds, errors = nba.fetch_feeds(self.game, {})
        self.assertEqual(len(feeds), 1)
        self.assertTrue(errors[0].startswith('StreamFree:'))

    def test_streamfree_presents_each_source_and_resolves_fresh_tokens(self):
        key = 'los-angeles-lakers-vs-la-clippers'
        base = nba.SF_ROOT
        source = f'https://strmfree.st/embed/basketball/{key}1080p2'
        listing = {'streams': {'basketball': [{'name':'Lakers vs Clippers', 'stream_key':key,
                                               'match_timestamp':int(self.start.timestamp())}]}}
        def fake_request(url, **kwargs):
            if '/api/v1/sources/' in url:
                return {'sources':[source], 'live_sources':[source]}
            if '/get-stream-key/' in url:
                return {'server_name':'cdn'}
            raise AssertionError(url)
        page = 'const _0x = {"1080p":{"_t":"fresh","_e":123,"_n":"nonce"}};'
        with patch.object(nba, 'request', side_effect=fake_request), patch.object(nba, 'request_text', return_value=page):
            feed, = nba.sf_feeds(listing, self.game)
            self.assertEqual(feed.label, 'Source 2 | 1080p | live')
            self.assertEqual(feed.kind, 'sf')
            url, headers = nba.resolve_streamfree(feed)
        self.assertTrue(url.startswith(f'{base}/live-cdn/{key}1080p2/index.m3u8?'))
        self.assertIn('_t=fresh', url)
        self.assertEqual(headers['Referer'], f'{base}/embed/basketball/{key}1080p2')

    def test_mpv_headers_are_arguments_not_shell_and_reject_injection(self):
        command = nba.mpv_command('https://example.com/a.m3u8',
                                  {'Referer':'https://example.com/', 'Bad\nHeader':'x', 'X-Unsafe':'a\nb'})
        self.assertIn('--http-header-fields-append=Referer: https://example.com/', command)
        self.assertFalse(any('Bad' in x or 'Unsafe' in x for x in command))
        self.assertEqual(command[-2:], ['--', 'https://example.com/a.m3u8'])

if __name__ == '__main__':
    unittest.main()
