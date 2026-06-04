from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

import mido


class Layer(Enum):
    A = "A"
    B = "B"


class XTouchMiniListener(Protocol):
    def on_knob_turn(self, knob: int, delta: int) -> None:
        ...

    def on_button(self, button: int, down: bool) -> None:
        ...

    def on_layer(self, layer: Layer, down: bool) -> None:
        ...

    def on_fader(self, value: int) -> None:
        ...


class XTouchMiniClient(Protocol):
    def set_mackie_mode(self) -> None:
        ...

    def set_layer_light(self, layer: Layer, on: bool) -> None:
        ...

    def set_button_light(self, button: int, on: bool) -> None:
        ...

    def set_knob_ring(self, knob: int, level: int) -> None:
        ...

    def reset(self) -> None:
        ...


@dataclass(frozen=True)
class XTouchMiniPorts:
    input_name: str
    output_name: str


class MidoXTouchMiniClient:
    """MIDO-backed X-Touch Mini output client in Mackie Control mode."""

    _top_buttons = (0x59, 0x5A, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D)
    _bottom_buttons = (0x57, 0x58, 0x5B, 0x5C, 0x56, 0x5D, 0x5E, 0x5F)
    _layer_buttons = {Layer.A: 0x54, Layer.B: 0x55}

    def __init__(self, ports: XTouchMiniPorts):
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

    def set_mackie_mode(self) -> None:
        self.send(mido.Message("control_change", channel=0, control=127, value=1))

    def set_layer_light(self, layer: Layer, on: bool) -> None:
        self.send(mido.Message("note_on", note=self._layer_buttons[layer], velocity=127 if on else 0))

    def set_button_light(self, button: int, on: bool) -> None:
        if not 1 <= button <= 16:
            raise ValueError(f"button must be 1..16, got {button}")
        note = self._button_note(button)
        self.send(mido.Message("note_on", note=note, velocity=127 if on else 0))

    def set_knob_ring(self, knob: int, level: int) -> None:
        if not 1 <= knob <= 8:
            raise ValueError(f"knob must be 1..8, got {knob}")
        clamped = max(0, min(level, 11))
        self.send(mido.Message("control_change", channel=0, control=0x2F + knob, value=clamped + 32))

    def reset(self) -> None:
        for knob in range(1, 9):
            self.set_knob_ring(knob, 0)
        for button in range(1, 17):
            self.set_button_light(button, False)
        self.set_layer_light(Layer.A, True)
        self.set_layer_light(Layer.B, False)

    @classmethod
    def _button_note(cls, button: int) -> int:
        if 1 <= button <= 8:
            return cls._top_buttons[button - 1]
        return cls._bottom_buttons[button - 9]


class XTouchMiniMessageRouter:
    """Parses X-Touch Mini MIDI input and dispatches to a listener."""

    _master_fader_channel = 8

    def __init__(self, listener: XTouchMiniListener, debug: Callable[[str], None] | None = None):
        self._listener = listener
        self._debug = debug

    def handle(self, message: mido.Message) -> None:
        if message.type == "control_change" and message.channel == 0 and 0x10 <= message.control <= 0x17:
            knob = message.control - 0x0F
            delta = _signed_knob_delta(message.value)
            self._log(f"knob={knob} delta={delta}")
            self._listener.on_knob_turn(knob, delta)
            return

        if message.type == "pitchwheel" and message.channel == self._master_fader_channel:
            value = _pitchwheel_to_fader(message.pitch)
            self._log(f"master_fader={value}")
            self._listener.on_fader(value)
            return

        if message.type not in {"note_on", "note_off"}:
            self._log(f"ignored {message}")
            return

        down = message.type == "note_on" and message.velocity > 0
        note = message.note

        if note in {0x54, 0x55}:
            layer = Layer.A if note == 0x54 else Layer.B
            self._log(f"layer={layer.value} down={down}")
            self._listener.on_layer(layer, down)
            return

        button = _note_to_button(note)
        if button is not None:
            self._log(f"button={button} down={down}")
            self._listener.on_button(button, down)
            return

        self._log(f"unmapped_note={note} down={down}")

    def _log(self, message: str) -> None:
        if self._debug is not None:
            self._debug(message)


def _signed_knob_delta(value: int) -> int:
    return value if value < 0x40 else -(value - 0x40)


def _pitchwheel_to_fader(pitch: int) -> int:
    return max(0, min(127, round((pitch + 8192) * 127 / 16383)))


def _note_to_button(note: int) -> int | None:
    top_notes = [0x59, 0x5A, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D]
    bottom_notes = [0x57, 0x58, 0x5B, 0x5C, 0x56, 0x5D, 0x5E, 0x5F]
    if note in top_notes:
        return top_notes.index(note) + 1
    if note in bottom_notes:
        return bottom_notes.index(note) + 9
    return None
