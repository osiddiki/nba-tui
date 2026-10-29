import unittest
from unittest.mock import patch

from sportscli import smart_search


class FuzzyFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = smart_search.default_index()

    def resolve(self, query, rapidfuzz):
        self.index.resolve.cache_clear()
        with patch.object(smart_search, '_rapid_process',
                          smart_search._rapid_process if rapidfuzz else None):
            return self.index.resolve(query)

    def assert_first(self, query, expected, rapidfuzz):
        results = self.resolve(query, rapidfuzz)
        self.assertTrue(results)
        self.assertEqual(results[0][0].display, expected)
        return results

    def test_typos_resolve_with_rapidfuzz_and_stdlib_fallback(self):
        for rapidfuzz in (True, False):
            with self.subTest(rapidfuzz=rapidfuzz):
                result = self.assert_first('lkaers', 'Los Angeles Lakers', rapidfuzz)
                self.assertGreater(result[0][1], .81)  # outranks the weak Lake Erie match
                self.assert_first('warriros', 'Golden State Warriors', rapidfuzz)

    def test_exact_aliases_and_short_prefixes_keep_existing_behavior(self):
        for rapidfuzz in (True, False):
            with self.subTest(rapidfuzz=rapidfuzz):
                mavs = self.assert_first('mavs', 'Dallas Mavericks', rapidfuzz)
                self.assertEqual(mavs[0][1], 1.0)
                self.assert_first('philly', 'Philadelphia 76ers', rapidfuzz)
                self.assert_first('ma', 'Dallas Mavericks', rapidfuzz)
                self.assert_first('mav', 'Dallas Mavericks', rapidfuzz)


if __name__ == '__main__':
    unittest.main()
