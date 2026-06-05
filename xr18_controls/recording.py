from __future__ import annotations

import queue
import random
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SAMPLE_RATE = 48_000
DEFAULT_CHANNELS = 18
DEFAULT_BLOCKSIZE = 1024
DEFAULT_QUEUE_BLOCKS = 128
RECORDING_FORMAT = "RF64"
RECORDING_SUBTYPE = "PCM_24"
RECORDING_EXTENSION = ".wav"
STOP_WRITER = object()

DebugLogger = Callable[[str], None]

RECORDING_WORDS = (
    "amber",
    "apex",
    "atlas",
    "aurora",
    "blue",
    "bright",
    "cedar",
    "clear",
    "cloud",
    "coral",
    "delta",
    "ember",
    "field",
    "flare",
    "forest",
    "glow",
    "gold",
    "harbor",
    "horizon",
    "iron",
    "jade",
    "lake",
    "lunar",
    "maple",
    "meadow",
    "metro",
    "midnight",
    "north",
    "nova",
    "ocean",
    "orbit",
    "pine",
    "plain",
    "pulse",
    "river",
    "silver",
    "signal",
    "sky",
    "solar",
    "stone",
    "summit",
    "sunset",
    "tempo",
    "trail",
    "velvet",
    "violet",
    "wave",
    "winter",
    # Hacker dictionary
    "admin",
    "backdoor",
    "binary",
    "blockchain",
    "buffer",
    "bytecode",
    "cache",
    "cipher",
    "cli",
    "cluster",
    "codec",
    "compile",
    "crypto",
    "daemon",
    "debug",
    "decrypt",
    "deploy",
    "devops",
    "exploit",
    "firewall",
    "firmware",
    "flux",
    "gateway",
    "git",
    "gitlab",
    "gitlab",
    "grep",
    "hash",
    "hexadecimal",
    "idle",
    "input",
    "kernel",
    "keylogger",
    "lambda",
    "libexec",
    "linux",
    "localhost",
    "malware",
    "matrix",
    "memory",
    "metasploit",
    "minify",
    "module",
    "mongodb",
    "mutex",
    "netcat",
    "nginx",
    "nmap",
    "node",
    "null",
    "obfuscate",
    "opcode",
    "packet",
    "payload",
    "pbx",
    "php",
    "postgres",
    "proxy",
    "putty",
    "recursion",
    "redis",
    "regex",
    "registry",
    "replicat",
    "router",
    "runtime",
    "sandbox",
    "script",
    "sdk",
    "segment",
    "server",
    "shell",
    "shellcode",
    "socket",
    "source",
    "ssh",
    "ssl",
    "stack",
    "stdin",
    "stdout",
    "subnet",
    "sudo",
    "swamp",
    "syntax",
    "syslog",
    "tcp",
    "terminal",
    "thread",
    "token",
    "trace",
    "tunnel",
    "udp",
    "unix",
    "vector",
    "vendor",
    "verbose",
    "virus",
    "volatile",
    "wasm",
    "webhook",
    "wifi",
    "xss",
    "yaml",
    "zombie",
    # Music memes
    "bass",
    "beat",
    "bop",
    "breakcore",
    "drop",
    "dubstep",
    "drum",
    "edm",
    "epic",
    "euphoria",
    "festival",
    "funk",
    "groove",
    "heavy",
    "lfo",
    "lo-fi",
    "meme",
    "metalcore",
    "midtempo",
    "mixtape",
    "remix",
    "reverb",
    "sick",
    "slap",
    "sound",
    "synth",
    "vibe",
    "vibraphone",
    "vinyl",
    "waveform",
    # Random unique words
    "abyss",
    "absurd",
    "acid",
    "acrid",
    "acrobat",
    "acute",
    "adage",
    "adapt",
    "addax",
    "adder",
    "addict",
    "addle",
    "adeem",
    "adept",
    "adieu",
    "adipose",
    "adjoin",
    "adjourn",
    "adjudge",
    "adjunct",
    "adjure",
    "adjust",
    "adjutant",
    "admire",
    "admit",
    "admix",
    "admonish",
    "adobe",
    "adonize",
    "adopt",
    "adore",
    "adorn",
    "adult",
    "adust",
    "advent",
    "adverb",
    "adverse",
    "advert",
    "advice",
    "advise",
    "advocate",
    "adze",
    "aegis",
    "aeon",
    "aerate",
    "aerial",
    "aerie",
    "aery",
    "afar",
    "affable",
    "affair",
    "affect",
    "affiche",
    "affied",
    "affies",
    "affinal",
    "affined",
    "affinal",
    "affinity",
    "affirm",
    "affix",
    "afflatus",
    "afflict",
    "afflux",
    "afford",
    "afforest",
    "affray",
    "affront",
    "affuse",
    "afghan",
    "afire",
    "aflame",
    "afloat",
    "aflutter",
    "afoot",
    "afore",
    "aforementioned",
    "afoul",
    "afraid",
    "afresh",
    "afrit",
    "aft",
    "after",
    "afters",
    "afterday",
    "afterglow",
    "aftermath",
)


