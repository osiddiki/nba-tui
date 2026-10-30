import unittest
from sportscli.tools import train_ad_model as training


class TrainingSplitTests(unittest.TestCase):
    def test_all_excerpts_of_a_broadcast_stay_in_one_partition(self):
        rows = [{'broadcast': name} for name in ('a', 'a', 'b', 'c', 'c')]
        train, held = training.split(rows, ['a'])
        self.assertEqual(len(held), 2)
        self.assertFalse({r['broadcast'] for r in train} & {r['broadcast'] for r in held})

    def test_misspelled_holdout_cannot_silently_remove_evaluation(self):
        with self.assertRaisesRegex(ValueError, 'Unknown held-out'):
            training.split([{'broadcast': 'game'}], ['typo'])
