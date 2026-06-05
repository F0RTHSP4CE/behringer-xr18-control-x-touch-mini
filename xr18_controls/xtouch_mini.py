from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from enum import IntEnum
from typing import Callable, Protocol

import mido


KNOB_COUNT = 8
BUTTON_COUNT = 16
RING_LEVEL_MIN = 0
RING_LEVEL_MAX = 11
PAN_RING_LEVEL_MIN = 1
PAN_RING_LEVEL_MAX = 11
RING_LEVEL_OFFSET = 32
MIDI_OFF = 0
MIDI_ON = 127
MACKIE_CHANNEL = 0
RELATIVE_ENCODER_REVERSE_BASE = 0x40
PITCHWHEEL_MIN = -8192
PITCHWHEEL_RANGE = 16383


class MackieCC(IntEnum):
    ENCODER_1 = 0x10
    RING_1 = 0x30
    SET_MODE = 0x7F


class MackieNote(IntEnum):
    LAYER_A = 0x54
    LAYER_B = 0x55
    KNOB_PRESS_1 = 0x20


TOP_BUTTON_NOTES = (0x59, 0x5A, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D)
BOTTOM_BUTTON_NOTES = (0x57, 0x58, 0x5B, 0x5C, 0x56, 0x5D, 0x5E, 0x5F)


class Layer(Enum):
    A = "A"
    B = "B"


LAYER_BUTTONS = {Layer.A: MackieNote.LAYER_A, Layer.B: MackieNote.LAYER_B}
NOTE_TO_LAYER = {MackieNote.LAYER_A: Layer.A, MackieNote.LAYER_B: Layer.B}
NOTE_TO_TOP_BUTTON = {note: index for index, note in enumerate(TOP_BUTTON_NOTES, start=1)}
NOTE_TO_BOTTOM_BUTTON = {note: index + KNOB_COUNT for index, note in enumerate(BOTTOM_BUTTON_NOTES, start=1)}


class XTouchMiniListener(Protocol):
    def on_knob_turn(self, knob: int, delta: int) -> None:
        ...

    def on_knob_press(self, knob: int, down: bool) -> None:
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

    def set_knob_pan_ring(self, knob: int, level: int) -> None:
        ...

    def reset(self) -> None:
        ...


@dataclass(frozen=True)
class XTouchMiniPorts:
    input_name: str
    output_name: str


class MidoXTouchMiniClient:
    """MIDO-backed X-Touch Mini output client in Mackie Control mode."""

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
        self.send(
            mido.Message("control_change", channel=MACKIE_CHANNEL, control=MackieCC.SET_MODE, value=1)
        )

    def set_layer_light(self, layer: Layer, on: bool) -> None:
        self.send(_note(LAYER_BUTTONS[layer], on))

    def set_button_light(self, button: int, on: bool) -> None:
        _validate_index("button", button, BUTTON_COUNT)
        note = self._button_note(button)
        self.send(_note(note, on))

    def set_knob_ring(self, knob: int, level: int) -> None:
        _validate_index("knob", knob, KNOB_COUNT)
        clamped = max(RING_LEVEL_MIN, min(level, RING_LEVEL_MAX))
        self.send(_ring_cc(knob, clamped + RING_LEVEL_OFFSET))

    def set_knob_pan_ring(self, knob: int, level: int) -> None:
        _validate_index("knob", knob, KNOB_COUNT)
        clamped = max(PAN_RING_LEVEL_MIN, min(level, PAN_RING_LEVEL_MAX))
        self.send(_ring_cc(knob, clamped))

    def reset(self) -> None:
        for knob in range(1, KNOB_COUNT + 1):
            self.set_knob_ring(knob, 0)
        for button in range(1, BUTTON_COUNT + 1):
            self.set_button_light(button, False)
        self.set_layer_light(Layer.A, True)
        self.set_layer_light(Layer.B, False)

    @classmethod
    def _button_note(cls, button: int) -> int:
        if button <= KNOB_COUNT:
            return TOP_BUTTON_NOTES[button - 1]
        return BOTTOM_BUTTON_NOTES[button - KNOB_COUNT - 1]


class XTouchMiniMessageRouter:
    """Parses X-Touch Mini MIDI input and dispatches to a listener."""

    _master_fader_channel = 8

    def __init__(self, listener: XTouchMiniListener, debug: Callable[[str], None] | None = None):
        self._listener = listener
        self._debug = debug

    def handle(self, message: mido.Message) -> None:
        if (
            message.type == "control_change"
            and message.channel == MACKIE_CHANNEL
            and MackieCC.ENCODER_1 <= message.control < MackieCC.ENCODER_1 + KNOB_COUNT
        ):
            knob = message.control - MackieCC.ENCODER_1 + 1
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

        if note in NOTE_TO_LAYER:
            layer = NOTE_TO_LAYER[note]
            self._log(f"layer={layer.value} down={down}")
            self._listener.on_layer(layer, down)
            return

        knob = _note_to_knob_press(note)
        if knob is not None:
            self._log(f"knob_press={knob} down={down}")
            self._listener.on_knob_press(knob, down)
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
    return value if value < RELATIVE_ENCODER_REVERSE_BASE else -(value - RELATIVE_ENCODER_REVERSE_BASE)


def _pitchwheel_to_fader(pitch: int) -> int:
    return max(MIDI_OFF, min(MIDI_ON, round((pitch - PITCHWHEEL_MIN) * MIDI_ON / PITCHWHEEL_RANGE)))


def _note_to_button(note: int) -> int | None:
    return NOTE_TO_TOP_BUTTON.get(note) or NOTE_TO_BOTTOM_BUTTON.get(note)


def _note_to_knob_press(note: int) -> int | None:
    if MackieNote.KNOB_PRESS_1 <= note < MackieNote.KNOB_PRESS_1 + KNOB_COUNT:
        return note - MackieNote.KNOB_PRESS_1 + 1
    return None


def _note(note: int, on: bool) -> mido.Message:
    return mido.Message("note_on", note=int(note), velocity=MIDI_ON if on else MIDI_OFF)


def _ring_cc(knob: int, value: int) -> mido.Message:
    return mido.Message("control_change", channel=MACKIE_CHANNEL, control=int(MackieCC.RING_1 + knob - 1), value=value)


def _validate_index(name: str, value: int, count: int) -> None:
    if not 1 <= value <= count:
        raise ValueError(f"{name} must be 1..{count}, got {value}")
