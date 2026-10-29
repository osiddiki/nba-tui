import datetime as dt
import unittest
from unittest.mock import patch
import nba
import providers
import relay
import gzip
import struct
import zlib

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
        with patch.object(nba, 'request', side_effect=fetch), patch.object(nba, 'monster_feeds', return_value=[]), patch.object(nba, 'directory_feeds', return_value=[]):
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

    def test_directory_matches_event_and_skips_other_matchups(self):
        card = f'<a class="card" href="/game/1"><span data-cd="{int(self.start.timestamp())}">Live</span><span>LA Clippers</span><span>Los Angeles Lakers</span></a>'
        def row(name, url, channel):
            return '<tr>' + ''.join(f'<td class="{cls}"><a href="{url}">{text}</a></td>' for cls,text in [('', 'x'),('who',name),('','Gold'),('','HD'),('','English'),('','2'),('',channel)]) + '</tr>'
        table = row('OK','https://example.com/lakers-vs-clippers/','Spectrum SportsNet USA') + row('Wrong','https://example.com/lakers-vs-celtics/','Other')
        def fetch(url, *args, **kwargs):
            return (card if url == providers.NBABITE + '/' else table, url)
        with patch.object(providers, 'fetch_html', side_effect=fetch):
            results=providers.nbabite_entries(self.game, nba.title_matches)
        self.assertEqual([r['name'] for r in results], ['OK'])
        self.game.broadcasts=['Spectrum Sports Net (Away)']
        self.assertEqual(nba.channel_side(results[0]['channel'], self.game), 'away')

    def test_candidate_follows_iframes_and_finds_tokenized_player(self):
        pages = {
            'https://one.example/watch':'<iframe src="https://two.example/player"></iframe>',
            'https://two.example/player': 'const SRC="https://edge.example/a/index.m3u8"; const EDGE="https://edge.example"; const CHANNEL="premium982"; fetch("/api/playlist-token");'
        }
        with patch.object(providers, 'fetch_html', side_effect=lambda url, *a, **kw:(pages[url],url)):
            result=providers.extract_player('https://one.example/watch')
        self.assertEqual(result['kind'], 'relay')
        self.assertEqual(result['channel'], 'premium982')
        self.assertFalse(providers.public_url('http://127.0.0.1/private'))

    def test_image_wrapped_transport_stream(self):
        ts = b'\x47' + b'\x00'*187 + b'\x47' + b'\x00'*187
        payload = gzip.compress(ts)
        rgb = b'TIKTIKPX' + struct.pack('>I',len(payload)) + payload
        rgb += b'\x00' * (-len(rgb) % 3)
        def chunk(kind, value):
            return struct.pack('>I',len(value)) + kind + value + struct.pack('>I',zlib.crc32(kind+value))
        ihdr=struct.pack('>IIBBBBB',len(rgb)//3,1,8,2,0,0,0)
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',ihdr)+chunk(b'IDAT',zlib.compress(b'\x00'+rgb))+chunk(b'IEND',b'')
        self.assertEqual(relay.unwrap_segment(png),ts)

    def test_mpv_headers_are_arguments_not_shell_and_reject_injection(self):
        command = nba.mpv_command('https://example.com/a.m3u8',
                                  {'Referer':'https://example.com/', 'Bad\nHeader':'x', 'X-Unsafe':'a\nb'})
        self.assertIn('--http-header-fields-append=Referer: https://example.com/', command)
        self.assertFalse(any('Bad' in x or 'Unsafe' in x for x in command))
        self.assertEqual(command[-2:], ['--', 'https://example.com/a.m3u8'])

if __name__ == '__main__':
    unittest.main()
