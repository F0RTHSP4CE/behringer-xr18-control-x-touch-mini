from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import mido


class XR18Listener(Protocol):
    def on_channel_fader(self, channel: int, value: int) -> None:
        ...

    def on_channel_mute(self, channel: int, muted: bool) -> None:
        ...

    def on_channel_pan(self, channel: int, value: int) -> None:
        ...

    def on_aux_fader(self, value: int) -> None:
        ...

    def on_fx_return_fader(self, fx: int, value: int) -> None:
        ...

    def on_aux_mute(self, muted: bool) -> None:
        ...

    def on_fx_return_mute(self, fx: int, muted: bool) -> None:
        ...

    def on_aux_pan(self, value: int) -> None:
        ...

    def on_fx_return_pan(self, fx: int, value: int) -> None:
        ...

    def on_main_fader(self, value: int) -> None:
        ...

    def on_dca_fader(self, dca: int, value: int) -> None:
        ...

    def on_main_mute(self, muted: bool) -> None:
        ...


class XR18Client(Protocol):
    def set_channel_fader(self, channel: int, value: int) -> None:
        ...

    def set_channel_mute(self, channel: int, muted: bool) -> None:
        ...

    def set_channel_pan(self, channel: int, value: int) -> None:
        ...

    def set_aux_fader(self, value: int) -> None:
        ...

    def set_fx_return_fader(self, fx: int, value: int) -> None:
        ...

    def set_aux_mute(self, muted: bool) -> None:
        ...

    def set_fx_return_mute(self, fx: int, muted: bool) -> None:
        ...

    def set_aux_pan(self, value: int) -> None:
        ...

    def set_fx_return_pan(self, fx: int, value: int) -> None:
        ...

    def set_main_fader(self, value: int) -> None:
        ...

    def set_dca_fader(self, dca: int, value: int) -> None:
        ...

    def set_main_mute(self, muted: bool) -> None:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class XR18Ports:
    input_name: str
    output_name: str


class MidoXR18Client:
    """MIDO-backed XR18 client using the documented CC lanes."""

    def __init__(self, ports: XR18Ports):
        self._input = mido.open_input(ports.input_name)
        try:
            self._output = mido.open_output(ports.output_name)
        except Exception:
            self._input.close()
            raise

    @property
    def input_port(self) -> mido.ports.BaseInput:
        return self._input

    def close(self) -> None:
        self._input.close()
        self._output.close()

    def send(self, message: mido.Message) -> None:
        self._output.send(message)

    def set_channel_fader(self, channel: int, value: int) -> None:
        self.send(mido.Message("control_change", channel=0, control=_channel_control(channel), value=_clamp(value)))

    def set_channel_mute(self, channel: int, muted: bool) -> None:
        self.send(mido.Message("control_change", channel=1, control=_channel_control(channel), value=127 if muted else 0))

    def set_channel_pan(self, channel: int, value: int) -> None:
        self.send(mido.Message("control_change", channel=2, control=_channel_control(channel), value=_clamp_pan(value)))

    def set_aux_fader(self, value: int) -> None:
        self.send(mido.Message("control_change", channel=0, control=16, value=_clamp(value)))

    def set_fx_return_fader(self, fx: int, value: int) -> None:
        self.send(mido.Message("control_change", channel=0, control=_fx_return_control(fx), value=_clamp(value)))

    def set_aux_mute(self, muted: bool) -> None:
        self.send(mido.Message("control_change", channel=1, control=16, value=127 if muted else 0))

    def set_fx_return_mute(self, fx: int, muted: bool) -> None:
        self.send(mido.Message("control_change", channel=1, control=_fx_return_control(fx), value=127 if muted else 0))

    def set_aux_pan(self, value: int) -> None:
        self.send(mido.Message("control_change", channel=2, control=16, value=_clamp_pan(value)))

    def set_fx_return_pan(self, fx: int, value: int) -> None:
        self.send(mido.Message("control_change", channel=2, control=_fx_return_control(fx), value=_clamp_pan(value)))

    def set_main_fader(self, value: int) -> None:
        self.send(mido.Message("control_change", channel=0, control=31, value=_clamp(value)))

    def set_dca_fader(self, dca: int, value: int) -> None:
        self.send(mido.Message("control_change", channel=0, control=_dca_control(dca), value=_clamp(value)))

    def set_main_mute(self, muted: bool) -> None:
        self.send(mido.Message("control_change", channel=1, control=31, value=127 if muted else 0))


