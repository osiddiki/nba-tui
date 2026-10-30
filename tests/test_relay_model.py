"""Conformance: the real timeline follows verification/relay/RelayFailover.tla's PumpResume.

After a switch, the next segment is the moment after the last one played, or the
relay waits until the new source publishes it. Checked for each way sources can
line up (names, program dates, transport-stream timestamps) with the backup
trailing by 0 to 2 segments.
"""
import unittest

from sportscli import merge

DURATION = 6.0
EPOCH = 1_793_400_000.0  # program dates are epoch seconds


def playlist(prefix, moments, *, names, pdt):
    """Segments for broadcast moments; shared names or program dates when the sources share them."""
    return merge.Playlist(6, [merge.Segment(
        m, f'https://{prefix}/{"seg" if names else prefix}-{m:03d}.ts', DURATION,
        EPOCH + m * DURATION if pdt else None, False) for m in moments], False)


def moment(segment):
    return segment.seq


class RelayModelConformance(unittest.TestCase):
    def resume(self, *, lag, names=False, pdt=False, pts=False, edge=8):
        timeline = merge.Timeline()
        main = playlist('main', range(edge - 5, edge + 1), names=names, pdt=pdt)
        start = timeline.plan(0, main)
        played = start[0][0]
        timeline.commit(0, played, start[0][1], 'k', pts=moment(played) * 90000 * 6 if pts else None)
        timeline.observe(0, main)
        backup = playlist('backup', range(edge - 5 - lag, edge + 1 - lag), names=names, pdt=pdt)
        plan = timeline.plan(1, backup)
        if pts and timeline.needs_alignment(1, plan):
            # Merged.align: measure the first planned segment's timestamp and realign.
            first = plan[0][0]
            position = backup.segments.index(first)
            best = merge.realign(backup.segments, position, moment(first) * 90000 * 6, timeline.end_pts)
            plan = [(s, True) for s in backup.segments[best:]]
        return moment(played), [moment(s) for s, _ in plan]

    def test_timestamp_realignment_continues_after_the_last_moment_or_waits(self):
        for lag in range(3):
            with self.subTest(lag=lag):
                last, plan = self.resume(lag=lag, pts=True)
                if plan: self.assertEqual(plan[0], last + 1)  # never a repeat, never a jump

    def test_names_and_dates_continue_when_the_backup_has_the_next_moment(self):
        for mode in ('names', 'pdt'):
            with self.subTest(mode=mode):
                last, plan = self.resume(lag=0, **{mode: True})
                self.assertEqual(plan[0], last + 1)

    def test_known_findings_names_dates_and_edge_fall_back_and_repeat(self):
        # RelayFailover.tla finds NoRepeat breaking for Resume = "names", "pdt" and "edge":
        # when the backup has not yet published the next moment (names: the moment that was
        # playing), Timeline.plan() keeps the distance from the live edge instead of waiting.
        # These assertions record today's behavior so that a fix shows up as a change here.
        for mode, lag in (('names', 3), ('pdt', 2), (None, 1)):
            with self.subTest(mode=mode, lag=lag):
                last, plan = self.resume(lag=lag, **({mode: True} if mode else {}))
                self.assertLessEqual(plan[0], last)

if __name__ == '__main__':
    unittest.main()
