# Testing ad detection

The local AI detector is experimental. A frame that is not a basketball court
may be a commercial, a studio segment, a player interview, or a replay. Test
candidate detectors on real recordings before using them to control audio.

## Label a local recording

Create a JSON file with intervals in seconds from the beginning of the video.
These sample times are illustrative:

```json
{
  "intervals": [
    {"start": 0, "end": 30, "label": "broadcast"},
    {"start": 30, "end": 60, "label": "ad"},
    {"start": 60, "end": 75, "label": "promo"},
    {"start": 75, "end": 120, "label": "broadcast"}
  ]
}
```

Use `broadcast` for game play, analysis, interviews, and other program coverage;
`ad` for paid commercials; and `promo` for network promotions. Leave unclear
sections unlabeled, or label them `unknown`. Intervals are start-inclusive and
end-exclusive and must not overlap. The tool treats gaps as unknown.

Keep whole broadcasts separate between training and evaluation; adjacent frames
from the same game or advertisement are not independent examples. Include
different sports, networks, ads, and difficult non-ad coverage such as halftime
and sideline interviews. Keep the recordings, extracted frames, and any model
weights outside the repository.

## Measure the current detector

With `ffmpeg` installed and the optional detector installed using
`./sports-cli --install-ad-model`, run:

```sh
python3 -m sportscli.tools.evaluate_ads recording.mp4 labels.json \
  --start 600 --duration 120 --output results.json
```

The tool samples locally at two-second intervals by default, uses the same
decision state machine as playback, and reports muted samples separately for
ads, broadcast coverage, promos, and unknown intervals. The JSON report includes
the actual sampled timestamps, scores, and decisions. No frames are uploaded;
temporary images are deleted at the end. `--every` changes the interval and
`--duration` is limited to 30 minutes and 1,800 samples per run.

The sample counts are a diagnostic, not an estimate of real-world accuracy or
exact mute duration. Review missed commercials, false mutes, and the delay at
each boundary. Measure inference time on the target Mac and Linux hardware as
well; an offline evaluation does not model the player's scheduling or stalls.

For an experimental worker, `--python`, `--worker`, and `--model` select local
files. The worker must implement the protocol in `sportscli/ai_ad_worker.py`:
emit `{"ready": true}` at startup and return a `score` from 0 to 1 for each
image, where lower scores indicate possible ads. The test uses the current
playback thresholds, so do not compare scores from differently calibrated
models as if they were probabilities.

## Experiments so far

In October 2026, we tested small visual classifiers on excerpts from nine
separate archived broadcasts, including paid ads, studio and game coverage,
promos, and a 2025 NFL broadcast. We held out each entire broadcast in turn.
The samples are clustered within short clips, so their counts are not independent
and the results cannot predict performance on current providers.

A compact MobileNet feature extractor with a linear classifier flagged 169 of
390 paid-ad samples, but also flagged 60 of 336 coverage and promo samples at
the chosen threshold. A smaller color-and-edge classifier missed most paid ads
from unseen broadcasts. Adding a short, past-only sequence of frames did not
make either approach reliable. Neither experimental model was included in the
app, and no footage or model weights were added to the repository.
