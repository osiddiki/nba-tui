import contextlib
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from sportscli.tools import evaluate_ads


class EvaluateAdsTests(unittest.TestCase):
    def test_labels_are_half_open_and_gaps_are_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = pathlib.Path(root) / 'labels.json'
            manifest.write_text(json.dumps({'intervals': [
                {'start': 4, 'end': 8, 'label': 'ad'},
                {'start': 0, 'end': 2, 'label': 'broadcast'},
                {'start': 8, 'end': 10, 'label': 'promo'},
            ]}))
            intervals = evaluate_ads.read_intervals(manifest)
            self.assertEqual([evaluate_ads.label_at(intervals, t) for t in (0, 2, 4, 8, 10)],
                             ['broadcast', 'unknown', 'ad', 'promo', 'unknown'])
            manifest.write_text(json.dumps({'intervals': [
                {'start': 0, 'end': 2.1, 'label': 'ad'},
                {'start': 2, 'end': 4, 'label': 'broadcast'},
            ]}))
            with self.assertRaisesRegex(ValueError, 'overlap'):
                evaluate_ads.read_intervals(manifest)

    def test_report_evaluates_live_decisions_and_keeps_promos_separate(self):
        class Decision:
            def update(self, score):
                return score < .5
        scores = iter([.9, .1, .2, .8])
        report = evaluate_ads.evaluate(['a', 'b', 'c', 'd'],
                                      [(10, 12, 'broadcast'), (12, 14, 'ad'),
                                       (14, 16, 'promo')],
                                      10, 2, lambda _: next(scores), Decision())
        self.assertEqual(report['counts']['broadcast'], {'samples': 1, 'muted': 0})
        self.assertEqual(report['counts']['ad'], {'samples': 1, 'muted': 1})
        self.assertEqual(report['counts']['promo'], {'samples': 1, 'muted': 1})
        self.assertEqual(report['counts']['unknown'], {'samples': 1, 'muted': 0})
        self.assertEqual([sample['time'] for sample in report['samples']], [10, 12, 14, 16])

    def test_invalid_model_scores_are_not_classified(self):
        for value in (True, float('nan'), -1, 2, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'invalid score'):
                evaluate_ads.evaluate(['frame'], [], 0, 2, lambda _: value)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is needed for the video sampling check')
    def test_samples_local_video_at_actual_positions(self):
        with tempfile.TemporaryDirectory() as root:
            root = pathlib.Path(root)
            video, manifest = root / 'video.mp4', root / 'labels.json'
            worker, model, report = root / 'worker.py', root / 'model', root / 'report.json'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc=size=64x64:rate=10:duration=6', '-c:v', 'mpeg4', str(video)],
                           check=True, capture_output=True)
            manifest.write_text(json.dumps({'intervals': [
                {'start': 0, 'end': 2, 'label': 'broadcast'},
                {'start': 2, 'end': 5, 'label': 'ad'}]}))
            worker.write_text('import json,sys\nprint(json.dumps({"ready":True}),flush=True)\n'
                              'for line in sys.stdin: print(json.dumps({"score":0.1}),flush=True)\n')
            model.write_text('test model')
            args = [str(video), str(manifest), '--start', '1', '--duration', '3.5', '--every', '2',
                    '--python', sys.executable, '--worker', str(worker), '--model', str(model),
                    '--output', str(report)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(evaluate_ads.main(args), 0)
            samples = json.loads(report.read_text())['samples']
            self.assertEqual([item['label'] for item in samples], ['broadcast', 'ad'])
            self.assertAlmostEqual(samples[0]['time'], 1, delta=.11)
            self.assertAlmostEqual(samples[1]['time'], 3, delta=.11)


if __name__ == '__main__':
    unittest.main()
