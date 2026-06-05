# behringer-xr18-control-x-touch-mini

control behringer XR18 mixer with x-touch mini

install [uv](https://docs.astral.sh/uv/getting-started/installation)

```
uv run xr18-controls.py
```

x-touch mini should be in **mackie mode**: unplug the x-touch mini, hold the MC button (bottom left), connect to pc, wait a few seconds, release the button — MC mode LED will turn on. 

## demo mode 
Demo mode still connects to the X-Touch Mini, but it does not require an XR18 mixer. Mixer actions are stored in memory and printed to the terminal.

```
uv run xr18-controls.py --demo
```

## debug MIDI input

Use debug mode when a button or fader seems unreliable:

```
uv run xr18-controls.py --demo --debug-midi
```

If a press has no `xtouch-midi: raw ...` line, the event did not reach the script. If it has a raw line but no `xtouch-router: button=...` line, the mapping needs fixing.
