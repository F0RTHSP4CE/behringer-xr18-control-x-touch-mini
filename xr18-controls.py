from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

import mido

from xr18_controls.xtouch_mini import (
    Layer,
    MidoXTouchMiniClient,
    XTouchMiniClient,
    XTouchMiniMessageRouter,
    XTouchMiniPorts,
)
from xr18_controls.xr18 import (
    DemoXR18Client,
    MidoXR18Client,
    XR18Client,
    XR18MessageRouter,
    XR18Ports,
)


@dataclass
class ChannelState:
    fader: int = 0
    requested_mute: bool = False
    applied_mute: bool = False


@dataclass
class AppState:
    active_layer: Layer = Layer.A
    channels: dict[int, ChannelState] = field(default_factory=lambda: {index: ChannelState() for index in range(1, 17)})
    main_fader: int = 0
    dca4_fader: int = 0
    main_muted: bool = False
    knob_step: int = 1


class FeedbackEchoFilter:
    def __init__(self, timeout: float = 1.0):
        self._timeout = timeout
        self._pending: list[tuple[int, float]] = []

    def remember(self, value: int) -> None:
        self._trim()
        self._pending.append((value, time.monotonic()))

    def consume(self, value: int) -> bool:
        self._trim()
        for index, (pending_value, _) in enumerate(self._pending):
            if pending_value == value:
                self._pending.pop(index)
                return True
        return False

    def _trim(self) -> None:
        cutoff = time.monotonic() - self._timeout
        expired_count = next(
            (index for index, (_, timestamp) in enumerate(self._pending) if timestamp >= cutoff),
            len(self._pending),
        )
        del self._pending[:expired_count]


class MixerBridge:
    def __init__(self, xtouch: XTouchMiniClient, xr18: XR18Client, knob_step: int = 1):
        self._xtouch = xtouch
        self._xr18 = xr18
        self._state = AppState(knob_step=knob_step)
        self._main_fader_echo = FeedbackEchoFilter()
        self._dca4_fader_echo = FeedbackEchoFilter()
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
            if button <= 8:
                channel = self._channel_for_button_locked(button)
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
            state = self._state.channels[channel]
            state.requested_mute = muted
            state.applied_mute = muted
            if self._channel_is_visible_locked(channel):
                self._set_mute_light_locked(channel)

    def on_main_fader(self, value: int) -> None:
        with self._lock:
            if self._main_fader_echo.consume(value):
                self._state.main_fader = value
                return

            self._state.main_fader = value
            if self._state.dca4_fader != value:
                self._state.dca4_fader = value
                self._send_dca4_fader_locked(value)

    def on_dca_fader(self, dca: int, value: int) -> None:
        if dca != 4:
            return

        with self._lock:
            if self._dca4_fader_echo.consume(value):
                self._state.dca4_fader = value
                return

            self._state.dca4_fader = value
            if self._state.main_fader != value:
                self._state.main_fader = value
                self._send_main_fader_locked(value)

    def on_main_mute(self, muted: bool) -> None:
        with self._lock:
            self._state.main_muted = muted

    def _toggle_mute_locked(self, channel: int) -> None:
        state = self._state.channels[channel]
        state.requested_mute = not state.requested_mute
        self._sync_channel_mute_locked(channel)
        if self._channel_is_visible_locked(channel):
            self._set_mute_light_locked(channel)

    def _sync_channel_mute_locked(self, channel: int) -> None:
        state = self._state.channels[channel]
        desired = state.requested_mute
        if state.applied_mute != desired:
            state.applied_mute = desired
            self._xr18.set_channel_mute(channel, desired)

    def _sync_main_locked(self) -> None:
        self._send_main_fader_locked(self._state.main_fader)
        self._state.dca4_fader = self._state.main_fader
        self._send_dca4_fader_locked(self._state.main_fader)
        self._xr18.set_main_mute(self._state.main_muted)

    def _send_main_fader_locked(self, value: int) -> None:
        clamped = _clamp(value)
        self._main_fader_echo.remember(clamped)
        self._xr18.set_main_fader(clamped)

    def _send_dca4_fader_locked(self, value: int) -> None:
        clamped = _clamp(value)
        self._dca4_fader_echo.remember(clamped)
        self._xr18.set_dca_fader(4, clamped)

    def _refresh_layer_lights_locked(self) -> None:
        self._xtouch.set_layer_light(Layer.A, self._state.active_layer == Layer.A)
        self._xtouch.set_layer_light(Layer.B, self._state.active_layer == Layer.B)

    def _refresh_visible_bank_locked(self) -> None:
        start = self._active_bank_start_locked()
        for knob in range(1, 9):
            channel = start + knob - 1
            self._refresh_knob_locked(knob, channel)
            self._set_mute_light_locked(channel)
            self._xtouch.set_button_light(knob + 8, False)

    def _refresh_knob_locked(self, knob: int, channel: int) -> None:
        level = round(self._state.channels[channel].fader * 11 / 127)
        self._xtouch.set_knob_ring(knob, level)

    def _channel_for_knob_locked(self, knob: int) -> int:
        if not 1 <= knob <= 8:
            raise ValueError(f"knob must be 1..8, got {knob}")
        return self._active_bank_start_locked() + knob - 1

    def _channel_for_button_locked(self, button: int) -> int:
        if not 1 <= button <= 16:
            raise ValueError(f"button must be 1..16, got {button}")
        bank_button = button if button <= 8 else button - 8
        return self._active_bank_start_locked() + bank_button - 1

    def _channel_is_visible_locked(self, channel: int) -> bool:
        start = self._active_bank_start_locked()
        return start <= channel <= start + 7

    def _visible_knob(self, channel: int) -> int:
        return channel - self._active_bank_start_locked() + 1

    def _mute_button(self, channel: int) -> int:
        return self._visible_knob(channel)

    def _set_mute_light_locked(self, channel: int) -> None:
        self._xtouch.set_button_light(self._mute_button(channel), not self._state.channels[channel].applied_mute)

    def _active_bank_start_locked(self) -> int:
        return 1 if self._state.active_layer == Layer.A else 9


