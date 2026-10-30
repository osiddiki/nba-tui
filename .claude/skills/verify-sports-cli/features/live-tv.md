# Live TV

Live TV channels (CNN, CNBC, MS NOW, Fox News and about 2,000 more) from iptv-org's free streams and DaddyLive's 24/7 pages, listed with the main news and network channels first.

## Sub-features

- `tv-open` `t` on the sports list or a schedule opens Live TV; Esc or `t` returns.
- `tv-start` `./sports-cli --tv` starts on Live TV.
- `tv-filter` `/` filters channels by name.
- `tv-sources` Enter on a channel lists its sources and checks them.

## How to get to it (user POV)

- Press `t` on the first screen or on any schedule.
- Start with `./sports-cli --tv`.

## Driving it with drive.py

Preconditions: baseline; network without a proxy for the source checks.

- **Open from home.** `$D 'expect:Choose a sport' key:t 'expect:CNN  \(\d+ sources?\)' shot:channels`. The first rows are CNN, CNBC, MS NOW, Fox News, Fox Business in bold.
- **Back.** Continue with `key:Esc 'expect:Choose a sport'`.
- **Start there.** `$D --app-args="--tv" 'expect:CNN  \(\d+ sources?\)' shot:start`.
- **Filter.** `$D --app-args="--tv" 'expect:CNN  \(' key:/ 'expect:Filter channels' type:weather key:Enter 'expect:filter: weather' shot:filtered`. Only weather channels remain.
- **Sources.** `$D --app-args="--tv" 'expect:CNN  \(' key:Down key:Enter 'expect:CNBC' 'expect:choices found' wait:6 shot:sources`. CNBC lists an iptv-org and a DaddyLive source; the CHECK column fills in (`OK` or `HTTP 404`).

## Gotchas

- The channel list loads in the background (spinner beside `Live TV`); expect a CNN row before pressing Enter.
- iptv-org's CNBC stream has returned HTTP 404; its DaddyLive source played. Report what the CHECK column shows.
- Inside a sandbox proxy, DaddyLive's player host is refused; the list still loads.
