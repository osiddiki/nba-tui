#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
commit=0f91ece96dc33cfda83948264948452bc988bb54
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo 'Install Node.js (20+) and npm, then rerun this script.' >&2
  exit 1
fi
major=$(node -p "Number(process.versions.node.split('.')[0])")
if [ "$major" -lt 20 ]; then
  echo 'Install Node.js 20 or newer, then rerun this script.' >&2
  exit 1
fi
if [ ! -f resolver/src/server.js ]; then
  if [ -e resolver ]; then echo 'resolver exists but is not the expected checkout.' >&2; exit 1; fi
  git clone https://github.com/Lunatic16/ppv-hls-proxy.git resolver
  git -C resolver checkout --detach "$commit"
fi
npm install --prefix resolver --ignore-scripts --no-audit --no-fund
if ! command -v mpv >/dev/null 2>&1; then
  echo 'Install mpv as well, then run ./nba.py'
else
  echo 'Ready: ./nba.py'
fi
