import datetime as dt
import unittest
from unittest.mock import patch
import nba
import providers
import relay
import gzip
import http.server
import io
import struct
import zlib
import threading
import time
import urllib.error
from types import SimpleNamespace
import grading
import replays

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

    def test_ppv_omits_expired_events(self):
        event = {'name':'Lakers vs Clippers', 'starts_at':int(self.start.timestamp()),
                 'ends_at':int((self.start+dt.timedelta(hours=3)).timestamp()),
                 'iframe':'https://example.com/embed', 'source_tag':'Home'}
        data = {'streams':[{'streams':[event]}]}
        self.assertEqual(len(nba.ppv_feeds(data,self.game,now=self.start)),1)
        self.assertEqual(nba.ppv_feeds(data,self.game,now=self.start+dt.timedelta(hours=4)),[])
        event['always_live'] = 1
        self.assertEqual(len(nba.ppv_feeds(data,self.game,now=self.start+dt.timedelta(hours=4))),1)

    def test_scoreboard_handles_any_team_and_broadcasts(self):
        data = {'events': [{'id':'x', 'date':'2026-10-28T23:00Z', 'name':'Miami Heat at Atlanta Hawks',
                            'competitions':[{'competitors':[{'homeAway':'home', 'team':{'name':'Hawks','displayName':'Atlanta Hawks'}},
                                                            {'homeAway':'away', 'team':{'name':'Heat','displayName':'Miami Heat'}}],
                                              'broadcasts':[{'market':'away','names':['Example TV']}]}]}]}
        g, = nba.games_from_espn(data)
        self.assertTrue(nba.title_matches('Miami Heat vs. Atlanta Hawks', g))
        self.assertEqual(g.broadcasts, ['Example TV (Away)'])
        self.assertEqual(g.lakers_side, '')

    def test_finished_events_are_hidden_without_hiding_delayed_games(self):
        def event(ident, status):
            return {'id': ident, 'date':'2026-10-28T23:00Z', 'name':'Sparks at Sun',
                    'status':{'type':status}, 'competitions':[{'competitors':[
                        {'homeAway':'home','team':{'name':'Sun','displayName':'Connecticut Sun'}},
                        {'homeAway':'away','team':{'name':'Sparks','displayName':'Los Angeles Sparks'}}]}]}
        data = {'events':[event('final',{'state':'post','completed':True}),
                          event('delayed',{'state':'pre','completed':False}),
                          event('live',{'state':'in','completed':False}),
                          event('unknown',{})]}
        self.assertEqual({g.id for g in nba.games_from_espn(data,league='wnba')}, {'delayed','live','unknown'})

    def test_fetch_streams_is_game_specific_and_reports_source_failure(self):
        def fetch(url, **kwargs):
            if url == nba.PPV:
                return {'streams':[{'streams':[{'name':'Lakers vs Clippers', 'starts_at':int(self.start.timestamp()),
                    'iframe':'https://example.com/embed/game', 'source_tag':'Home'}]}]}
            raise OSError('unavailable')
        with patch.object(nba, 'request', side_effect=fetch), patch.object(nba, 'monster_feeds', return_value=[]), patch.object(nba, 'directory_feeds', return_value=[]), patch.object(nba, 'ntv_feeds', return_value=[]):
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

    def test_streamfree_omits_sources_marked_not_live(self):
        key = 'lakers-vs-clippers'
        active = f'https://strmfree.st/embed/basketball/{key}1080p1'
        inactive = f'https://strmfree.st/embed/basketball/{key}1080p2'
        listing = {'streams':{'basketball':[{'name':'Lakers vs Clippers','stream_key':key,
                                            'match_timestamp':int(self.start.timestamp())}]}}
        with patch.object(nba, 'request', return_value={'sources':[active,inactive],'live_sources':[active]}):
            feeds = nba.sf_feeds(listing,self.game)
        self.assertEqual([f.label for f in feeds], ['Source 1 | 1080p | live'])
        with patch.object(nba, 'request', return_value={'sources':[active,inactive],'live_sources':[]}):
            self.assertEqual(nba.sf_feeds(listing,self.game), [])
        with patch.object(nba, 'request', return_value={'sources':[active]}):
            self.assertEqual(nba.sf_feeds(listing,self.game)[0].label, 'Source 1 | 1080p | status unknown')

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

    def test_streamfree_png_chunk_is_unwrapped_and_relayed(self):
        ts = (b'\x47' + b'\x00'*187) * 3
        def chunk(kind, value):
            return struct.pack('>I',len(value)) + kind + value + struct.pack('>I',zlib.crc32(kind+value))
        ihdr = struct.pack('>IIBBBBB',1,1,8,6,0,0,0)
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR',ihdr) + chunk(b'IDAT',zlib.compress(b'\x00'*5)) + chunk(b'tsDa',ts) + chunk(b'IEND',b'')
        self.assertEqual(relay.unwrap_segment(png), ts)
        manifest = '#EXTM3U\n#EXTINF:4,\nsegment.png\n'
        server = relay.Relay()
        try:
            url = server.add_streamfree('https://example.com/stream.m3u8', 'https://example.com/player',
                                        lambda: ('https://example.com/fresh.m3u8',{}), manifest)
            path = '/' + url.split('/', 3)[-1]
            with patch.object(relay, '_download', return_value=png):
                playlist, _ = server.get(path)
                segment = next(line for line in playlist.decode().splitlines() if line.startswith('http'))
                media, content_type = server.get('/' + segment.split('/', 3)[-1])
            self.assertEqual(media, ts)
            self.assertEqual(content_type, 'video/mp2t')
        finally:
            server.close()

    def test_streamfree_detects_wrapped_segments_and_preserves_direct_streams(self):
        def chunk(kind, value):
            return struct.pack('>I',len(value)) + kind + value + struct.pack('>I',zlib.crc32(kind+value))
        ihdr = struct.pack('>IIBBBBB',1,1,8,6,0,0,0)
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR',ihdr) + chunk(b'IDAT',zlib.compress(b'\x00'*5)) + chunk(b'tsDa',(b'\x47'+b'\x00'*187)*3)
        manifest = '#EXTM3U\n#EXTINF:4,\nsegment.png\n'
        opener = SimpleNamespace(open=lambda *a, **kw: io.BytesIO(png))
        with patch.object(nba.urllib.request, 'build_opener', return_value=opener):
            self.assertTrue(nba.streamfree_wraps_segments('https://example.com/live.m3u8',manifest,{}))
        opener = SimpleNamespace(open=lambda *a, **kw: io.BytesIO(b'\x47'+b'\x00'*187))
        with patch.object(nba.urllib.request, 'build_opener', return_value=opener):
            self.assertFalse(nba.streamfree_wraps_segments('https://example.com/live.m3u8',manifest,{}))

    def test_streamfree_relay_renews_rejected_playlist_token(self):
        server = relay.Relay()
        denied = urllib.error.HTTPError('https://example.com/old.m3u8',403,'expired',{},None)
        renewed = ('https://example.com/fresh.m3u8', {'Referer':'https://example.com/new-player'})
        try:
            url = server.add_streamfree('https://example.com/old.m3u8', 'https://example.com/player', lambda: renewed)
            path = '/' + url.split('/',3)[-1]
            with patch.object(relay, '_download', side_effect=[denied,b'#EXTM3U\n#EXTINF:4,\nsegment.png\n']) as download, \
                 patch.object(relay.time, 'sleep'):
                playlist, _ = server.get(path)
            self.assertIn(b'/segment/',playlist)
            self.assertEqual(download.call_args_list[1].args[:2], (renewed[0], renewed[1]['Referer']))
        finally:
            server.close()

    def test_progressive_loading_preserves_user_selection(self):
        slow_gate = threading.Event()
        fast_feed = nba.Feed('Fast', 'One', url='https://example.com/a', kind='direct')
        other_feed = nba.Feed('Slow', 'Two', url='https://example.com/b', kind='direct')
        def slow():
            if not slow_gate.wait(2): raise RuntimeError('timed out')
            return [other_feed]
        app = nba.App(None,{})
        app.games = [self.game]; app.mode = 'feeds'
        probe_patcher = patch.object(app, 'start_auto_checks')
        probe_patcher.start(); self.addCleanup(probe_patcher.stop)
        try:
            # Slow source sorts first, but the fast one should appear immediately.
            with patch.object(nba, 'feed_tasks', return_value=[('Slow',slow),('Fast',lambda:[fast_feed])]):
                app.refresh_feeds()
            end = time.monotonic() + 1
            while not app.feeds and time.monotonic() < end:
                app.poll_feeds(); time.sleep(.01)
            self.assertEqual(app.visible_feeds(),[fast_feed])
            self.assertEqual(app.feed_pending,1)
            app.feed_selection_touched = True
            slow_gate.set()
            end = time.monotonic() + 1
            while app.feed_pending and time.monotonic() < end:
                app.poll_feeds(); time.sleep(.01)
            self.assertEqual(app.visible_feeds(),[other_feed,fast_feed])
            self.assertEqual(app.visible_feeds()[app.fi],fast_feed)
            app.feed_search='two'
            self.assertEqual(app.visible_feeds(),[other_feed])
        finally:
            slow_gate.set()

    def test_stale_feed_results_are_ignored(self):
        app = nba.App(None,{})
        app.games = [self.game]; app.mode = 'feeds'; app.feed_generation = 2
        app.feed_pending = 1; app.feed_order = ['New']
        app.feed_queue.put((1,'Old',[nba.Feed('Old','Old')],None))
        app.feed_queue.put((2,'New',[nba.Feed('New','New')],None))
        app.poll_feeds()
        self.assertEqual([f.label for f in app.feeds],['New'])
        self.assertEqual(app.feed_pending,0)

    def test_help_keeps_progressive_results(self):
        app = nba.App(None,{})
        app.games = [self.game]; app.mode = 'help'; app.help_return = 'feeds'
        app.feed_generation = 1; app.feed_pending = 1; app.feed_order = ['Source']
        app.feed_queue.put((1,'Source',[nba.Feed('Source','One')],None))
        app.poll_feeds()
        self.assertEqual([f.label for f in app.feeds], ['One'])
        self.assertEqual(app.feed_pending, 0)

    def test_failed_feed_is_hidden_until_refresh_but_missing_dependency_is_not(self):
        app = nba.App(None,{})
        app.games = [self.game]; app.mode = 'feeds'
        probe_patcher = patch.object(app, 'start_auto_checks')
        probe_patcher.start(); self.addCleanup(probe_patcher.stop)
        dead = nba.Feed('Source','Dead',url='https://example.com/a',kind='direct')
        good = nba.Feed('Source','Good',url='https://example.com/b',kind='direct')
        app.feeds = [dead,good]
        with patch.object(app,'render'), patch.object(app,'resolve_feed',side_effect=OSError('offline')), \
             patch.object(nba,'save_config'):
            app.test_feed(dead)
        self.assertEqual(app.visible_feeds(), [good])
        self.assertIn('hidden until refresh', app.message)
        self.assertEqual(app.config['health']['Source:Dead']['checks'], [False])
        with patch.object(nba,'feed_tasks',return_value=[('Source',lambda: [dead,good])]):
            app.refresh_feeds()
        end = time.monotonic() + 1
        while app.feed_pending and time.monotonic() < end:
            app.poll_feeds(); time.sleep(.01)
        self.assertEqual(app.visible_feeds(), [dead,good])
        with patch.object(app,'render'), patch.object(app,'resolve_feed',side_effect=nba.DependencyError('Install resolver')), \
             patch.object(nba,'save_config'):
            app.test_feed(good)
        self.assertEqual(app.visible_feeds(), [dead,good])
        self.assertEqual(app.message, 'Install resolver')

    def test_automatic_checks_are_bounded_and_keep_transient_failures_visible(self):
        app = nba.App(None,{})
        app.games = [self.game]; app.mode = 'feeds'; app.feed_generation = 1
        feeds = [nba.Feed('Source', name, url='https://example.com/' + name, kind='direct')
                 for name in ('one', 'two', 'three')]
        app.feeds = feeds
        def probe(feed):
            if feed.label == 'two':
                raise urllib.error.HTTPError(feed.url, 403, 'forbidden', {}, None)
            return True
        with patch.object(nba, 'quick_probe_feed', side_effect=probe) as check:
            app.start_auto_checks(1, feeds)
            end = time.monotonic() + 1
            while 'checking' in app.auto_checks.values() and time.monotonic() < end:
                app.poll_auto_checks(); time.sleep(.01)
        self.assertEqual(check.call_count, 2)
        self.assertEqual(app.auto_checks[id(feeds[0])], 'OK')
        self.assertEqual(app.auto_checks[id(feeds[1])], 'HTTP 403')
        self.assertNotIn(id(feeds[2]), app.auto_checks)
        self.assertEqual(app.visible_feeds(), feeds)
        self.assertNotIn('health', app.config)

    def test_mpv_headers_are_arguments_not_shell_and_reject_injection(self):
        command = nba.mpv_command('https://example.com/a.m3u8',
                                  {'Referer':'https://example.com/', 'Bad\nHeader':'x', 'X-Unsafe':'a\nb'})
        self.assertIn('--http-header-fields-append=Referer: https://example.com/', command)
        self.assertFalse(any('Bad' in x or 'Unsafe' in x for x in command))
        self.assertEqual(command[-2:], ['--', 'https://example.com/a.m3u8'])

    def test_names_match_college_schools_and_soccer_clubs(self):
        def team(display, location, name, short):
            return {'displayName': display, 'location': location, 'name': name, 'shortDisplayName': short}
        def event(home, away, league):
            data = {'events': [{'date':'2026-10-28T23:00Z', 'competitions':[{'competitors':[
                {'homeAway':'home', 'team':home}, {'homeAway':'away', 'team':away}]}]}]}
            return nba.games_from_espn(data, league=league)[0]
        college = event(team('New Mexico State Aggies','New Mexico State','Aggies','New Mexico St'),
                        team('Jacksonville State Gamecocks','Jacksonville State','Gamecocks','Jax State'), 'ncaaf')
        self.assertTrue(nba.title_matches('Jacksonville St vs New Mexico State', college))
        self.assertFalse(nba.title_matches('Jacksonville State vs Texas A&M', college))
        soccer = event(team('Charlotte FC','Charlotte FC','Charlotte FC','Charlotte'),
                       team('CF Montréal','CF Montréal','CF Montréal','CF Montréal'), 'mls')
        self.assertTrue(nba.title_matches('Charlotte vs Montreal', soccer))
        self.assertFalse(nba.title_matches('Montreal vs Miami', soccer))
        same = event(team('Alpha Wildcats','Alpha','Wildcats','Alpha'),
                     team('Beta Wildcats','Beta','Wildcats','Beta'), 'ncaam')
        self.assertTrue(nba.title_matches('Alpha vs Beta', same))
        self.assertFalse(nba.title_matches('The Wildcats vs Gamma', same))

    def test_non_nba_categories_use_correct_directories_and_embeds(self):
        game = nba.Game('2','Charlotte FC vs CF Montréal',self.start,'Charlotte FC','CF Montréal',
                        'Charlotte FC','CF Montréal',league='mls',category='soccer')
        self.assertEqual([name for name, _ in nba.feed_tasks(game,{})], ['StreamFree','PPV','NTV'])
        key = 'charlotte-vs-montreal'
        listing = {'streams':{'soccer':[{'name':'Charlotte vs Montreal','stream_key':key,
                                        'match_timestamp':int(self.start.timestamp())}]}}
        source = f'https://strmfree.st/embed/soccer/{key}720p2'
        with patch.object(nba, 'request', return_value={'sources':[source], 'live_sources':[source]}):
            feed, = nba.sf_feeds(listing,game)
        self.assertEqual(feed.metadata['category'], 'soccer')
        self.assertEqual(providers.extract_player(source)['category'], 'soccer')

    def test_ntv_returns_healthy_server_when_other_is_down(self):
        result = {'success':True, 'all':[{'title':'Lakers vs Clippers',
            'date':int(self.start.timestamp()*1000), 'sources':[{'url':'https://example.com/stream',
            'source':'1','channelName':'Home'}]}]}
        def fetch(url, **kwargs):
            if 'falcon' in url: raise OSError('down')
            return result
        with patch.object(nba, 'request', side_effect=fetch):
            feeds = nba.ntv_feeds(self.game)
        self.assertEqual([(f.source, f.side, f.kind) for f in feeds], [('NTV','home','candidate')])
        with patch.object(nba, 'request', side_effect=OSError('down')):
            with self.assertRaises(OSError): nba.ntv_feeds(self.game)
        result['all'][0]['live'] = False
        with patch.object(nba, 'request', return_value=result):
            self.assertEqual(nba.ntv_feeds(self.game), [])

    def test_iina_receives_headers_and_keeps_the_tui_running(self):
        url = 'https://example.com/stream.m3u8?a=1&b=2'
        headers = {'Referer':'https://example.com/', 'Bad\nHeader':'x', 'Origin':'https://example.com'}
        command = nba.iina_command('/Applications/IINA.app/Contents/MacOS/iina-cli', url, headers)
        self.assertEqual(command[-1], url)
        self.assertIn('--no-stdin', command)
        self.assertIn('--mpv-http-header-fields=Referer: https://example.com/,Origin: https://example.com', command)
        self.assertFalse(any('Bad' in x or 'keep-running' in x for x in command))
        app = nba.App(None, {'player':'iina'})
        feed = nba.Feed('Test','Test',url=url,kind='direct')
        with patch.object(nba, 'find_iina', return_value='/path/iina-cli'), \
             patch.object(app, 'render'), patch.object(app, 'resolve_feed', return_value=(url, headers)), \
             patch.object(nba.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as launch:
            app.play(feed)
        self.assertIn('Keep this terminal open', app.message)
        self.assertEqual(launch.call_args.args[0][-1], url)

    def test_linux_celluloid_launch_is_independent_and_keeps_headers(self):
        url = 'https://example.com/stream.m3u8?a=1&b=2'
        headers = {'Referer':'https://example.com/', 'Origin':'https://example.com',
                   'Unsafe':"x' --ytdl=yes", 'Other':'value\\n'}
        command = nba.celluloid_command('/usr/bin/celluloid', url, headers, cache=30)
        self.assertIn('--no-existing-session', command)
        self.assertIn('--mpv-cache-secs=30', command)
        self.assertIn('--mpv-http-header-fields=Referer: https://example.com/,Origin: https://example.com', command)
        self.assertFalse(any('Unsafe:' in x or 'Other:' in x for x in command))
        self.assertEqual(command[-1], url)
        app = nba.App(None, {'player':'celluloid'})
        process = SimpleNamespace(poll=lambda: None)
        feed = nba.Feed('Test','Test',url=url,kind='direct')
        with patch.object(nba, 'find_celluloid', return_value='/usr/bin/celluloid'), \
             patch.object(app, 'render'), patch.object(app, 'resolve_feed', return_value=(url, headers)), \
             patch.object(nba.subprocess, 'Popen', return_value=process) as launch:
            app.play(feed)
        self.assertIn('Keep this terminal open', app.message)
        self.assertEqual(launch.call_args.args[0], nba.celluloid_command('/usr/bin/celluloid', url, headers))
        self.assertTrue(launch.call_args.kwargs['start_new_session'])
        self.assertEqual(app.gui_players, [process])
        app.poll_gui_players()
        self.assertEqual(app.gui_players, [process])

    def test_wnba_league_is_loaded_only_after_selection(self):
        class Screen:
            def __init__(self): self.keys = iter([9, ord('r'), ord('j'), 10, ord('q')])
            def keypad(self, value): pass
            def timeout(self, value): pass
            def getch(self): return next(self.keys)
        app = nba.App(Screen(), {})
        with patch.object(nba.curses, 'curs_set'), patch.object(app, 'render'), \
             patch.object(nba, 'get_games', return_value=[]) as fetch:
            app.run()
        self.assertEqual([call.args[1] for call in fetch.call_args_list], ['wnba'])

    def test_lowercase_s_changes_sport_and_d_opens_resolver_settings(self):
        class Screen:
            def __init__(self): self.keys = iter([9, 10, 10, ord('s'), 27, ord('d'), ord('q')])
            def keypad(self, value): pass
            def timeout(self, value): pass
            def getch(self): return next(self.keys)
        app = nba.App(Screen(), {})
        modes = []
        with patch.object(nba.curses, 'curs_set'), patch.object(app, 'render', side_effect=lambda: modes.append(app.mode)), \
             patch.object(nba, 'get_games', return_value=[self.game]), patch.object(nba, 'feed_tasks', return_value=[]), \
             patch.object(app, 'configure_resolver') as resolver:
            app.run()
        self.assertEqual(modes[0], 'search')
        self.assertEqual(modes[-3:], ['leagues', 'feeds', 'feeds'])
        resolver.assert_called_once()

    def test_feed_loading_continues_while_sport_menu_is_open(self):
        app = nba.App(None,{})
        app.games = [self.game]; app.mode = 'leagues'; app.league_cancel = 'feeds'
        app.feed_generation = 1; app.feed_pending = 1; app.feed_order = ['Source']
        app.feed_queue.put((1, 'Source', [nba.Feed('Source','One')], None))
        app.poll_feeds()
        self.assertEqual([f.label for f in app.feeds], ['One'])
        self.assertEqual(app.feed_pending, 0)

    def test_replay_catalog_and_servers_are_discovered_on_demand(self):
        catalog = '<a href="/lakers-replay">Lakers vs Blazers NBA Full Game Replay</a>' \
                  '<a href="/wnba-replay">Dream vs Aces WNBA Full Game Replay</a>' \
                  '<a href="https://other.example/ad">Lakers vs Bulls NBA Replay</a>'
        article = '<p>Server #1</p><iframe src="https://video.example/e/abc"></iframe>' \
                  '<p><a class="myButton" href="https://video.example/e/xyz">Full Match</a></p>'
        def fetch(url, **kwargs):
            return (article if url.endswith('lakers-replay') else catalog, url)
        with patch.object(providers, 'fetch_html', side_effect=fetch):
            items = replays.listing(('Basketball Replays','https://example.com/','nba'))
            self.assertEqual(len(items),1)
            servers = replays.servers(items[0])
        self.assertEqual([s.url for s in servers], ['https://video.example/e/abc','https://video.example/e/xyz'])
        self.assertEqual(servers[0].referer, items[0].url)
        self.assertTrue(servers[1].label.startswith('Full Match'))

    def test_replay_player_api_produces_public_media_url(self):
        payload = b'{"streaming_url":"https://media.example/video/master.m3u8"}'
        calls = []
        def open_api(request, **kwargs):
            calls.append(request)
            return io.BytesIO(payload)
        with patch.object(providers.urllib.request, 'build_opener', return_value=SimpleNamespace(open=open_api)):
            found = providers.vidara_stream("fetch('/api/stream'); file=t.streaming_url", 'https://video.example/e/abc')
        self.assertEqual(found['url'], 'https://media.example/video/master.m3u8')
        self.assertEqual(calls[0].full_url, 'https://video.example/api/stream')
        self.assertIn(b'"filecode": "abc"', calls[0].data)
        self.assertIsNone(providers.vidara_stream('ordinary page', 'https://video.example/e/abc'))

    def test_relay_retries_temporary_errors_but_not_rejected_tokens(self):
        error = urllib.error.HTTPError('https://example.com', 502, 'unavailable', {}, None)
        with patch.object(relay.urllib.request, 'urlopen', side_effect=[error, io.BytesIO(b'OK')]) as fetch, \
             patch.object(relay.time, 'sleep'):
            self.assertEqual(relay._download('https://example.com/a','https://example.com/'), b'OK')
        self.assertEqual(fetch.call_count, 2)
        denied = urllib.error.HTTPError('https://example.com', 403, 'forbidden', {}, None)
        with patch.object(relay.urllib.request, 'urlopen', side_effect=denied) as fetch:
            with self.assertRaises(urllib.error.HTTPError):
                relay._download('https://example.com/a','https://example.com/')
        self.assertEqual(fetch.call_count, 1)

    def test_relay_refreshes_rejected_playlist_tokens(self):
        relay_server = relay.Relay()
        rejected = urllib.error.HTTPError('https://example.com/playlist', 403, 'expired', {}, None)
        token_fetches = []
        playlist_fetches = []
        def download(url, referer, **kwargs):
            if '/playlist-token?' in url:
                token_fetches.append(url)
                return b'{"token":"new","ttl":120}'
            playlist_fetches.append(url)
            if len(playlist_fetches) < 3: raise rejected
            return b'#EXTM3U\n#EXTINF:5,\nsegment.png\n'
        try:
            url = relay_server.add('https://example.com/live.m3u8', 'https://example.com',
                                   'channel', 'https://example.com/player')
            path = '/' + url.split('/', 3)[-1]
            with patch.object(relay, '_download', side_effect=download), patch.object(relay.time, 'sleep'):
                manifest, kind = relay_server.get(path)
            self.assertEqual(len(token_fetches), 3)
            self.assertEqual(len(playlist_fetches), 3)
            self.assertIn(b'/segment/', manifest)
            self.assertEqual(kind, 'application/vnd.apple.mpegurl')
        finally:
            relay_server.close()

    def test_relay_shares_one_playlist_between_concurrent_player_requests(self):
        relay_server = relay.Relay()
        downloads = []
        def download(url, referer, **kwargs):
            if '/playlist-token?' in url:
                return b'{"token":"new","ttl":120}'
            downloads.append(url)
            time.sleep(.05)
            return b'#EXTM3U\n#EXTINF:5,\nsegment.png\n'
        try:
            url = relay_server.add('https://example.com/live.m3u8', 'https://example.com',
                                   'channel', 'https://example.com/player')
            path = '/' + url.split('/', 3)[-1]
            with patch.object(relay, '_download', side_effect=download):
                results = []
                threads = [threading.Thread(target=lambda: results.append(relay_server.get(path))) for _ in range(4)]
                for thread in threads: thread.start()
                for thread in threads: thread.join()
            self.assertEqual(len(downloads),1)
            self.assertEqual(len(results),4)
            self.assertTrue(all(result == results[0] for result in results))
        finally:
            relay_server.close()

    def test_grading_checks_playlist_and_segment_without_saving_url(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                bodies = {'/master.m3u8':b'#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1280x720\nmedia.m3u8\n',
                          '/media.m3u8':b'#EXTM3U\n#EXTINF:6,\nvideo.ts\n',
                          '/video.ts':b'\x47' + b'\x00'*600,
                          '/private.m3u8':b'#EXTM3U\n#EXTINF:6,\nhttp://127.0.0.1:1/private\n'}
                body = bodies[self.path]
                self.send_response(200); self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)
        server = http.server.ThreadingHTTPServer(('127.0.0.1',0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with patch.object(grading.shutil, 'which', return_value=None):
                self.assertEqual(grading.inspect_stream(base+'/master.m3u8')['height'], 720)
                with self.assertRaisesRegex(ValueError, 'Private media'):
                    grading.inspect_stream(base+'/private.m3u8')
            fake_probe = SimpleNamespace(returncode=0, stdout=b'{"streams":[{"height":1}]}')
            with patch.object(grading.shutil, 'which', return_value='ffprobe'), \
                 patch.object(grading.subprocess, 'run', return_value=fake_probe):
                self.assertIsNone(grading.inspect_stream(base+'/media.m3u8')['height'])
        finally:
            server.shutdown(); server.server_close(); thread.join()
        feed = nba.Feed('StreamFree','Source 1 | 1080p | live',url='https://example.com/secret')
        self.assertNotIn('secret', grading.source_key(feed))
        self.assertEqual(grading.summary({'checks':[True,False], 'height':720}), '? 1/2 720p')
        self.assertEqual(grading.summary({'checks':[True,True,True]}), 'A 3/3')
        self.assertGreater(grading.score({'checks':[True,True,True]}), grading.score({}))

if __name__ == '__main__':
    unittest.main()
