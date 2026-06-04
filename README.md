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
