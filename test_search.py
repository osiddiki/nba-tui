import datetime as dt
import time
import unittest
from unittest.mock import patch

import nba
import replays
import smart_search as search


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = search.default_index()
        cls.today = dt.date(2026, 10, 28)
        start = dt.datetime(2026, 10, 28, 23, tzinfo=dt.timezone.utc)
        cls.mavs = nba.Game('1', 'Dallas Mavericks at Houston Rockets', start,
                             'Houston Rockets', 'Dallas Mavericks', 'Rockets', 'Mavericks',
                             league='nba', state='live')
        cls.lakers = nba.Game('2', 'Los Angeles Lakers at LA Clippers', start,
                               'LA Clippers', 'Los Angeles Lakers', 'Clippers', 'Lakers',
                               league='nba', state='live')
        cls.archived = [
            ('nba', replays.Replay('Basketball Replays',
                'Portland Trail Blazers vs. Los Angeles Lakers - NBA Full Game Replay - 27 October 2026',
                'https://example.com/lakers-blazers')),
            ('nba', replays.Replay('Basketball Replays',
                'Los Angeles Lakers vs. Miami Heat - NBA Full Game Replay - October 26, 2026',
                'https://example.com/lakers-heat')),
            ('ncaaf', replays.Replay('NFL Video',
                'Texas A&M Aggies vs. Alabama Crimson Tide - College Football - October 24, 2026',
                'https://example.com/tamu-alabama')),
        ]

    def results(self, text):
        query = search.parse_query(text, self.today)
        plan = search.make_plan(self.index, query)
        return plan, search.rank(self.index, plan, [self.mavs, self.lakers], self.archived, self.today)

    def test_partial_prefix_suggests_mavs_and_ranks_live_first(self):
        plan, hits = self.results('ma')
        self.assertEqual(plan.primary.display, 'Dallas Mavericks')
        self.assertEqual(hits[0].kind, 'live')
        self.assertEqual(hits[0].item, self.mavs)
        self.assertIn('Dallas Mavericks', [hit.title for hit in hits if hit.kind == 'team'])

    def test_aliases_and_matchup_intent(self):
        for query in ('mavs vs rockets', 'mavs rockets'):
            plan, hits = self.results(query)
            self.assertEqual(plan.leagues, ('nba',))
            self.assertEqual([(hit.kind, hit.item) for hit in hits], [('live', self.mavs)])
        plan, hits = self.results('tamu vs alabama')
        self.assertEqual(plan.leagues[0], 'ncaaf')
        self.assertEqual([hit.item.url for hit in hits if hit.kind == 'replay'], ['https://example.com/tamu-alabama'])

    def test_incomplete_second_team_keeps_first_team_results(self):
        plan, hits = self.results('mavs vs r')
        self.assertEqual(plan.query.fragments, ('mavs',))
        self.assertEqual(hits[0].item, self.mavs)

    def test_date_and_live_replay_intent(self):
        plan, hits = self.results('lakers game today')
        self.assertEqual(plan.query.date, self.today)
        self.assertEqual([(hit.kind, hit.item) for hit in hits], [('live', self.lakers)])
        for query in ('lakers vs blazers oct 27', 'lakers vs blazers 10/27',
                      'lakers vs blazers 2026-10-27'):
            plan, hits = self.results(query)
            self.assertEqual(plan.query.date, dt.date(2026,10,27))
            self.assertEqual([hit.item.url for hit in hits], ['https://example.com/lakers-blazers'])
        self.assertEqual(search.parse_query('lakers last night', self.today).date, dt.date(2026,10,27))
        self.assertEqual(search.parse_query('lakers last night', self.today).intent, 'replay')
        self.assertEqual(search.parse_query('mavs tomorrow', self.today).intent, 'live')

    def test_typos_and_full_names_match_without_changing_meaning(self):
        for query in ('lakerz vs blazers oct 27', 'xakers vs blazers oct 27'):
            _, hits = self.results(query)
            self.assertEqual([hit.item.url for hit in hits], ['https://example.com/lakers-blazers'])
        plan, hits = self.results('los angeles lakers')
        self.assertEqual(plan.query.fragments, ('los angeles lakers',))
        self.assertEqual(hits[0].item, self.lakers)

    def test_flexible_replay_dates_and_nearest_year(self):
        for title in ('Lakers vs Blazers October 27, 2026', 'Lakers vs Blazers 27 Oct 2026',
                      'Lakers vs Blazers 2026-10-27'):
            self.assertEqual(search.replay_date(title,self.today), dt.date(2026,10,27))
        self.assertEqual(search.parse_query('lakers dec 31',dt.date(2027,1,1)).date,dt.date(2026,12,31))
        self.assertIsNone(search.parse_query('49ers vs rams',self.today).date)

    def test_search_fetches_only_relevant_league_and_reuses_cache(self):
        app = nba.App(None,{})
        app.search_query = 'mavs'
        with patch.object(nba, 'default_day', return_value=self.today), \
             patch.object(replays, 'catalogs', return_value=[]), \
             patch.object(nba, 'get_games', return_value=[self.mavs]) as get_games:
            app.update_global_search(); app.search_due = 0; app.start_global_search()
            end = time.monotonic()+2
            while app.search_inflight and time.monotonic() < end:
                app.poll_global_search(); time.sleep(.01)
            self.assertEqual(get_games.call_count,1)
            self.assertEqual(get_games.call_args.args, (self.today,'nba'))
            self.assertEqual(app.search_results[0].kind,'live')
            app.search_query = 'mavs vs rockets'
            app.update_global_search(); app.search_due = 0; app.start_global_search()
            self.assertEqual(get_games.call_count,1)
            self.assertEqual(app.search_results[0].item,self.mavs)
        app.close()

    def test_selection_stays_on_user_choice_as_results_arrive(self):
        app = nba.App(None,{})
        app.search_query = 'mavs'
        with patch.object(nba, 'default_day', return_value=self.today), patch.object(replays, 'catalogs', return_value=[]):
            app.update_global_search()
            self.assertEqual(app.search_results[0].kind, 'team')
            selected = app.search_results[0].key
            app.search_touched = True
            app.search_cache[('games','nba',self.today)] = (time.monotonic()+60,[self.mavs],None)
            app.rebuild_global_results()
            self.assertEqual(app.search_results[0].kind, 'live')
            self.assertEqual(app.search_results[app.search_position].key, selected)

    def test_stream_rows_distinguish_listed_and_measured_quality(self):
        feed = nba.Feed('NBA Bite', 'sportylive.xyz | Spectrum SportsNet | HD | English',
                        side='away', kind='candidate')
        view = nba.describe_feed(feed, {}, 'checking')
        self.assertEqual((view.name,view.side,view.quality,view.check),
                         ('NBA Bite / sportylive.xyz','AWAY','~HD','Checking'))
        self.assertIn('Spectrum SportsNet',view.detail)
        view = nba.describe_feed(feed, {'checks':[True,True,True],'height':720}, 'OK')
        self.assertEqual(view.quality,'720p')
        self.assertEqual(view.check,'OK A 3/3')


if __name__ == '__main__':
    unittest.main()
