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

check nav-home 'expect:Home' 'expect:Live sports' shot:home key:1 'expect:Live sports: choose a sport' key:Enter 'expect:NBA  \|' shot:schedule key:Esc 'expect:choose a sport' key:Esc 'expect:Home' shot:back-home
check nav-help --app-args="--league nba" 'expect:NBA  \|' 'key:?' 'expect:Controls and setup' shot:help key:Esc 'expect:NBA  \|' shot:back
check nav-search 'expect:Home' key:/ 'expect:Search:' type:lakers 'expect:Search: lakers' shot:search key:Esc 'expect:Home' shot:back
check nav-date --app-args="--league nba" 'expect:NBA  \|' shot:today 'key:]' 'expect:NBA  \|' shot:tomorrow
check nav-sport --app-args="--league nba" 'expect:NBA  \|' key:s 'expect:choose a sport' key:Down key:Enter 'expect:WNBA  \|' shot:wnba
check tv-open 'expect:Home' key:3 'expect:CNN  \(\d+ sources?\)' shot:channels key:Esc 'expect:Home' shot:back
check tv-start --app-args="--tv" 'expect:CNN  \(\d+ sources?\)' shot:start
check tv-filter --app-args="--tv" 'expect:CNN  \(' key:f 'expect:Filter channels' type:weather key:Enter 'expect:filter: weather' shot:filtered
check tv-search 'expect:Home' key:/ type:cnbc 'expect:TV CHANNELS' shot:results key:Enter 'expect:choices found' shot:sources key:Esc 'expect:Search: cnbc'
check tv-sources --app-args="--tv" 'expect:CNN  \(' key:Down key:Enter 'expect:CNBC' 'expect:choices found' wait:8 shot:sources
check settings 'expect:Home' key:, 'expect:Backup source for live streams' shot:settings key:Down key:Down key:Down key:Enter 'expect:Backup source off' key:Down key:Enter 'expect:During detected ads: break screen' key:Up key:Up key:Up key:Enter 'expect:Cache: 30 seconds' shot:changed key:3 'expect:CNN  \(' key:Enter 'expect:backup: off' 'expect:cache: 30s' shot:sources
check play-tv --mpv-seconds 8 --app-args="--tv" 'expect:CNN  \(' key:Enter 'expect:choices found' shot:sources key:Enter 'expect:Returned from mpv' shot:returned
check rep-list 'expect:Home' key:2 'expect:Replays: choose a sport' key:Enter 'expect:replays found' shot:replays key:Enter 'expect:Replay servers from' 'expect:choices found' shot:servers key:Esc 'expect:Replays' shot:back
shell_check list-games python3 sports-cli --list --league nba
shell_check list-tv python3 sports-cli --list --tv

echo "$pass passed, $fail failed. Evidence: $RUN" | tee -a "$SUMMARY"
[ "$fail" -eq 0 ]
