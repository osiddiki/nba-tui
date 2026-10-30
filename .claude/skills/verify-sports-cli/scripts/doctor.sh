#!/bin/sh
# Read-only: is this checkout worth driving? Prints one line per check; exits 1 on a blocker.
cd "$(dirname "$0")/../../../.." || exit 1
status=0
echo "commit: $(git rev-parse --short HEAD)$(git diff --quiet || echo ' (uncommitted changes)')"
python3 -c 'import sys; assert sys.version_info >= (3, 9)' && echo "python: $(python3 --version)" || { echo "python: need 3.9+"; status=1; }
python3 sports-cli --help >/dev/null 2>&1 && echo "app: ./sports-cli starts" || { echo "app: ./sports-cli --help failed"; status=1; }
command -v mpv >/dev/null && echo "mpv: $(mpv --version | head -1)" || echo "mpv: missing (playback features cannot be proven)"
command -v ffmpeg >/dev/null && echo "ffmpeg: present" || echo "ffmpeg: missing (recorder and frame tools cannot run)"
if env | grep -qi '^https\?_proxy='; then echo "network: proxy set ($(env | grep -i '^https_proxy=' | cut -d= -f2)); stream hosts may be refused, so run network features from a normal terminal"; else echo "network: no proxy"; fi
running=$(pgrep -f '[./]sports-cli( |$)' | wc -l | tr -d ' ')
echo "other app instances: $running (drive.py uses its own settings folder, so they do not conflict)"
exit $status
