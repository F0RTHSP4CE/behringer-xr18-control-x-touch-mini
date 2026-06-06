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

## recording

Press row 2, column 8 on the X-Touch Mini to start/stop recording. While recording, that button blinks on every page.

Recordings are written as multichannel RF64 WAV files at 48 kHz / 24-bit PCM by default. RF64 keeps CPU load low like normal WAV, but supports files larger than 4 GB.

When recording starts, the script snapshots channel mute state and writes only unmuted channel strips. If a muted channel is unmuted later, it is not added to the active recording. Muting a channel after recording starts does not remove it from that recording.

The script records from the XR18 USB audio device, not from MIDI. By default it searches for an audio device matching `X-AIR` and auto-picks the best match: most input channels first, then ASIO, WDM-KS, WASAPI, DirectSound, and MME.

List available audio inputs and their host APIs:

```
uv run xr18-controls.py --list-audio-devices
```

On Windows the script enables `sounddevice`'s ASIO-capable PortAudio DLL before listing or recording devices. If an ASIO driver is installed and visible to PortAudio, it should appear in this list.

If an ASIO device is available, you can force ASIO:

```
uv run xr18-controls.py --record-hostapi ASIO --record-audio-device "X-AIR"
```

If you need to target a specific device, pass its numeric index:

```
uv run xr18-controls.py --record-audio-device 52
```

To force one of the Windows host APIs from the device list:

```
uv run xr18-controls.py --record-hostapi "Windows WDM-KS"
```

If the chosen device is `IN 1-8`, the script captures inputs 1-8 and writes only the unmuted channels among those inputs. Channels 9-16 cannot be recorded from an 8-input WDM/WASAPI-style device.

Recording filenames include the date/time plus random words, for example `2026-06-06_21-30-12_river-signal.wav`.
