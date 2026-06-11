from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol

import mido

from xr18_controls.midi_ports import DebugLogger
from xr18_controls.midi_ports import ReconnectableMidiIO


FADER_MIN = 0
FADER_MAX = 127
PAN_MIN = 1
PAN_CENTER = 64
PAN_MAX = 127
MUTE_OFF = 0
MUTE_ON = 127
MUTE_THRESHOLD = 64


class CCLane(IntEnum):
    FADER = 0
    MUTE = 1
    PAN = 2
    BUS_1_SEND = 3
    BUS_2_SEND = 4
    BUS_3_SEND = 5
    BUS_4_SEND = 6
    BUS_5_SEND = 7
    BUS_6_SEND = 8
    FX_1_SEND = 9
    FX_2_SEND = 10
    FX_3_SEND = 11
    FX_4_SEND = 12


class StripControl(IntEnum):
    CHANNEL_1 = 0
    AUX = 16
    FX_RETURN_1 = 17
    MAIN = 31
    DCA_1 = 32


CHANNEL_COUNT = 16
FX_RETURN_COUNT = 4
DCA_COUNT = 4
BUS_SEND_COUNT = 6
FX_SEND_COUNT = 4


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

    def on_channel_bus_send(self, channel: int, bus: int, value: int) -> None:
        ...

    def on_channel_fx_send(self, channel: int, fx: int, value: int) -> None:
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

    def set_channel_bus_send(self, channel: int, bus: int, value: int) -> None:
        ...

    def set_channel_fx_send(self, channel: int, fx: int, value: int) -> None:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class XR18Ports:
    requested_name: str


class MidoXR18Client:
    """MIDO-backed XR18 client using the documented CC lanes."""

    def __init__(self, ports: XR18Ports, debug: DebugLogger | None = None):
        self._io = ReconnectableMidiIO(
            label="XR18",
            requested_name=ports.requested_name,
            debug=debug,
        )

    @property
    def connected(self) -> bool:
        return self._io.connected

    @property
    def input_port(self):
        return self._io.input_port

    @property
    def description(self) -> str:
        return self._io.description

    def connect(self) -> bool:
        return self._io.connect()

    def disconnect(self, reason: str | None = None) -> None:
        self._io.disconnect(reason)

    def check_connection(self) -> None:
        self._io.check_connection()

    def close(self) -> None:
        self._io.close()

    def send(self, message: mido.Message) -> bool:
        return self._io.send(message)

    def set_channel_fader(self, channel: int, value: int) -> None:
        self.send(_cc(CCLane.FADER, _channel_control(channel), _clamp_fader(value)))

    def set_channel_mute(self, channel: int, muted: bool) -> None:
        self.send(_cc(CCLane.MUTE, _channel_control(channel), _mute_value(muted)))

    def set_channel_pan(self, channel: int, value: int) -> None:
        self.send(_cc(CCLane.PAN, _channel_control(channel), _clamp_pan(value)))

    def set_aux_fader(self, value: int) -> None:
        self.send(_cc(CCLane.FADER, StripControl.AUX, _clamp_fader(value)))

    def set_fx_return_fader(self, fx: int, value: int) -> None:
        self.send(_cc(CCLane.FADER, _fx_return_control(fx), _clamp_fader(value)))

    def set_aux_mute(self, muted: bool) -> None:
        self.send(_cc(CCLane.MUTE, StripControl.AUX, _mute_value(muted)))

    def set_fx_return_mute(self, fx: int, muted: bool) -> None:
        self.send(_cc(CCLane.MUTE, _fx_return_control(fx), _mute_value(muted)))

    def set_aux_pan(self, value: int) -> None:
        self.send(_cc(CCLane.PAN, StripControl.AUX, _clamp_pan(value)))

    def set_fx_return_pan(self, fx: int, value: int) -> None:
        self.send(_cc(CCLane.PAN, _fx_return_control(fx), _clamp_pan(value)))

    def set_main_fader(self, value: int) -> None:
        self.send(_cc(CCLane.FADER, StripControl.MAIN, _clamp_fader(value)))

    def set_dca_fader(self, dca: int, value: int) -> None:
        self.send(_cc(CCLane.FADER, _dca_control(dca), _clamp_fader(value)))

    def set_main_mute(self, muted: bool) -> None:
        self.send(_cc(CCLane.MUTE, StripControl.MAIN, _mute_value(muted)))

    def set_channel_bus_send(self, channel: int, bus: int, value: int) -> None:
        self.send(_cc(_bus_send_lane(bus), _channel_control(channel), _clamp_fader(value)))

    def set_channel_fx_send(self, channel: int, fx: int, value: int) -> None:
        self.send(_cc(_fx_send_lane(fx), _channel_control(channel), _clamp_fader(value)))


