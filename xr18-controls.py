from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

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
    FADER_MAX,
    FADER_MIN,
    MidoXR18Client,
    PAN_CENTER,
    PAN_MAX,
    PAN_MIN,
    XR18Client,
    XR18MessageRouter,
    XR18Ports,
)


KNOBS = range(1, 9)
BUTTONS = range(1, 17)
CHANNELS = range(1, 17)
FX_RETURNS = range(1, 5)
PC_AUX_KNOB = 8
SECOND_CHANNEL_PAGE_OFFSET = 8
METER_RING_STEPS = 11
PAN_RING_STEPS = 10
MAIN_DCA = 4
INPUT_POLL_INTERVAL = 0.01
RECONNECT_INTERVAL = 1.0
CONNECTION_CHECK_INTERVAL = 1.0


def _validate_index(name: str, value: int, count: int) -> None:
    if not 1 <= value <= count:
        raise ValueError(f"{name} must be 1..{count}, got {value}")


class PageId(Enum):
    FX = 0
    CHANNELS_1_8 = 1
    CHANNELS_9_16 = 2


class MixerTargetKind(Enum):
    CHANNEL = "channel"
    FX_RETURN = "fx_return"
    AUX = "aux"


@dataclass(frozen=True)
class MixerTarget:
    kind: MixerTargetKind
    index: int = 1

    @classmethod
    def channel(cls, channel: int) -> "MixerTarget":
        _validate_index("channel", channel, len(CHANNELS))
        return cls(MixerTargetKind.CHANNEL, channel)

    @classmethod
    def fx_return(cls, fx: int) -> "MixerTarget":
        _validate_index("fx", fx, len(FX_RETURNS))
        return cls(MixerTargetKind.FX_RETURN, fx)

    @classmethod
    def aux(cls) -> "MixerTarget":
        return cls(MixerTargetKind.AUX)


def _all_strip_targets() -> list[MixerTarget]:
    return [
        *(MixerTarget.channel(channel) for channel in CHANNELS),
        *(MixerTarget.fx_return(fx) for fx in FX_RETURNS),
        MixerTarget.aux(),
    ]


@dataclass(frozen=True)
class PageDefinition:
    page_id: PageId
    layer_light: Layer | None
    controls: dict[int, MixerTarget]

    def target_for_control(self, control: int) -> MixerTarget | None:
        return self.controls.get(control)

    def knob_for_target(self, target: MixerTarget) -> int | None:
        for knob, knob_target in self.controls.items():
            if knob_target == target:
                return knob
        return None


@dataclass
class StripState:
    fader: int = FADER_MIN
    pan: int = PAN_CENTER
    muted: bool = False


@dataclass
class MainState:
    fader: int = FADER_MIN
    dca4_fader: int = FADER_MIN
    muted: bool = False


@dataclass
class AppState:
    active_page: PageId = PageId.FX
    strips: dict[MixerTarget, StripState] = field(
        default_factory=lambda: {target: StripState() for target in _all_strip_targets()}
    )
    pan_knobs: set[int] = field(default_factory=set)
    main: MainState = field(default_factory=MainState)
    knob_step: int = 1


PAGE_DEFINITIONS = {
    PageId.FX: PageDefinition(
        page_id=PageId.FX,
        layer_light=None,
        controls={
            1: MixerTarget.fx_return(1),
            2: MixerTarget.fx_return(2),
            3: MixerTarget.fx_return(3),
            4: MixerTarget.fx_return(4),
            PC_AUX_KNOB: MixerTarget.aux(),
        },
    ),
    PageId.CHANNELS_1_8: PageDefinition(
        page_id=PageId.CHANNELS_1_8,
        layer_light=Layer.A,
        controls={knob: MixerTarget.channel(knob) for knob in KNOBS},
    ),
    PageId.CHANNELS_9_16: PageDefinition(
        page_id=PageId.CHANNELS_9_16,
        layer_light=Layer.B,
        controls={knob: MixerTarget.channel(knob + SECOND_CHANNEL_PAGE_OFFSET) for knob in KNOBS},
    ),
}


