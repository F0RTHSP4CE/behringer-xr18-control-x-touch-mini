from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import contextmanager
import os
import sys

import mido


DebugLogger = Callable[[str], None]


class ReconnectableMidiIO:
    def __init__(
        self,
        *,
        label: str,
        requested_name: str,
        debug: DebugLogger | None = None,
    ) -> None:
        self._label = label
        self._requested_name = requested_name
        self._debug = debug
        self._input = None
        self._output = None
        self._input_name: str | None = None
        self._output_name: str | None = None
        self._last_status: str | None = None
        self._last_lookup_status: dict[str, str] = {}

    @property
    def connected(self) -> bool:
        return self._input is not None and self._output is not None

    @property
    def input_port(self):
        return self._input

    @property
    def description(self) -> str:
        if self.connected:
            return f"{self._label}: {self._input_name} -> {self._output_name}"
        return f"{self._label}: waiting for {self._requested_name!r}"

    def connect(self) -> bool:
        if self.connected:
            return False

        try:
            with _quiet_backend_stderr():
                input_names = mido.get_input_names()
                output_names = mido.get_output_names()
        except Exception as error:
            self._log_status(f"{self._label} port scan failed: {error}")
            return False

        input_name = self._pick_port_name(input_names, "input")
        output_name = self._pick_port_name(output_names, "output")
        if input_name is None or output_name is None:
            return False

        try:
            with _quiet_backend_stderr():
                input_port = mido.open_input(input_name)
                output_port = mido.open_output(output_name)
        except Exception as error:
            self._close_port(input_port if "input_port" in locals() else None)
            self._close_port(output_port if "output_port" in locals() else None)
            self._log_status(f"{self._label} connect failed: {error}")
            return False

        self._input = input_port
        self._output = output_port
        self._input_name = input_name
        self._output_name = output_name
        self._last_lookup_status.clear()
        self._log_status(f"{self._label} connected: {input_name} -> {output_name}")
        return True

    def send(self, message) -> bool:
        if not self.connected and not self.connect():
            return False
        if self._output is None:
            return False

        try:
            self._output.send(message)
        except Exception as error:
            self.disconnect(f"send failed: {error}")
            return False
        return True

    def check_connection(self) -> None:
        if not self.connected:
            return

        try:
            with _quiet_backend_stderr():
                input_names = mido.get_input_names()
                output_names = mido.get_output_names()
        except Exception as error:
            self.disconnect(f"port scan failed: {error}")
            return

        input_missing = self._input_name not in input_names
        output_missing = self._output_name not in output_names
        if input_missing or output_missing:
            self.disconnect("ports disappeared")

    def disconnect(self, reason: str | None = None) -> None:
        was_connected = self.connected
        self._close_port(self._input)
        self._close_port(self._output)
        self._input = None
        self._output = None
        self._input_name = None
        self._output_name = None

        if reason is not None or was_connected:
            suffix = f" ({reason})" if reason else ""
            self._log_status(f"{self._label} disconnected{suffix}")

    def close(self) -> None:
        self.disconnect()

    def _pick_port_name(self, names: Sequence[str], direction: str) -> str | None:
        if self._requested_name in names:
            return self._requested_name

        requested = self._requested_name.lower()
        matches = [name for name in names if requested in name.lower()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            self._log_lookup_status(
                direction,
                f"{self._label} {direction} port matching {self._requested_name!r} not found"
            )
            return None

        self._log_lookup_status(
            direction,
            f"{self._label} {direction} port {self._requested_name!r} is ambiguous: "
            + ", ".join(matches),
        )
        return None

    def _log_lookup_status(self, direction: str, message: str) -> None:
        if self._last_lookup_status.get(direction) == message:
            return
        self._last_lookup_status[direction] = message
        self._log_status(message)

    def _log_status(self, message: str) -> None:
        if message == self._last_status:
            return
        self._last_status = message
        if self._debug is not None:
            self._debug(message)

    @staticmethod
    def _close_port(port) -> None:
        if port is None:
            return
        try:
            port.close()
        except Exception:
            pass


@contextmanager
def _quiet_backend_stderr():
    if os.environ.get("XR18_MIDI_BACKEND_DEBUG"):
        yield
        return

    try:
        stderr_fd = sys.stderr.fileno()
        saved_fd = os.dup(stderr_fd)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
    except Exception:
        yield
        return

    try:
        os.dup2(devnull_fd, stderr_fd)
        yield
    finally:
        os.dup2(saved_fd, stderr_fd)
        os.close(saved_fd)
        os.close(devnull_fd)