class DemoXR18Client:
    """In-memory XR18 stand-in for developing without a connected mixer."""

    def __init__(self):
        self.channel_faders = {channel: FADER_MIN for channel in range(1, CHANNEL_COUNT + 1)}
        self.channel_mutes = {channel: False for channel in range(1, CHANNEL_COUNT + 1)}
        self.channel_pans = {channel: PAN_CENTER for channel in range(1, CHANNEL_COUNT + 1)}
        self.fx_return_faders = {fx: FADER_MIN for fx in range(1, FX_RETURN_COUNT + 1)}
        self.fx_return_mutes = {fx: False for fx in range(1, FX_RETURN_COUNT + 1)}
        self.fx_return_pans = {fx: PAN_CENTER for fx in range(1, FX_RETURN_COUNT + 1)}
        self.aux_fader = FADER_MIN
        self.aux_muted = False
        self.aux_pan = PAN_CENTER
        self.dca_faders = {dca: FADER_MIN for dca in range(1, DCA_COUNT + 1)}
        self.main_fader = FADER_MIN
        self.main_muted = False
        self.channel_bus_sends = {
            (c, b): FADER_MIN for c in range(1, CHANNEL_COUNT + 1) for b in range(1, BUS_SEND_COUNT + 1)
        }
        self.channel_fx_sends = {
            (c, f): FADER_MIN for c in range(1, CHANNEL_COUNT + 1) for f in range(1, FX_SEND_COUNT + 1)
        }

    def close(self) -> None:
        pass

    def set_channel_fader(self, channel: int, value: int) -> None:
        clamped = _clamp_fader(value)
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
        self.aux_fader = _clamp_fader(value)
        print(f"[demo xr18] aux fader = {self.aux_fader}")

    def set_fx_return_fader(self, fx: int, value: int) -> None:
        clamped = _clamp_fader(value)
        self.fx_return_faders[_fx_return_control(fx) - StripControl.AUX] = clamped
        print(f"[demo xr18] FX {fx} return fader = {clamped}")

    def set_aux_mute(self, muted: bool) -> None:
        self.aux_muted = muted
        print(f"[demo xr18] aux mute = {'on' if muted else 'off'}")

    def set_fx_return_mute(self, fx: int, muted: bool) -> None:
        self.fx_return_mutes[_fx_return_control(fx) - StripControl.AUX] = muted
        print(f"[demo xr18] FX {fx} return mute = {'on' if muted else 'off'}")

    def set_aux_pan(self, value: int) -> None:
        self.aux_pan = _clamp_pan(value)
        print(f"[demo xr18] aux pan = {self.aux_pan}")

    def set_fx_return_pan(self, fx: int, value: int) -> None:
        clamped = _clamp_pan(value)
        self.fx_return_pans[_fx_return_control(fx) - StripControl.AUX] = clamped
        print(f"[demo xr18] FX {fx} return pan = {clamped}")

    def set_main_fader(self, value: int) -> None:
        self.main_fader = _clamp_fader(value)
        print(f"[demo xr18] main fader = {self.main_fader}")

    def set_dca_fader(self, dca: int, value: int) -> None:
        clamped = _clamp_fader(value)
        self.dca_faders[_dca_control(dca) - StripControl.MAIN] = clamped
        print(f"[demo xr18] DCA {dca} fader = {clamped}")

    def set_main_mute(self, muted: bool) -> None:
        self.main_muted = muted
        print(f"[demo xr18] main mute = {'on' if muted else 'off'}")

    def set_channel_bus_send(self, channel: int, bus: int, value: int) -> None:
        clamped = _clamp_fader(value)
        self.channel_bus_sends[(channel, bus)] = clamped
        print(f"[demo xr18] channel {channel} bus {bus} send = {clamped}")

    def set_channel_fx_send(self, channel: int, fx: int, value: int) -> None:
        clamped = _clamp_fader(value)
        self.channel_fx_sends[(channel, fx)] = clamped
        print(f"[demo xr18] channel {channel} fx {fx} send = {clamped}")