@dataclass(frozen=True)
class RecordingConfig:
    directory: Path
    audio_device: str
    channels: int = DEFAULT_CHANNELS
    sample_rate: int = DEFAULT_SAMPLE_RATE
    blocksize: int = DEFAULT_BLOCKSIZE
    queue_blocks: int = DEFAULT_QUEUE_BLOCKS


class SystemNotifier:
    def __init__(self, debug: DebugLogger | None = None):
        self._debug = debug

    def notify(self, title: str, message: str) -> None:
        if sys.platform == "win32" and self._notify_windows(title, message):
            return

        self._log(f"{title}: {message}")

    def _notify_windows(self, title: str, message: str) -> bool:
        try:
            from winotify import Notification
        except Exception as error:
            self._log(f"Windows notification unavailable: {error}")
            return False

        try:
            Notification(app_id="XR18 Controls", title=title, msg=message).show()
        except Exception as error:
            self._log(f"Windows notification failed: {error}")
            return False
        return True

    def _log(self, message: str) -> None:
        if self._debug is not None:
            self._debug(message)


class RecordingService:
    def __init__(
        self,
        config: RecordingConfig,
        notifier: SystemNotifier,
        debug: DebugLogger | None = None,
    ):
        self._recorder = MultitrackRecorder(config, debug=debug)
        self._notifier = notifier

    @property
    def is_recording(self) -> bool:
        return self._recorder.is_recording

    @property
    def current_file(self) -> Path | None:
        return self._recorder.current_file

    def toggle(self, active_channels: Sequence[int] | None = None) -> bool:
        if self.is_recording:
            self.stop()
            return False

        path = self._recorder.start(active_channels)
        channel_text = _format_channel_list(self._recorder.recorded_channels)
        self._notifier.notify("XR18 recording started", f"{path.name} ({channel_text})")
        return True

    def stop(self) -> None:
        self._recorder.stop()

    def close(self) -> None:
        self.stop()


class MultitrackRecorder:
    def __init__(self, config: RecordingConfig, debug: DebugLogger | None = None):
        if config.channels < 1:
            raise ValueError("recording channels must be at least 1")
        if config.sample_rate < 1:
            raise ValueError("recording sample rate must be positive")
        if config.blocksize < 1:
            raise ValueError("recording blocksize must be positive")

        self._config = config
        self._debug = debug
        self._lock = threading.Lock()
        self._stream: Any | None = None
        self._sound_file: Any | None = None
        self._writer_thread: threading.Thread | None = None
        self._queue: queue.Queue[Any] | None = None
        self._current_file: Path | None = None
        self._recorded_channels: tuple[int, ...] = ()
        self._writer_error: BaseException | None = None
        self._callback_error: BaseException | None = None

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._stream is not None

    @property
    def current_file(self) -> Path | None:
        with self._lock:
            return self._current_file

    @property
    def recorded_channels(self) -> tuple[int, ...]:
        with self._lock:
            return self._recorded_channels

    def start(self, active_channels: Sequence[int] | None = None) -> Path:
        with self._lock:
            if self._stream is not None:
                assert self._current_file is not None
                return self._current_file

            recorded_channels = _normalize_recorded_channels(active_channels, self._config.channels)
            output_channels = len(recorded_channels)
            channel_indices = tuple(channel - 1 for channel in recorded_channels)
            sd, sf = _load_audio_modules()
            self._config.directory.mkdir(parents=True, exist_ok=True)
            path = self._next_recording_path()
            device_index = _pick_input_device(sd, self._config.audio_device, self._config.channels)
            audio_queue: queue.Queue[Any] = queue.Queue(maxsize=self._config.queue_blocks)

            sound_file = sf.SoundFile(
                path,
                mode="w",
                samplerate=self._config.sample_rate,
                channels=output_channels,
                format=RECORDING_FORMAT,
                subtype=RECORDING_SUBTYPE,
            )

            self._queue = audio_queue
            self._sound_file = sound_file
            self._current_file = path
            self._recorded_channels = recorded_channels
            self._writer_error = None
            self._callback_error = None

            writer_thread = threading.Thread(
                target=self._write_audio,
                args=(audio_queue, sound_file, channel_indices),
                name="recording-writer",
                daemon=True,
            )
            writer_thread.start()
            self._writer_thread = writer_thread

            try:
                stream = sd.InputStream(
                    samplerate=self._config.sample_rate,
                    device=device_index,
                    channels=self._config.channels,
                    blocksize=self._config.blocksize,
                    dtype="int32",
                    callback=self._audio_callback,
                )
                self._stream = stream
                stream.start()
            except Exception:
                self._stop_locked()
                raise

            self._log(f"Recording started: {path} ({_format_channel_list(recorded_channels)})")
            return path

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

        audio_queue = self._queue
        self._queue = None
        if audio_queue is not None:
            self._request_writer_stop(audio_queue)

        writer_thread = self._writer_thread
        self._writer_thread = None
        if writer_thread is not None:
            writer_thread.join()

        sound_file = self._sound_file
        self._sound_file = None
        if sound_file is not None:
            sound_file.close()

        if self._current_file is not None:
            self._log(f"Recording stopped: {self._current_file}")
        self._current_file = None
        self._recorded_channels = ()

        if self._writer_error is not None:
            error = self._writer_error
            self._writer_error = None
            raise RuntimeError(f"recording writer failed: {error}") from error
        if self._callback_error is not None:
            error = self._callback_error
            self._callback_error = None
            raise RuntimeError(f"recording input failed: {error}") from error

    def _audio_callback(self, indata, frames: int, time_info, status) -> None:
        if status:
            self._log(f"Recording input status: {status}")

        audio_queue = self._queue
        if audio_queue is None:
            return

        try:
            audio_queue.put_nowait(indata.copy())
        except queue.Full as error:
            self._callback_error = error
            raise

    def _write_audio(
        self,
        audio_queue: queue.Queue[Any],
        sound_file,
        channel_indices: tuple[int, ...],
    ) -> None:
        while True:
            block = audio_queue.get()
            if block is STOP_WRITER:
                return

            try:
                sound_file.write(block[:, channel_indices])
            except BaseException as error:
                self._writer_error = error
                return

    @staticmethod
    def _request_writer_stop(audio_queue: queue.Queue[Any]) -> None:
        try:
            audio_queue.put_nowait(STOP_WRITER)
            return
        except queue.Full:
            pass

        try:
            audio_queue.get_nowait()
        except queue.Empty:
            pass
        audio_queue.put_nowait(STOP_WRITER)

    def _next_recording_path(self) -> Path:
        for _ in range(100):
            suffix = "-".join(_random_words())
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            path = self._config.directory / f"{timestamp}_{suffix}{RECORDING_EXTENSION}"
            if not path.exists():
                return path
        raise RuntimeError("could not create a unique recording filename")

    def _log(self, message: str) -> None:
        if self._debug is not None:
            self._debug(message)


