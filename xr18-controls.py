from __future__ import annotations

import argparse
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

import mido

from xr18_controls.xtouch_mini import Layer, MidoXTouchMiniClient, XTouchMiniMessageRouter, XTouchMiniPorts
from xr18_controls.xr18 import MidoXR18Client, XR18MessageRouter, XR18Ports


@dataclass
class ChannelState:
    fader: int = 0
    requested_mute: bool = False
    applied_mute: bool = False
    solo: bool = False


@dataclass
class AppState:
    active_layer: Layer = Layer.A
    channels: dict[int, ChannelState] = field(default_factory=lambda: {index: ChannelState() for index in range(1, 17)})
    main_fader: int = 0
    main_muted: bool = False
    knob_step: int = 1


class MixerBridge:
    def __init__(self, xtouch: MidoXTouchMiniClient, xr18: MidoXR18Client, knob_step: int = 1):
        self._xtouch = xtouch
        self._xr18 = xr18
        self._state = AppState(knob_step=knob_step)
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            self._xtouch.set_mackie_mode()
            self._xtouch.reset()
            self._refresh_layer_lights_locked()
            self._refresh_visible_bank_locked()
            self._sync_main_locked()

    def on_knob_turn(self, knob: int, delta: int) -> None:
        with self._lock:
            channel = self._channel_for_knob_locked(knob)
            state = self._state.channels[channel]
            state.fader = _clamp(state.fader + delta * self._state.knob_step)
            self._xr18.set_channel_fader(channel, state.fader)
            self._refresh_knob_locked(knob, channel)

    def on_button(self, button: int, down: bool) -> None:
        if not down:
            return

        with self._lock:
            channel = self._channel_for_button_locked(button)
            if button <= 8:
                self._toggle_solo_locked(channel)
            else:
                self._toggle_mute_locked(channel)

    def on_layer(self, layer: Layer, down: bool) -> None:
        if not down:
            return

        with self._lock:
            if self._state.active_layer != layer:
                self._state.active_layer = layer
                self._refresh_layer_lights_locked()
                self._refresh_visible_bank_locked()

    def on_fader(self, value: int) -> None:
        with self._lock:
            self._state.main_fader = value
            self._sync_main_locked()

    def on_channel_fader(self, channel: int, value: int) -> None:
        with self._lock:
            self._state.channels[channel].fader = value
            if self._channel_is_visible_locked(channel):
                self._refresh_knob_locked(self._visible_knob(channel), channel)

    def on_channel_mute(self, channel: int, muted: bool) -> None:
        with self._lock:
            self._state.channels[channel].requested_mute = muted
            self._state.channels[channel].applied_mute = muted
            if self._channel_is_visible_locked(channel):
                self._xtouch.set_button_light(self._visible_button(channel), muted)

    def on_main_fader(self, value: int) -> None:
        with self._lock:
            self._state.main_fader = value

    def on_main_mute(self, muted: bool) -> None:
        with self._lock:
            self._state.main_muted = muted

    def _toggle_mute_locked(self, channel: int) -> None:
        state = self._state.channels[channel]
        state.requested_mute = not state.requested_mute
        self._sync_channel_mute_locked(channel)
        if self._channel_is_visible_locked(channel):
            self._xtouch.set_button_light(self._visible_button(channel), state.applied_mute)

    def _toggle_solo_locked(self, channel: int) -> None:
        state = self._state.channels[channel]
        state.solo = not state.solo
        self._apply_solo_locked()
        self._refresh_visible_bank_locked()

    def _apply_solo_locked(self) -> None:
        solo_channels = {channel for channel, state in self._state.channels.items() if state.solo}
        for channel, state in self._state.channels.items():
            desired = state.requested_mute or (bool(solo_channels) and channel not in solo_channels)
            if state.applied_mute != desired:
                state.applied_mute = desired
                self._xr18.set_channel_mute(channel, desired)

    def _sync_channel_mute_locked(self, channel: int) -> None:
        state = self._state.channels[channel]
        solo_channels = {index for index, current in self._state.channels.items() if current.solo}
        desired = state.requested_mute or (bool(solo_channels) and channel not in solo_channels)
        if state.applied_mute != desired:
            state.applied_mute = desired
            self._xr18.set_channel_mute(channel, desired)

    def _sync_main_locked(self) -> None:
        self._xr18.set_main_fader(self._state.main_fader)
        self._xr18.set_main_mute(self._state.main_muted)

    def _refresh_layer_lights_locked(self) -> None:
        self._xtouch.set_layer_light(Layer.A, self._state.active_layer == Layer.A)
        self._xtouch.set_layer_light(Layer.B, self._state.active_layer == Layer.B)

    def _refresh_visible_bank_locked(self) -> None:
        start = 1 if self._state.active_layer == Layer.A else 9
        for knob in range(1, 9):
            channel = start + knob - 1
            self._refresh_knob_locked(knob, channel)
            self._xtouch.set_button_light(knob, self._state.channels[channel].solo)
            self._xtouch.set_button_light(knob + 8, self._state.channels[channel].applied_mute)

    def _refresh_knob_locked(self, knob: int, channel: int) -> None:
        level = round(self._state.channels[channel].fader * 11 / 127)
        self._xtouch.set_knob_ring(knob, level)

    def _channel_for_knob_locked(self, knob: int) -> int:
        if not 1 <= knob <= 8:
            raise ValueError(f"knob must be 1..8, got {knob}")
        return (1 if self._state.active_layer == Layer.A else 9) + knob - 1

    def _channel_for_button_locked(self, button: int) -> int:
        if not 1 <= button <= 8:
            raise ValueError(f"button must be 1..8, got {button}")
        return (1 if self._state.active_layer == Layer.A else 9) + button - 1

    def _channel_is_visible_locked(self, channel: int) -> bool:
        start = 1 if self._state.active_layer == Layer.A else 9
        return start <= channel <= start + 7

    def _visible_knob(self, channel: int) -> int:
        start = 1 if self._state.active_layer == Layer.A else 9
        return channel - start + 1

    def _visible_button(self, channel: int) -> int:
        return self._visible_knob(channel)