PAGE_FOR_LAYER = {
    Layer.A: PageId.CHANNELS_1_8,
    Layer.B: PageId.CHANNELS_9_16,
}


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


@dataclass(frozen=True)
class TapKey:
    page: PageId
    knob: int


class DoubleTapDetector:
    def __init__(self, timeout: float):
        self._timeout = timeout
        self._last_taps: dict[TapKey, float] = {}

    def remember(self, key: TapKey) -> None:
        self._last_taps[key] = time.monotonic()

    def consume(self, key: TapKey) -> bool:
        timestamp = self._last_taps.pop(key, None)
        return timestamp is not None and time.monotonic() - timestamp <= self._timeout

    def clear(self) -> None:
        self._last_taps.clear()


class MixerBridge:
    _double_tap_timeout = 0.15

    def __init__(self, xtouch: XTouchMiniClient, xr18: XR18Client, knob_step: int = 1):
        self._xtouch = xtouch
        self._xr18 = xr18
        self._state = AppState(knob_step=knob_step)
        self._main_fader_echo = FeedbackEchoFilter()
        self._dca4_fader_echo = FeedbackEchoFilter()
        self._double_taps = DoubleTapDetector(self._double_tap_timeout)
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            self._initialize_controller_locked()
            self._sync_main_locked()

    def refresh_controller(self) -> None:
        with self._lock:
            self._initialize_controller_locked()

    def sync_mixer(self) -> None:
        with self._lock:
            self._sync_main_locked()

    def on_knob_turn(self, knob: int, delta: int) -> None:
        with self._lock:
            target = self._current_page_locked().target_for_control(knob)
            if target is None:
                return

            state = self._strip_state(target)
            if knob in self._state.pan_knobs:
                state.pan = _clamp_pan(state.pan + self._scaled_delta(delta))
                self._set_target_pan(target, state.pan)
                self._refresh_knob_pan_locked(knob, target)
                return

            state.fader = _clamp_fader(state.fader + self._scaled_delta(delta))
            self._set_target_fader(target, state.fader)
            self._refresh_knob_fader_locked(knob, target)

    def on_knob_press(self, knob: int, down: bool) -> None:
        with self._lock:
            target = self._current_page_locked().target_for_control(knob)
            if target is None:
                return

            if down:
                self._state.pan_knobs.add(knob)
                if self._double_taps.consume(self._tap_key(knob)):
                    self._center_target_pan_locked(knob, target)
                self._refresh_knob_pan_locked(knob, target)
            else:
                self._state.pan_knobs.discard(knob)
                self._double_taps.remember(self._tap_key(knob))
                self._refresh_knob_fader_locked(knob, target)

    def on_button(self, button: int, down: bool) -> None:
        if not down:
            return

        with self._lock:
            target = self._current_page_locked().target_for_control(button)
            if target is not None:
                self._toggle_target_mute_locked(button, target)

    def on_layer(self, layer: Layer, down: bool) -> None:
        if not down:
            return

        with self._lock:
            page = PAGE_FOR_LAYER[layer]
            if self._state.active_page == page:
                page = PageId.FX

            if self._state.active_page != page:
                self._state.active_page = page
                self._state.pan_knobs.clear()
                self._double_taps.clear()
                self._refresh_layer_lights_locked()
                self._refresh_page_locked()

    def on_fader(self, value: int) -> None:
        with self._lock:
            self._state.main.fader = _clamp_fader(value)
            self._sync_main_locked()

    def on_channel_fader(self, channel: int, value: int) -> None:
        with self._lock:
            self._on_target_fader_locked(MixerTarget.channel(channel), value)

    def on_channel_mute(self, channel: int, muted: bool) -> None:
        with self._lock:
            self._on_target_mute_locked(MixerTarget.channel(channel), muted)

    def on_channel_pan(self, channel: int, value: int) -> None:
        with self._lock:
            self._on_target_pan_locked(MixerTarget.channel(channel), value)

    def on_aux_fader(self, value: int) -> None:
        with self._lock:
            self._on_target_fader_locked(MixerTarget.aux(), value)

    def on_fx_return_fader(self, fx: int, value: int) -> None:
        with self._lock:
            self._on_target_fader_locked(MixerTarget.fx_return(fx), value)

    def on_aux_mute(self, muted: bool) -> None:
        with self._lock:
            self._on_target_mute_locked(MixerTarget.aux(), muted)

    def on_fx_return_mute(self, fx: int, muted: bool) -> None:
        with self._lock:
            self._on_target_mute_locked(MixerTarget.fx_return(fx), muted)

    def on_aux_pan(self, value: int) -> None:
        with self._lock:
            self._on_target_pan_locked(MixerTarget.aux(), value)

    def on_fx_return_pan(self, fx: int, value: int) -> None:
        with self._lock:
            self._on_target_pan_locked(MixerTarget.fx_return(fx), value)

    def on_main_fader(self, value: int) -> None:
        with self._lock:
            if self._main_fader_echo.consume(value):
                self._state.main.fader = _clamp_fader(value)
                return

            value = _clamp_fader(value)
            self._state.main.fader = value
            if self._state.main.dca4_fader != value:
                self._state.main.dca4_fader = value
                self._send_dca4_fader_locked(value)

    def on_dca_fader(self, dca: int, value: int) -> None:
        if dca != MAIN_DCA:
            return

        with self._lock:
            if self._dca4_fader_echo.consume(value):
                self._state.main.dca4_fader = _clamp_fader(value)
                return

            value = _clamp_fader(value)
            self._state.main.dca4_fader = value
            if self._state.main.fader != value:
                self._state.main.fader = value
                self._send_main_fader_locked(value)

    def on_main_mute(self, muted: bool) -> None:
        with self._lock:
            self._state.main.muted = muted

    def _sync_main_locked(self) -> None:
        self._send_main_fader_locked(self._state.main.fader)
        self._state.main.dca4_fader = self._state.main.fader
        self._send_dca4_fader_locked(self._state.main.fader)
        self._xr18.set_main_mute(self._state.main.muted)

    def _initialize_controller_locked(self) -> None:
        self._xtouch.set_mackie_mode()
        self._xtouch.reset()
        self._refresh_layer_lights_locked()
        self._refresh_page_locked()

    def _send_main_fader_locked(self, value: int) -> None:
        clamped = _clamp_fader(value)
        self._main_fader_echo.remember(clamped)
        self._xr18.set_main_fader(clamped)

    def _send_dca4_fader_locked(self, value: int) -> None:
        clamped = _clamp_fader(value)
        self._dca4_fader_echo.remember(clamped)
        self._xr18.set_dca_fader(MAIN_DCA, clamped)

    def _refresh_layer_lights_locked(self) -> None:
        page = self._current_page_locked()
        self._xtouch.set_layer_light(Layer.A, page.layer_light == Layer.A)
        self._xtouch.set_layer_light(Layer.B, page.layer_light == Layer.B)

    def _refresh_page_locked(self) -> None:
        page = self._current_page_locked()
        for knob in KNOBS:
            target = page.target_for_control(knob)
            if target is None:
                self._xtouch.set_knob_ring(knob, FADER_MIN)
            elif knob in self._state.pan_knobs:
                self._refresh_knob_pan_locked(knob, target)
            else:
                self._refresh_knob_fader_locked(knob, target)

        for button in BUTTONS:
            target = page.target_for_control(button)
            if target is None:
                self._xtouch.set_button_light(button, False)
            else:
                self._refresh_mute_light_locked(button, target)

    def _refresh_knob_fader_locked(self, knob: int, target: MixerTarget) -> None:
        level = round(self._strip_state(target).fader * METER_RING_STEPS / FADER_MAX)
        self._xtouch.set_knob_ring(knob, level)

    def _refresh_knob_pan_locked(self, knob: int, target: MixerTarget) -> None:
        level = round((self._strip_state(target).pan - PAN_MIN) * PAN_RING_STEPS / (PAN_MAX - PAN_MIN)) + 1
        self._xtouch.set_knob_pan_ring(knob, level)

    def _refresh_mute_light_locked(self, button: int, target: MixerTarget) -> None:
        self._xtouch.set_button_light(button, not self._strip_state(target).muted)

    def _toggle_target_mute_locked(self, button: int, target: MixerTarget) -> None:
        state = self._strip_state(target)
        state.muted = not state.muted
        self._set_target_mute(target, state.muted)
        self._refresh_mute_light_locked(button, target)

    def _center_target_pan_locked(self, knob: int, target: MixerTarget) -> None:
        state = self._strip_state(target)
        state.pan = PAN_CENTER
        self._set_target_pan(target, state.pan)
        self._refresh_knob_pan_locked(knob, target)

    def _on_target_fader_locked(self, target: MixerTarget, value: int) -> None:
        state = self._strip_state(target)
        state.fader = _clamp_fader(value)
        knob = self._visible_knob_for_target_locked(target)
        if knob is not None and knob not in self._state.pan_knobs:
            self._refresh_knob_fader_locked(knob, target)

    def _on_target_mute_locked(self, target: MixerTarget, muted: bool) -> None:
        self._strip_state(target).muted = muted
        knob = self._visible_knob_for_target_locked(target)
        if knob is not None:
            self._refresh_mute_light_locked(knob, target)

    def _on_target_pan_locked(self, target: MixerTarget, value: int) -> None:
        state = self._strip_state(target)
        state.pan = _clamp_pan(value)
        knob = self._visible_knob_for_target_locked(target)
        if knob is not None and knob in self._state.pan_knobs:
            self._refresh_knob_pan_locked(knob, target)

    def _set_target_fader(self, target: MixerTarget, value: int) -> None:
        if target.kind == MixerTargetKind.CHANNEL:
            self._xr18.set_channel_fader(target.index, value)
        elif target.kind == MixerTargetKind.FX_RETURN:
            self._xr18.set_fx_return_fader(target.index, value)
        elif target.kind == MixerTargetKind.AUX:
            self._xr18.set_aux_fader(value)

    def _set_target_mute(self, target: MixerTarget, muted: bool) -> None:
        if target.kind == MixerTargetKind.CHANNEL:
            self._xr18.set_channel_mute(target.index, muted)
        elif target.kind == MixerTargetKind.FX_RETURN:
            self._xr18.set_fx_return_mute(target.index, muted)
        elif target.kind == MixerTargetKind.AUX:
            self._xr18.set_aux_mute(muted)

    def _set_target_pan(self, target: MixerTarget, value: int) -> None:
        if target.kind == MixerTargetKind.CHANNEL:
            self._xr18.set_channel_pan(target.index, value)
        elif target.kind == MixerTargetKind.FX_RETURN:
            self._xr18.set_fx_return_pan(target.index, value)
        elif target.kind == MixerTargetKind.AUX:
            self._xr18.set_aux_pan(value)

    def _strip_state(self, target: MixerTarget) -> StripState:
        return self._state.strips[target]

    def _current_page_locked(self) -> PageDefinition:
        return PAGE_DEFINITIONS[self._state.active_page]

    def _visible_knob_for_target_locked(self, target: MixerTarget) -> int | None:
        return self._current_page_locked().knob_for_target(target)

    def _tap_key(self, knob: int) -> TapKey:
        return TapKey(self._state.active_page, knob)

    def _scaled_delta(self, delta: int) -> int:
        return delta * self._state.knob_step


