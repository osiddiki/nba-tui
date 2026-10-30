"""Developer-only: sample frames for labeling, then turn per-frame tags into label intervals.

    python -m sportscli.tools.label_frames extract game.mp4 frames/ --every 2
    python -m sportscli.tools.label_frames intervals frames/tags.json game.labels.json

``extract`` writes small JPEGs named by their position in seconds (for example
``000123.0.jpg``) to a folder outside the repository. A reviewer, or a model,
writes ``tags.json`` mapping each file name to one label from
docs/ad-detector-testing.md. ``intervals`` merges consecutive equal tags into
the interval manifest that evaluate_ads and train_ad_model read. A single
differing frame inside a run is treated as noise unless --keep-single is set.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

from sportscli.tools.evaluate_ads import LABELS


def extract(video, folder, every, start, duration, width):
    folder.mkdir(parents=True, exist_ok=True)
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', str(start), '-i', str(video)]
    if duration: command += ['-t', str(duration)]
    command += ['-vf', f'fps=1/{every},scale={width}:-2', '-q:v', '4', str(folder / 'frame-%06d.jpg')]
    subprocess.run(command, check=True)
    names = []
    for index, path in enumerate(sorted(folder.glob('frame-*.jpg'))):
        name = f'{start + index * every:08.1f}.jpg'
        path.rename(folder / name); names.append(name)
    return names


def intervals(tags, every, keep_single=False):
    """Merge chronological per-frame tags into non-overlapping labeled intervals."""
    samples = sorted((float(pathlib.Path(name).stem), label) for name, label in tags.items())
    for _, label in samples:
        if label not in LABELS: raise ValueError(f'Unknown label: {label}')
    labels = [label for _, label in samples]
    if not keep_single:
        # Smooth an isolated frame that disagrees with identical neighbours.
        for i in range(1, len(labels) - 1):
            if labels[i - 1] == labels[i + 1] != labels[i]: labels[i] = labels[i - 1]
    out = []
    for (position, _), label in zip(samples, labels):
        if out and out[-1]['label'] == label and abs(out[-1]['end'] - position) < every * 1.5:
            out[-1]['end'] = position + every
        else:
            out.append({'start': position, 'end': position + every, 'label': label})
    return [item for item in out if item['label'] != 'unknown']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    sample = commands.add_parser('extract', help='write timestamped frames for labeling')
    sample.add_argument('video', type=pathlib.Path)
    sample.add_argument('folder', type=pathlib.Path)
    sample.add_argument('--every', type=float, default=2.0)
    sample.add_argument('--start', type=float, default=0.0)
    sample.add_argument('--duration', type=float)
    sample.add_argument('--width', type=int, default=384)
    merge = commands.add_parser('intervals', help='convert tags.json into a label manifest')
    merge.add_argument('tags', type=pathlib.Path)
    merge.add_argument('output', type=pathlib.Path)
    merge.add_argument('--every', type=float, default=2.0)
    merge.add_argument('--keep-single', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'extract':
        if not shutil.which('ffmpeg'): raise SystemExit('ffmpeg is required.')
        names = extract(args.video, args.folder, args.every, args.start, args.duration, args.width)
        print(f'Wrote {len(names)} frames to {args.folder}')
    else:
        result = intervals(json.loads(args.tags.read_text(encoding='utf-8')), args.every, args.keep_single)
        args.output.write_text(json.dumps({'intervals': result}, indent=2) + '\n')
        print(f'Wrote {len(result)} intervals to {args.output}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
