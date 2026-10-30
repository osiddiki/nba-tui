#!/bin/sh
# Run every recipe in features/ once and write a pass/fail summary next to the evidence.
# Usage: .claude/skills/verify-sports-cli/scripts/run_all.sh   (from anywhere; needs network without a proxy)
cd "$(dirname "$0")/../../../.." || exit 1
D=.claude/skills/verify-sports-cli/scripts/drive.py
RUN=${RUN:-$HOME/.cache/sports-cli-verify/runs/all-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$RUN"
SUMMARY="$RUN/summary.txt"
.claude/skills/verify-sports-cli/scripts/doctor.sh > "$RUN/doctor.txt" 2>&1
pass=0; fail=0
check() {  # check ID [drive.py arguments...]
  id=$1; shift
  if "$D" --out "$RUN/$id" "$@" > "$RUN/$id.log" 2>&1; then
    echo "PASS $id" | tee -a "$SUMMARY"; pass=$((pass+1))
  else
    echo "FAIL $id (see $RUN/$id.log)" | tee -a "$SUMMARY"; fail=$((fail+1))
  fi
}
shell_check() {  # shell_check ID command...
  id=$1; shift
  if "$@" > "$RUN/$id.out" 2> "$RUN/$id.err"; then
    echo "PASS $id" | tee -a "$SUMMARY"; pass=$((pass+1))
  else
    echo "FAIL $id (exit $?; see $RUN/$id.err)" | tee -a "$SUMMARY"; fail=$((fail+1))
  fi
}

check nav-schedule 'expect:Choose a sport or league' shot:home key:Enter 'expect:NBA  \|' shot:schedule key:Esc 'expect:Choose a sport or league' shot:back
check nav-help --app-args="--league nba" 'expect:NBA  \|' 'key:?' 'expect:Controls and setup' shot:help key:Esc 'expect:NBA  \|' shot:back
check nav-search 'expect:Choose a sport' key:s 'expect:Search:' type:lakers 'expect:Search: lakers' shot:search key:Esc 'expect:Choose a sport' shot:back
check nav-date --app-args="--league nba" 'expect:NBA  \|' shot:today 'key:]' 'expect:NBA  \|' shot:tomorrow
check tv-open 'expect:Choose a sport' key:t 'expect:CNN  \(\d+ sources?\)' shot:channels key:Esc 'expect:Choose a sport' shot:back
check tv-start --app-args="--tv" 'expect:CNN  \(\d+ sources?\)' shot:start
check tv-filter --app-args="--tv" 'expect:CNN  \(' key:/ 'expect:Filter channels' type:weather key:Enter 'expect:filter: weather' shot:filtered
check tv-sources --app-args="--tv" 'expect:CNN  \(' key:Down key:Enter 'expect:CNBC' 'expect:choices found' wait:8 shot:sources
check src-settings --app-args="--tv" 'expect:CNN  \(' key:Enter 'expect:choices found' shot:sources key:b 'expect:Backup source off' 'expect:backup: off' shot:backup-off key:b 'expect:adds a backup source' key:m 'expect:During detected ads: break screen' shot:breaks key:c 'expect:cache: 30s' shot:cache
check play-tv --mpv-seconds 8 --app-args="--tv" 'expect:CNN  \(' key:Enter 'expect:choices found' shot:sources key:Enter 'expect:Returned from mpv' shot:returned
check rep-list --app-args="--league nba" 'expect:NBA  \|' key:R 'expect:replays found' shot:replays key:Enter 'expect:Replay servers from' 'expect:choices found' shot:servers key:Esc 'expect:Replays' shot:back
shell_check list-games python3 sports-cli --list --league nba
shell_check list-tv python3 sports-cli --list --tv

echo "$pass passed, $fail failed. Evidence: $RUN" | tee -a "$SUMMARY"
[ "$fail" -eq 0 ]