class DemoXR18Client:
    """In-memory XR18 stand-in for developing without a connected mixer."""

    def __init__(self):
        self.channel_faders = {channel: 0 for channel in range(1, 17)}
        self.channel_mutes = {channel: False for channel in range(1, 17)}
        self.channel_pans = {channel: 64 for channel in range(1, 17)}
        self.fx_return_faders = {fx: 0 for fx in range(1, 5)}
        self.fx_return_mutes = {fx: False for fx in range(1, 5)}
        self.fx_return_pans = {fx: 64 for fx in range(1, 5)}
        self.aux_fader = 0
        self.aux_muted = False
        self.aux_pan = 64
        self.dca_faders = {dca: 0 for dca in range(1, 5)}
        self.main_fader = 0
        self.main_muted = False

    def close(self) -> None:
        pass

    def set_channel_fader(self, channel: int, value: int) -> None:
        clamped = _clamp(value)
        self.channel_faders[_channel_control(channel) + 1] = clamped
        print(f"[demo xr18] channel {channel} fader = {clamped}")

    def set_channel_mute(self, channel: int, muted: bool) -> None:
        self.channel_mutes[_channel_control(channel) + 1] = muted
        print(f"[demo xr18] channel {channel} mute = {'on' if muted else 'off'}")

    def set_channel_pan(self, channel: int, value: int) -> None:
        clamped = _clamp_pan(value)
        self.channel_pans[_channel_control(channel) + 1] = clamped
        print(f"[demo xr18] channel {channel} pan = {clamped}")

    def set_aux_fader(self, value: int) -> None:
        self.aux_fader = _clamp(value)
        print(f"[demo xr18] aux fader = {self.aux_fader}")

    def set_fx_return_fader(self, fx: int, value: int) -> None:
        clamped = _clamp(value)
        self.fx_return_faders[_fx_return_control(fx) - 16] = clamped
        print(f"[demo xr18] FX {fx} return fader = {clamped}")

    def set_aux_mute(self, muted: bool) -> None:
        self.aux_muted = muted
        print(f"[demo xr18] aux mute = {'on' if muted else 'off'}")

    def set_fx_return_mute(self, fx: int, muted: bool) -> None:
        self.fx_return_mutes[_fx_return_control(fx) - 16] = muted
        print(f"[demo xr18] FX {fx} return mute = {'on' if muted else 'off'}")

    def set_aux_pan(self, value: int) -> None:
        self.aux_pan = _clamp_pan(value)
        print(f"[demo xr18] aux pan = {self.aux_pan}")

    def set_fx_return_pan(self, fx: int, value: int) -> None:
        clamped = _clamp_pan(value)
        self.fx_return_pans[_fx_return_control(fx) - 16] = clamped
        print(f"[demo xr18] FX {fx} return pan = {clamped}")

    def set_main_fader(self, value: int) -> None:
        self.main_fader = _clamp(value)
        print(f"[demo xr18] main fader = {self.main_fader}")

    def set_dca_fader(self, dca: int, value: int) -> None:
        clamped = _clamp(value)
        self.dca_faders[_dca_control(dca) - 31] = clamped
        print(f"[demo xr18] DCA {dca} fader = {clamped}")

    def set_main_mute(self, muted: bool) -> None:
        self.main_muted = muted
        print(f"[demo xr18] main mute = {'on' if muted else 'off'}")


class XR18MessageRouter:
    """Parses XR18 MIDI feedback and dispatches to a listener."""

    def __init__(self, listener: XR18Listener):
        self._listener = listener

    def handle(self, message: mido.Message) -> None:
        if message.type != "control_change":
            return

        if message.channel == 0:
            if 0 <= message.control <= 15:
                self._listener.on_channel_fader(message.control + 1, message.value)
            elif message.control == 16:
                self._listener.on_aux_fader(message.value)
            elif 17 <= message.control <= 20:
                self._listener.on_fx_return_fader(message.control - 16, message.value)
            elif message.control == 31:
                self._listener.on_main_fader(message.value)
            elif 32 <= message.control <= 35:
                self._listener.on_dca_fader(message.control - 31, message.value)
            return

        if message.channel == 1:
            if 0 <= message.control <= 15:
                self._listener.on_channel_mute(message.control + 1, message.value >= 64)
            elif message.control == 16:
                self._listener.on_aux_mute(message.value >= 64)
            elif 17 <= message.control <= 20:
                self._listener.on_fx_return_mute(message.control - 16, message.value >= 64)
            elif message.control == 31:
                self._listener.on_main_mute(message.value >= 64)
            return

        if message.channel == 2:
            if 0 <= message.control <= 15:
                self._listener.on_channel_pan(message.control + 1, message.value)
            elif message.control == 16:
                self._listener.on_aux_pan(message.value)
            elif 17 <= message.control <= 20:
                self._listener.on_fx_return_pan(message.control - 16, message.value)


def _channel_control(channel: int) -> int:
    if not 1 <= channel <= 16:
        raise ValueError(f"channel must be 1..16, got {channel}")
    return channel - 1


def _dca_control(dca: int) -> int:
    if not 1 <= dca <= 4:
        raise ValueError(f"dca must be 1..4, got {dca}")
    return dca + 31


def _fx_return_control(fx: int) -> int:
    if not 1 <= fx <= 4:
        raise ValueError(f"fx must be 1..4, got {fx}")
    return fx + 16


def _clamp(value: int) -> int:
    return max(0, min(127, value))


def _clamp_pan(value: int) -> int:
    return max(1, min(127, value))