class _InputThread(threading.Thread):
    def __init__(self, port: mido.ports.BaseInput, router, name: str):
        super().__init__(name=name, daemon=True)
        self._port = port
        self._router = router
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            had_message = False
            for message in self._port.iter_pending():
                had_message = True
                self._router.handle(message)
            if not had_message:
                time.sleep(0.01)

    def stop(self) -> None:
        self._stop_event.set()


def _pick_port_name(requested: str, available: Iterable[str]) -> str:
    available_list = list(available)
    exact = [name for name in available_list if name == requested]
    if exact:
        return exact[0]

    matches = [name for name in available_list if requested.lower() in name.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise RuntimeError(f"No MIDI port matches '{requested}'. Available: {available_list}")
    raise RuntimeError(f"Multiple MIDI ports match '{requested}': {matches}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bridge a Behringer X-Touch Mini to an XR18 over MIDI.")
    parser.add_argument("--xtouch", default="X-TOUCH MINI", help="X-Touch Mini port name or substring")
    parser.add_argument("--xr18", default="XR18", help="XR18 port name or substring")
    parser.add_argument("--knob-step", type=int, default=1, help="Fader step per X-Touch knob detent")
    parser.add_argument("--list-ports", action="store_true", help="List MIDI ports and exit")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.list_ports:
        print("Input ports:")
        for name in mido.get_input_names():
            print(f"  {name}")
        print("Output ports:")
        for name in mido.get_output_names():
            print(f"  {name}")
        return 0

    xtouch_input = _pick_port_name(args.xtouch, mido.get_input_names())
    xtouch_output = _pick_port_name(args.xtouch, mido.get_output_names())
    xr18_input = _pick_port_name(args.xr18, mido.get_input_names())
    xr18_output = _pick_port_name(args.xr18, mido.get_output_names())

    xtouch = MidoXTouchMiniClient(XTouchMiniPorts(xtouch_input, xtouch_output))
    xr18 = MidoXR18Client(XR18Ports(xr18_input, xr18_output))
    bridge = MixerBridge(xtouch, xr18, knob_step=args.knob_step)

    xtouch_router = XTouchMiniMessageRouter(bridge)
    xr18_router = XR18MessageRouter(bridge)
    xtouch_thread = _InputThread(xtouch._input, xtouch_router, name="xtouch-midi")
    xr18_thread = _InputThread(xr18._input, xr18_router, name="xr18-midi")

    try:
        bridge.start()
        xtouch_thread.start()
        xr18_thread.start()
        print(f"Connected X-Touch Mini: {xtouch_input} / {xtouch_output}")
        print(f"Connected XR18: {xr18_input} / {xr18_output}")
        print("Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        xtouch_thread.stop()
        xr18_thread.stop()
        xtouch.close()
        xr18.close()


def _clamp(value: int) -> int:
    return max(0, min(127, value))


if __name__ == "__main__":
    raise SystemExit(main())
