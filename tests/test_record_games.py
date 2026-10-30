import unittest
from types import SimpleNamespace

from sportscli.tools import record_games


class RecordGamesTests(unittest.TestCase):
    def test_find_game_matches_either_team_ignoring_case(self):
        games = [SimpleNamespace(home='Boston Celtics', away='Chicago Bulls'),
                 SimpleNamespace(home='Philadelphia 76ers', away='New York Knicks')]
        self.assertIs(record_games.find_game(games, 'knicks'), games[1])
        self.assertIs(record_games.find_game(games, 'Celtics'), games[0])
        self.assertIsNone(record_games.find_game(games, 'Lakers'))

    def test_command_passes_headers_and_records_small_video(self):
        command = record_games.command('https://cdn.test/live.m3u8',
                                       {'Referer': 'https://player.test/', 'User-Agent': 'UA'}, 'out.ts')
        self.assertEqual(command[command.index('-user_agent') + 1], 'UA')
        self.assertEqual(command[command.index('-headers') + 1], 'Referer: https://player.test/\r\n')
        self.assertIn('scale=-2:216,fps=10', command)
        self.assertEqual(command[-1], 'out.ts')
        self.assertNotIn('-headers', record_games.command('http://127.0.0.1:1/m.m3u8', {}, 'o.ts'))


if __name__ == '__main__':
    unittest.main()
