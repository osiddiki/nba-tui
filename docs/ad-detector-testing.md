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
    {"start": 30, "end": 40, "label": "overlay"},
    {"start": 40, "end": 70, "label": "ad"},
    {"start": 70, "end": 75, "label": "break"},
    {"start": 75, "end": 90, "label": "promo"},
    {"start": 90, "end": 120, "label": "broadcast"}
  ]
}
```

Use `broadcast` for game play, replays and other program coverage; `studio` for
studio, desk and booth segments with hosts or analysts on camera; `bench` for
bench, sideline, crowd and interview shots away from play; `ad` for a full-screen
paid commercial, including political ads; `promo` for network or program
promotions; `break` for a quiet break screen or filler with no commercial or
program coverage; and `overlay` for sponsor graphics or an ad read while game
or program coverage continues. A timeout with commentary remains `broadcast`;
a paid commercial during a timeout is `ad`. Leave unclear sections unlabeled,
or label them `unknown`. Intervals are start-inclusive and end-exclusive and
must not overlap. The tool treats gaps as unknown.

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
each label, so false mutes on studio and bench coverage show on their own rows. The JSON report includes
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

## Train a smaller model

`sportscli/tools/train_ad_model.py` fine-tunes an int8 MobileNetV3-Small at
256×144. On an Apple M2 the exported model is about 0.6 MB and classifies a
frame in about 2 ms, compared with 22 MB and about 280 ms for the original
VGG16 model. Those numbers come from the export pipeline; they say nothing
about accuracy, which depends entirely on the training footage.

Label recordings from several sports and networks. Commercials look similar
across sports, and studio, bench and sideline coverage from other sports
teaches the model what is not an ad. To label quickly, sample frames and tag
each one, by hand or with a vision model, then merge the tags:

```sh
python3 -m sportscli.tools.label_frames extract game.mp4 ~/ad-data/game-frames --every 2
# write ~/ad-data/game-frames/tags.json: {"00000000.0.jpg": "broadcast", ...}
python3 -m sportscli.tools.label_frames intervals ~/ad-data/game-frames/tags.json ~/ad-data/game.json
```

Model-generated tags are useful for training but can confuse promos with paid
ads. To record several live games unattended at training resolution, about 100 MB
per hour each, run `python3 -m sportscli.tools.record_games ~/ad-data/recordings
nba:Knicks nhl:Jets` before they start; it waits for each game and stops when
ESPN marks it finished. `tv:ESPN` or `"tv:NFL Network"` with `--hours 3`
records a channel from the live TV directory right away; sports networks fill
the night with studio shows and commercials. Sparse stills, such as one frame every 45 seconds from a replay, need no
video file: list the folder and its `tags.json` as a `frames` entry in the
manifest. Replay archives usually have commercials cut out, so they add
coverage, studio and bench examples rather than ads; record live games for
ads. Check the labels of the held-out broadcasts yourself so the evaluation
remains trustworthy. List the recordings in a manifest (see the module
docstring), then train with TensorFlow 2.16 and Pillow in a separate
environment:

```sh
python -m sportscli.tools.train_ad_model ~/ad-data/dataset.json --output ~/ad-data/ad-model.tflite
```

The tool holds out whole broadcasts, uses only explicit labels by default. Pass `--teacher-weight 0.3` to opt into
the original model's soft labels for unlabeled time when it is installed, and prints held-out mute counts
for both models using the playback decision logic. `--install` makes the result
the active detector and enables AI detection for its leagues; delete
`ad-model.tflite` from the detector directory to restore the original.

## Experiments so far

We evaluated the current quantized NBA model and playback decision logic at
two-second intervals on two independently labeled 120-second excerpts from
1996 NBC NBA broadcasts. It muted 75 of 75 sampled paid-ad frames, but also
muted 14 of 30 sampled broadcast frames and 7 of 7 sampled promo frames.
Uncertain boundary intervals were kept separate. These are a small, correlated
set of samples from one network and era, not a field accuracy measurement or
proof that complete ad breaks will be detected. The false mutes demonstrate
that automatic use remains unsafe for uninterrupted commentary.

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

We also tried a three-class linear head on the same frozen image features,
holding out whole broadcasts. With a fixed argmax decision it identified
281/390 ad samples, 166/258 broadcast samples, and 14/78 promo samples as
their correct classes. It mislabeled 72 broadcast and 42 promo samples as ads.
That experiment has no labeled break or overlay samples, so it cannot evaluate
those classes. It was not deployed.

The current model produces only a binary score; it does not distinguish these
labels. The additional labels let future models and evaluations separate
commercials from pauses and sponsored coverage without muting those categories
by default.
