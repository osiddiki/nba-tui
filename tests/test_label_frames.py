import unittest

from sportscli.tools import label_frames


class LabelFramesTest(unittest.TestCase):
    def test_tags_merge_into_intervals_and_isolated_noise_is_smoothed(self):
        tags = {'0000000.0.jpg': 'broadcast', '0000002.0.jpg': 'broadcast', '0000004.0.jpg': 'ad',
                '0000006.0.jpg': 'broadcast', '0000008.0.jpg': 'broadcast', '0000010.0.jpg': 'ad',
                '0000012.0.jpg': 'ad', '0000014.0.jpg': 'unknown', '0000016.0.jpg': 'unknown'}
        self.assertEqual(label_frames.intervals(tags, 2), [
            {'start': 0.0, 'end': 10.0, 'label': 'broadcast'},
            {'start': 10.0, 'end': 14.0, 'label': 'ad'}])
        kept = label_frames.intervals(tags, 2, keep_single=True)
        self.assertIn({'start': 4.0, 'end': 6.0, 'label': 'ad'}, kept)

    def test_unknown_labels_are_rejected(self):
        with self.assertRaises(ValueError):
            label_frames.intervals({'0.0.jpg': 'commercial'}, 2)


if __name__ == '__main__':
    unittest.main()