class _InputThread(threading.Thread):
    def __init__(self, port: mido.ports.BaseInput, router, name: str, debug: bool = False):
        super().__init__(name=name, daemon=True)
        self._port = port
        self._router = router
        self._debug = debug
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            had_message = False
            for message in self._port.iter_pending():
                had_message = True
                if self._debug:
                    _debug_log(self.name, f"raw {message}")
                try:
                    self._router.handle(message)
                except Exception as error:
                    _debug_log(self.name, f"router error for {message}: {error!r}")
                    raise
            if not had_message:
                time.sleep(0.01)

    def stop(self) -> None:
        self._stop_event.set()


@dataclass
class AppRuntime:
    bridge: MixerBridge
    xtouch: MidoXTouchMiniClient
    xr18: XR18Client
    threads: list[_InputThread]
    status_messages: list[str]

    def start_threads(self) -> None:
        for thread in self.threads:
            thread.start()

    def close(self) -> None:
        for thread in self.threads:
            thread.stop()
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(timeout=1)
        self.xtouch.close()
        self.xr18.close()


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
    parser.add_argument("--demo", action="store_true", help="Run without XR18 MIDI ports and print mixer actions")
    parser.add_argument("--debug-midi", action="store_true", help="Print raw and routed MIDI input events")
    parser.add_argument("--list-ports", action="store_true", help="List MIDI ports and exit")
    return parser


def _print_ports() -> None:
    print("Input ports:")
    for name in mido.get_input_names():
        print(f"  {name}")
    print("Output ports:")
    for name in mido.get_output_names():
        print(f"  {name}")


def _open_runtime(args: argparse.Namespace) -> AppRuntime:
    input_names = mido.get_input_names()
    output_names = mido.get_output_names()

    xtouch_input = _pick_port_name(args.xtouch, input_names)
    xtouch_output = _pick_port_name(args.xtouch, output_names)
    xtouch = MidoXTouchMiniClient(XTouchMiniPorts(xtouch_input, xtouch_output))

    xr18: XR18Client | None = None
    mido_xr18: MidoXR18Client | None = None
    try:
        if args.demo:
            xr18 = DemoXR18Client()
            xr18_status = "XR18 demo mode: no mixer MIDI ports opened."
        else:
            xr18_input = _pick_port_name(args.xr18, input_names)
            xr18_output = _pick_port_name(args.xr18, output_names)
            mido_xr18 = MidoXR18Client(XR18Ports(xr18_input, xr18_output))
            xr18 = mido_xr18
            xr18_status = f"Connected XR18: {xr18_input} / {xr18_output}"

        assert xr18 is not None
        bridge = MixerBridge(xtouch, xr18, knob_step=args.knob_step)
        xtouch_debug = (lambda message: _debug_log("xtouch-router", message)) if args.debug_midi else None
        xtouch_router = XTouchMiniMessageRouter(bridge, debug=xtouch_debug)
        threads = [_InputThread(xtouch.input_port, xtouch_router, name="xtouch-midi", debug=args.debug_midi)]

        if mido_xr18 is not None:
            threads.append(
                _InputThread(
                    mido_xr18.input_port,
                    XR18MessageRouter(bridge),
                    name="xr18-midi",
                    debug=args.debug_midi,
                )
            )

        return AppRuntime(
            bridge=bridge,
            xtouch=xtouch,
            xr18=xr18,
            threads=threads,
            status_messages=[
                f"Connected X-Touch Mini: {xtouch_input} / {xtouch_output}",
                xr18_status,
            ],
        )
    except Exception:
        xtouch.close()
        if xr18 is not None:
            xr18.close()
        raise


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.list_ports:
        _print_ports()
        return 0

    runtime = _open_runtime(args)
    try:
        runtime.bridge.start()
        runtime.start_threads()
        for message in runtime.status_messages:
            print(message)
        print("Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        runtime.close()


def _clamp(value: int) -> int:
    return max(0, min(127, value))


def _debug_log(source: str, message: str) -> None:
    print(f"[{time.monotonic():.6f}] {source}: {message}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