class XR18MessageRouter:
    """Parses XR18 MIDI feedback and dispatches to a listener."""

    def __init__(self, listener: XR18Listener):
        self._listener = listener

    def handle(self, message: mido.Message) -> None:
        if message.type != "control_change":
            return

        if message.channel == CCLane.FADER:
            if _is_channel_control(message.control):
                self._listener.on_channel_fader(message.control + 1, message.value)
            elif message.control == StripControl.AUX:
                self._listener.on_aux_fader(message.value)
            elif _is_fx_return_control(message.control):
                self._listener.on_fx_return_fader(message.control - StripControl.AUX, message.value)
            elif message.control == StripControl.MAIN:
                self._listener.on_main_fader(message.value)
            elif _is_dca_control(message.control):
                self._listener.on_dca_fader(message.control - StripControl.MAIN, message.value)
            return

        if message.channel == CCLane.MUTE:
            muted = message.value >= MUTE_THRESHOLD
            if _is_channel_control(message.control):
                self._listener.on_channel_mute(message.control + 1, muted)
            elif message.control == StripControl.AUX:
                self._listener.on_aux_mute(muted)
            elif _is_fx_return_control(message.control):
                self._listener.on_fx_return_mute(message.control - StripControl.AUX, muted)
            elif message.control == StripControl.MAIN:
                self._listener.on_main_mute(muted)
            return

        if message.channel == CCLane.PAN:
            if _is_channel_control(message.control):
                self._listener.on_channel_pan(message.control + 1, message.value)
            elif message.control == StripControl.AUX:
                self._listener.on_aux_pan(message.value)
            elif _is_fx_return_control(message.control):
                self._listener.on_fx_return_pan(message.control - StripControl.AUX, message.value)
            return

        if _is_bus_send_lane(message.channel):
            bus = message.channel - CCLane.BUS_1_SEND + 1
            if _is_channel_control(message.control):
                self._listener.on_channel_bus_send(message.control + 1, bus, message.value)
            return

        if _is_fx_send_lane(message.channel):
            fx = message.channel - CCLane.FX_1_SEND + 1
            if _is_channel_control(message.control):
                self._listener.on_channel_fx_send(message.control + 1, fx, message.value)


def _channel_control(channel: int) -> int:
    _validate_index("channel", channel, CHANNEL_COUNT)
    return StripControl.CHANNEL_1 + channel - 1


def _dca_control(dca: int) -> int:
    _validate_index("dca", dca, DCA_COUNT)
    return StripControl.DCA_1 + dca - 1


def _fx_return_control(fx: int) -> int:
    _validate_index("fx", fx, FX_RETURN_COUNT)
    return StripControl.FX_RETURN_1 + fx - 1


def _bus_send_lane(bus: int) -> CCLane:
    _validate_index("bus", bus, BUS_SEND_COUNT)
    return CCLane(CCLane.BUS_1_SEND + bus - 1)


def _fx_send_lane(fx: int) -> CCLane:
    _validate_index("fx_send", fx, FX_SEND_COUNT)
    return CCLane(CCLane.FX_1_SEND + fx - 1)


def _is_bus_send_lane(channel: int) -> bool:
    return CCLane.BUS_1_SEND <= channel < CCLane.BUS_1_SEND + BUS_SEND_COUNT


def _is_fx_send_lane(channel: int) -> bool:
    return CCLane.FX_1_SEND <= channel < CCLane.FX_1_SEND + FX_SEND_COUNT


def _cc(lane: CCLane, control: int, value: int) -> mido.Message:
    return mido.Message("control_change", channel=int(lane), control=int(control), value=value)


def _mute_value(muted: bool) -> int:
    return MUTE_ON if muted else MUTE_OFF


def _is_channel_control(control: int) -> bool:
    return StripControl.CHANNEL_1 <= control < StripControl.CHANNEL_1 + CHANNEL_COUNT


def _is_fx_return_control(control: int) -> bool:
    return StripControl.FX_RETURN_1 <= control < StripControl.FX_RETURN_1 + FX_RETURN_COUNT


def _is_dca_control(control: int) -> bool:
    return StripControl.DCA_1 <= control < StripControl.DCA_1 + DCA_COUNT


def _validate_index(name: str, value: int, count: int) -> None:
    if not 1 <= value <= count:
        raise ValueError(f"{name} must be 1..{count}, got {value}")


def _clamp_fader(value: int) -> int:
    return max(FADER_MIN, min(FADER_MAX, value))


def _clamp_pan(value: int) -> int:
    return max(PAN_MIN, min(PAN_MAX, value))