def list_audio_input_devices() -> list[str]:
    sd, _ = _load_audio_modules()
    devices = sd.query_devices()
    lines = []
    for index, device in enumerate(devices):
        input_channels = int(device.get("max_input_channels", 0))
        if input_channels > 0:
            lines.append(f"{index}: {device['name']} ({input_channels} inputs)")
    return lines


def _pick_input_device(sd, requested_name: str, channels: int) -> int | None:
    devices = sd.query_devices()
    candidates = [
        (index, device)
        for index, device in enumerate(devices)
        if int(device.get("max_input_channels", 0)) >= channels
    ]

    exact_matches = [
        index for index, device in candidates if str(device["name"]).lower() == requested_name.lower()
    ]
    if exact_matches:
        return exact_matches[0]

    requested = requested_name.lower()
    matches = [index for index, device in candidates if requested in str(device["name"]).lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        available = ", ".join(
            f"{index}: {device['name']} ({device['max_input_channels']} inputs)"
            for index, device in candidates
        )
        raise RuntimeError(
            f"No audio input device matching {requested_name!r} with at least {channels} channels. "
            f"Available: {available or 'none'}"
        )

    names = ", ".join(str(devices[index]["name"]) for index in matches)
    raise RuntimeError(f"Multiple audio input devices match {requested_name!r}: {names}")


def _random_words() -> tuple[str, ...]:
    rng = random.SystemRandom()
    count = rng.randint(2, 3)
    return tuple(rng.sample(RECORDING_WORDS, count))


def _normalize_recorded_channels(
    active_channels: Sequence[int] | None,
    capture_channels: int,
) -> tuple[int, ...]:
    if active_channels is None:
        return tuple(range(1, capture_channels + 1))

    recorded_channels: list[int] = []
    seen: set[int] = set()
    for channel in active_channels:
        if not 1 <= channel <= capture_channels:
            continue
        if channel in seen:
            continue
        recorded_channels.append(channel)
        seen.add(channel)

    if not recorded_channels:
        raise RuntimeError("No unmuted channels selected for recording")
    return tuple(recorded_channels)


def _format_channel_list(channels: Sequence[int]) -> str:
    return "channels " + ", ".join(str(channel) for channel in channels)


def _load_audio_modules():
    try:
        import sounddevice as sd
        import soundfile as sf
    except Exception as error:
        raise RuntimeError(
            "Recording requires sounddevice and soundfile. Install project dependencies with uv sync."
        ) from error
    return sd, sf
