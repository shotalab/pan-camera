# SPDX-License-Identifier: AGPL-3.0-only

"""Record clean camera video and microphone audio using a bounded FFmpeg worker."""

from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, Queue
import shutil
import signal
import subprocess
import tempfile
import os
from threading import Lock, Thread
import tomllib
import time

from .paths import ROOT
from . import mjpeg_stream

MAX_QUEUE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class RecordingConfig:
    raw_enabled: bool = True
    display_enabled: bool = True
    width: int = 1280
    height: int = 720
    camera_fps: int = 30
    camera_device: int | str = 0
    audio_device: str = "plughw:CARD=Camera,DEV=0"
    audio_rate: int = 48000
    audio_channels: int = 1
    video_codec: str = "h264"
    video_crf: int = 26
    encoding_threads: int = 2

    @property
    def output_suffix(self):
        return ".mp4" if self.video_codec == "h264" else ".mkv"

    @classmethod
    def load(cls):
        with (ROOT / "config/recording.toml").open("rb") as f:
            config = cls(**tomllib.load(f)["recording"])
        device_valid = (
            type(config.camera_device) is int and config.camera_device >= 0
        ) or (
            isinstance(config.camera_device, str) and config.camera_device.startswith("/dev/")
        )
        if (type(config.raw_enabled) is not bool
                or type(config.display_enabled) is not bool
                or not device_valid
                or (config.width, config.height) not in ((1280, 720), (1920, 1080))
                or not 1 <= config.camera_fps <= 30
                or config.audio_channels not in (1, 2)
                or config.audio_rate not in (16000, 22050, 44100, 48000)
                or config.video_codec not in ("h264", "copy")
                or not 18 <= config.video_crf <= 35
                or not 1 <= config.encoding_threads <= 4
                or not config.audio_device):
            raise ValueError("Invalid recording configuration")
        return config


class RawAVRecorder:
    """A bounded writer queue prevents disk/audio stalls from blocking capture."""

    def __init__(self, config):
        self.config = config
        self._lock = Lock()
        self._queue = None
        self._process = None
        self._thread = None
        self._log = None
        self._error = None
        self._queued_bytes = 0
        self.path = None

    def _audio_input(self):
        return ["-thread_queue_size", "64", "-use_wallclock_as_timestamps", "1",
                "-analyzeduration", "1", "-probesize", "32",
                "-f", "alsa", "-sample_rate", str(self.config.audio_rate),
                "-channels", str(self.config.audio_channels), "-i", self.config.audio_device]

    def _command(self, path):
        if self.config.video_codec == "h264":
            output = [
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                "-crf", str(self.config.video_crf), "-threads", str(self.config.encoding_threads),
                "-g", str(self.config.camera_fps * 2),
                "-pix_fmt", "yuv420p", "-fps_mode", "vfr", "-enc_time_base:v", "1:1000",
                "-c:a", "aac", "-b:a", "96k", "-af", "aresample=async=1",
                "-movflags", "+faststart", "-f", "mp4",
            ]
        else:
            output = ["-c:v", "copy", "-c:a", "pcm_s16le", "-f", "matroska"]
        return ["ffmpeg", "-hide_banner", "-loglevel", "info", "-nostats", "-nostdin", "-y",
                "-copyts", "-itsoffset", f"{-self._wall_start:.6f}", *self._audio_input(),
                "-thread_queue_size", "8",
                "-f", "matroska",
                "-probesize", "32", "-analyzeduration", "1", "-fpsprobesize", "0",
                "-threads", "1", "-i", "pipe:0",
                "-map", "1:v:0", "-map", "0:a:0",
                "-shortest", "-avoid_negative_ts", "make_zero", *output, str(path)]

    def start(self, path):
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("Install ffmpeg for original video/audio recording")
        self.path = Path(path)
        self._error = None
        self._started = time.monotonic()
        self._wall_start = time.time()
        self._last_timestamp = -1
        self._log = tempfile.TemporaryFile()
        try:
            self._process = subprocess.Popen(
                self._command(path), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=self._log, bufsize=0, start_new_session=True,
            )
            # ALSA/device startup may temporarily delay stdin consumption.
            queue = Queue(maxsize=max(8, self.config.camera_fps * 2))
            with self._lock:
                self._queue = queue
                self._queued_bytes = 0
            thread = Thread(target=self._write_packets, args=(queue, self._process),
                            name="original-recording", daemon=True)
            thread.start()
            self._thread = thread
        except BaseException:
            self.stop()
            raise

    def submit(self, jpeg):
        # Called on the capture thread; never wait or raise on that thread.
        with self._lock:
            if self._queue is None or self._error is not None:
                return
            if self._queued_bytes + len(jpeg) > MAX_QUEUE_BYTES:
                self._error = "Original recording queue memory limit reached (32 MiB)"
                return
            try:
                timestamp = max(self._last_timestamp + 1, int((time.monotonic() - self._started) * 1000))
                self._queue.put_nowait((timestamp, jpeg))
                self._queued_bytes += len(jpeg)
                self._last_timestamp = timestamp
            except Full:
                self._error = (
                    f"Original recording queue overflow ({self._queue.maxsize} frames, "
                    f"{self._queued_bytes / 1024**2:.1f} MiB); writer is not keeping up"
                )

    def _write_packets(self, queue, process):
        def write(data):
            data = memoryview(data)
            while data:
                written = process.stdin.write(data)
                if not written:
                    raise BrokenPipeError("FFmpeg input closed")
                data = data[written:]
        try:
            write(mjpeg_stream.header(self.config.width, self.config.height, self.config.camera_fps))
            while True:
                packet = queue.get()
                if packet is None:
                    break
                timestamp, jpeg = packet
                with self._lock:
                    self._queued_bytes -= len(jpeg)
                write(mjpeg_stream.frame(jpeg, timestamp))
        except (OSError, ValueError) as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    def _log_tail(self):
        if self._log is None:
            return ""
        size = os.fstat(self._log.fileno()).st_size
        return os.pread(self._log.fileno(), min(2000, size), max(0, size - 2000)).decode(errors="replace").strip()

    def check(self):
        with self._lock:
            error = self._error
        if self._process is not None and self._process.poll() is not None:
            error = f"FFmpeg exited with code {self._process.returncode}"
        if error:
            raise RuntimeError(f"{error}: {self._log_tail()}")

    def stop(self):
        process, thread = self._process, self._thread
        with self._lock:
            queue, self._queue = self._queue, None
        if queue is not None:
            # Stop promptly: discard pending packets if necessary, retaining a bounded tail.
            while True:
                try:
                    queue.put_nowait(None)
                    break
                except Full:
                    try:
                        packet = queue.get_nowait()
                        if packet is not None:
                            with self._lock:
                                self._queued_bytes -= len(packet[1])
                    except Empty:
                        pass
        try:
            if thread is not None:
                thread.join(timeout=2)
            elif process is not None and process.stdin is not None:
                process.stdin.close()
            if process is not None:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                        raise RuntimeError("FFmpeg had to be killed; original recording may be incomplete")
                if thread is not None:
                    thread.join(timeout=1)
                    if thread.is_alive():
                        raise RuntimeError("Original recording writer did not stop")
                if process.returncode not in (0, 255):
                    raise RuntimeError(f"Original recording failed: {self._log_tail()}")
        finally:
            self._process = None
            self._thread = None
            if self._log is not None:
                self._log.close()
                self._log = None
