from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import mido


class XR18Listener(Protocol):
    def on_channel_fader(self, channel: int, value: int) -> None:
        ...

    def on_channel_mute(self, channel: int, muted: bool) -> None:
        ...

    def on_main_fader(self, value: int) -> None:
        ...

    def on_main_mute(self, muted: bool) -> None:
        ...


class XR18Client(Protocol):
    def set_channel_fader(self, channel: int, value: int) -> None:
        ...

    def set_channel_mute(self, channel: int, muted: bool) -> None:
        ...

    def set_main_fader(self, value: int) -> None:
        ...

    def set_main_mute(self, muted: bool) -> None:
        ...


@dataclass(frozen=True)
class XR18Ports:
    input_name: str
    output_name: str


class MidoXR18Client:
    """MIDO-backed XR18 client using the documented CC lanes."""

    def __init__(self, ports: XR18Ports):
        self._input = mido.open_input(ports.input_name)
        self._output = mido.open_output(ports.output_name)

    def close(self) -> None:
        self._input.close()
        self._output.close()

    def send(self, message: mido.Message) -> None:
        self._output.send(message)

    def set_channel_fader(self, channel: int, value: int) -> None:
        self.send(mido.Message("control_change", channel=0, control=_channel_control(channel), value=_clamp(value)))

    def set_channel_mute(self, channel: int, muted: bool) -> None:
        self.send(mido.Message("control_change", channel=1, control=_channel_control(channel), value=127 if muted else 0))

    def set_main_fader(self, value: int) -> None:
        self.send(mido.Message("control_change", channel=0, control=31, value=_clamp(value)))

    def set_main_mute(self, muted: bool) -> None:
        self.send(mido.Message("control_change", channel=1, control=31, value=127 if muted else 0))


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
            elif message.control == 31:
                self._listener.on_main_fader(message.value)
            return

        if message.channel == 1:
            if 0 <= message.control <= 15:
                self._listener.on_channel_mute(message.control + 1, message.value >= 64)
            elif message.control == 31:
                self._listener.on_main_mute(message.value >= 64)


def _channel_control(channel: int) -> int:
    if not 1 <= channel <= 16:
        raise ValueError(f"channel must be 1..16, got {channel}")
    return channel - 1


def _clamp(value: int) -> int:
    return max(0, min(127, value))
