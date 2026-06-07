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

Default recording directories:

- Linux: `~/XR18_Recordings`
- Windows: `C:\Users\%USERNAME%\Music\XR18_Recordings`

When recording is stopped from the controller, the recording folder opens with the created file selected when the platform file manager supports it.

If the USB audio stream fails while recording, the script stops recording, finalizes the partial file, turns off the blinking record light, shows a stop notification, and opens the recording location.

When recording starts, the script snapshots channel mute state and writes only unmuted channel strips. If a muted channel is unmuted later, it is not added to the active recording. Muting a channel after recording starts does not remove it from that recording.

The script records from the XR18 USB audio device, not from MIDI. By default it searches for an ASIO audio device matching `X-AIR` with at least 18 inputs. Non-ASIO devices and devices with fewer than 18 inputs are discarded for recording.

List available audio inputs and their host APIs:

```
uv run xr18-controls.py --list-audio-devices
```

On Windows the script enables `sounddevice`'s ASIO-capable PortAudio DLL before listing or recording devices. If an ASIO driver is installed and visible to PortAudio, it should appear in this list as a recording candidate.

ASIO is the default, but you can still be explicit:

```
uv run xr18-controls.py --record-hostapi ASIO --record-audio-device "X-AIR"
```

If you need to target a specific ASIO device, pass its numeric index:

```
uv run xr18-controls.py --record-audio-device 52
```

Backend JACK/PortAudio probe warnings are hidden by default. To show native backend diagnostics:

```
set XR18_AUDIO_BACKEND_DEBUG=1
set XR18_MIDI_BACKEND_DEBUG=1
```

Recording filenames include the date/time plus random words, for example `2026-06-06_21-30-12_river-signal.wav`.
