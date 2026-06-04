# behringer-xr18-control-x-touch-mini

control behringer XR18 mixer with x-touch mini

## install dependencies & run
install [uv](https://docs.astral.sh/uv/getting-started/installation)

```
uv run xr18-controls.py
```

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

## probe XR18 X-OSC over MIDI

Use this to check whether the XR18 replies to OSC-over-SysEx queries on its MIDI port:

```
uv run xr18-controls.py --probe-xosc
```

If replies appear as `X-OSC ...`, startup sync can be built from those values. Normal `control_change` replies mean MIDI feedback is working, but they are not X-OSC query replies.
