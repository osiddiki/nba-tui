import http.server
import threading
import unittest

from sportscli import ad_mute, app as nba


PLAYLIST = '''#EXTM3U
#EXT-X-VERSION:3
#EXTINF:2.5,
one.ts
#EXTINF:2.5,
two.ts
#EXT-X-CUE-OUT:5
#EXTINF:3,
ad1.ts
#EXTINF:2,
ad2.ts
#EXT-X-CUE-IN
#EXTINF:4,
three.ts
#EXT-X-ENDLIST
'''


class AdMuteTests(unittest.TestCase):
    def test_ad_mute_requires_explicit_run_flag_even_with_old_config(self):
        self.assertFalse(nba.App(None, {'ad_mute': True}).ad_mute)
        self.assertTrue(nba.App(None, {}, ad_mute_enabled=True).ad_mute)

    def test_cues_are_only_used_for_complete_playlists(self):
        self.assertEqual(ad_mute.cue_intervals(PLAYLIST), [(5.0, 10.0)])
        self.assertEqual(ad_mute.cue_intervals(PLAYLIST.replace('#EXT-X-ENDLIST', '')), [])
        self.assertEqual(ad_mute.cue_intervals(PLAYLIST.replace('#EXT-X-CUE-OUT:5', '# no cue')), [])
        unfinished = PLAYLIST.replace('#EXT-X-CUE-IN', '# no cue')
        self.assertEqual(ad_mute.cue_intervals(unfinished), [(5.0, 10.0)])

    def test_only_undoes_its_own_mute_and_respects_manual_unmute(self):
        state = ad_mute.MuteState()
        self.assertIsNone(state.update(False, False))
        self.assertTrue(state.update(True, False))
        self.assertIsNone(state.update(True, True))
        self.assertFalse(state.update(False, True))
        self.assertIsNone(state.update(True, True))
        self.assertIsNone(state.update(False, True))
        self.assertTrue(state.update(True, False))
        self.assertIsNone(state.update(True, False))  # User unmuted mid-break.
        self.assertIsNone(state.update(False, False))

    def test_follows_hls_variant_and_fetches_cues_locally(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/master.m3u8':
                    body = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1280x720\nvideo.m3u8\n'
                elif self.path == '/video.m3u8': body = PLAYLIST
                else:
                    self.send_error(404); return
                body = body.encode()
                self.send_response(200); self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)

            def log_message(self, *args): pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/master.m3u8'
            self.assertEqual(ad_mute.marked_replay_intervals(url), [(5.0, 10.0)])
        finally:
            server.shutdown(); server.server_close(); worker.join()


if __name__ == '__main__':
    unittest.main()
