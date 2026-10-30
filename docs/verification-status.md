# Verification status

The app is Python. Bend's laws apply to Bend implementations and proofs; a
separate Bend model would not by itself prove this Python program correct.
There are no project Bend proofs or LAWS.bend files in the current checkout.
Bend 2's upstream now points to https://github.com/bendlang/bend.

## Existing executable checks

| Area | Property | Check | Limit |
| --- | --- | --- | --- |
| Navigation | Keys follow the screen chart; Escape reaches Home | `python3 -m unittest tests.test_screens` | Declared screen states and tested keys |
| Async playback | Stale or canceled requests cannot open a player | `python3 -m unittest tests.test_feed_actions_async` | Deterministic controlled thread schedules |
| Replay discovery | A team search retains matches from later archive pages | `python3 -m unittest tests.test_search` | At most five older pages per supported archive; ten displayed games |
| Training partition | Excerpts of one broadcast never cross training/evaluation partitions | `python3 -m unittest tests.test_training_split` | Broadcast IDs must identify the real shared source |
| Relay failover | Never repeat or rewind already played segments | `verification/relay/check.sh` | Six segments, two sources, backup one segment behind |

The relay's shared-timestamp configuration passes. Shared-name, shared-date,
and live-edge configurations still produce NoRepeat counterexamples. The
deliberately broken configuration also fails, showing the check detects a
violation. The script expects these documented failures, so a zero exit status
does **not** mean every relay configuration is correct. See
[relay-failover.md](relay-failover.md).

The network-facing catalogs, stream quality, ML recognition accuracy, and all
possible thread schedules are not proved by these checks. Future laws should
be tied to executable code with conformance tests and deliberately broken
variants before they count as verification.

## Agent skills

The existing project skills are in `.claude/skills/`. For this session, 58
portable pstack skills were imported into `~/.agents/skills/` from
https://github.com/backnotprop/pstack at commit
`25abb38559ddbabec563646224d09eff9a250eca`. This mirror identifies
https://github.com/cursor/plugins/tree/main/pstack as its original source.
The user-level installation is not part of the app or its runtime dependencies.

This imports instructions, not a guarantee of correctness. Applicable project
guidance and the user's requests remain authoritative.