class _ReconnectableInputClient(Protocol):
    @property
    def connected(self) -> bool:
        ...

    @property
    def input_port(self):
        ...

    @property
    def description(self) -> str:
        ...

    def connect(self) -> bool:
        ...

    def disconnect(self, reason: str | None = None) -> None:
        ...

    def check_connection(self) -> None:
        ...


class _InputThread(threading.Thread):
    def __init__(
        self,
        client: _ReconnectableInputClient,
        router,
        name: str,
        on_connect: Callable[[], None] | None = None,
        debug: bool = False,
    ):
        super().__init__(name=name, daemon=True)
        self._client = client
        self._router = router
        self._on_connect = on_connect
        self._debug = debug
        self._stop_event = threading.Event()

    def run(self) -> None:
        next_connection_check = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()
            if now >= next_connection_check:
                self._client.check_connection()
                next_connection_check = now + CONNECTION_CHECK_INTERVAL

            if self._client.connect() and self._on_connect is not None:
                self._on_connect()

            if not self._client.connected:
                time.sleep(RECONNECT_INTERVAL)
                continue

            port = self._client.input_port
            if port is None:
                self._client.disconnect("input port disappeared")
                time.sleep(RECONNECT_INTERVAL)
                continue

            try:
                pending_messages = list(port.iter_pending())
            except Exception as error:
                self._client.disconnect(f"input failed: {error}")
                time.sleep(RECONNECT_INTERVAL)
                continue

            for message in pending_messages:
                if self._debug:
                    _debug_log(self.name, f"raw {message}")
                try:
                    self._router.handle(message)
                except Exception as error:
                    _debug_log(self.name, f"router error for {message}: {error!r}")
                    raise

            if not pending_messages:
                time.sleep(INPUT_POLL_INTERVAL)

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
    port_debug = lambda message: _debug_log("midi-ports", message)
    xtouch = MidoXTouchMiniClient(XTouchMiniPorts(args.xtouch), debug=port_debug)

    xr18: XR18Client | None = None
    mido_xr18: MidoXR18Client | None = None
    try:
        if args.demo:
            xr18 = DemoXR18Client()
            xr18_status = "XR18 demo mode: no mixer MIDI ports opened."
        else:
            mido_xr18 = MidoXR18Client(XR18Ports(args.xr18), debug=port_debug)
            xr18 = mido_xr18
            xr18_status = f"Watching XR18 MIDI ports matching {args.xr18!r}."

        assert xr18 is not None
        bridge = MixerBridge(xtouch, xr18, knob_step=args.knob_step)
        xtouch_debug = (lambda message: _debug_log("xtouch-router", message)) if args.debug_midi else None
        xtouch_router = XTouchMiniMessageRouter(bridge, debug=xtouch_debug)
        threads = [
            _InputThread(
                xtouch,
                xtouch_router,
                name="xtouch-midi",
                on_connect=bridge.refresh_controller,
                debug=args.debug_midi,
            )
        ]

        if mido_xr18 is not None:
            threads.append(
                _InputThread(
                    mido_xr18,
                    XR18MessageRouter(bridge),
                    name="xr18-midi",
                    on_connect=bridge.sync_mixer,
                    debug=args.debug_midi,
                )
            )

        return AppRuntime(
            bridge=bridge,
            xtouch=xtouch,
            xr18=xr18,
            threads=threads,
            status_messages=[
                f"Watching X-Touch Mini MIDI ports matching {args.xtouch!r}.",
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


def _clamp_fader(value: int) -> int:
    return max(FADER_MIN, min(FADER_MAX, value))


def _clamp_pan(value: int) -> int:
    return max(PAN_MIN, min(PAN_MAX, value))


def _debug_log(source: str, message: str) -> None:
    print(f"[{time.monotonic():.6f}] {source}: {message}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
