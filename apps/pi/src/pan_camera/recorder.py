# SPDX-License-Identifier: AGPL-3.0-only

"""Local video recording."""

import shutil
import time
from datetime import datetime

import cv2

from .paths import ROOT
from .display import DisplayRecorder
from .raw_recorder import RawAVRecorder

RECORD_DIR = ROOT / "outputs/recordings"


class Recorder:
    def __init__(self, fps, raw_config=None):
        self.fps = fps
        self.writer = None
        self.display = None
        self.display_enabled = raw_config.display_enabled if raw_config is not None else True
        self.started = 0.0
        self.path = None
        self.raw = RawAVRecorder(raw_config) if raw_config and raw_config.raw_enabled else None

    @property
    def active(self):
        return self.writer is not None

    def seconds(self):
        return int(time.monotonic() - self.started) if self.active else 0

    def start(self):
        RECORD_DIR.mkdir(parents=True, exist_ok=True)

        if shutil.disk_usage(RECORD_DIR).free < 100 * 1024 * 1024:
            raise RuntimeError("Not enough recording disk space")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = RECORD_DIR / f"pancamera_{stamp}_annotated.avi"

        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"MJPG"),
            self.fps,
            (640, 360),
        )
        if not writer.isOpened():
            writer.release()
            raise RuntimeError("Recording file could not be opened")

        started = time.monotonic()
        display = None
        display_path = RECORD_DIR / f"pancamera_{stamp}_display.avi"
        try:
            if self.display_enabled:
                display = DisplayRecorder(display_path, started)
            if self.raw is not None:
                suffix = self.raw.config.output_suffix
                self.raw.start(RECORD_DIR / f"pancamera_{stamp}_clean{suffix}")
        except BaseException:
            try:
                writer.release()
            finally:
                if display is not None:
                    display.stop()
            raise

        self.writer = writer
        self.path = path
        self.started = started
        self.display = display
        print(f"REC START: {path}", flush=True)
        if display is not None:
            print(f"REC DISPLAY: {display_path}", flush=True)
        if self.raw is not None:
            print(f"REC CLEAN + AUDIO: {self.raw.path}", flush=True)

    def write_raw(self, jpeg):
        if self.raw is not None:
            self.raw.submit(jpeg)

    def write(self, image):
        if self.active:
            if self.raw is not None:
                self.raw.check()
            self.writer.write(image)

    def write_display(self, preview, **status):
        if self.active and self.display is not None:
            self.display.write(preview, **status)

    def stop(self):
        display, self.display = self.display, None
        writer, self.writer = self.writer, None
        try:
            if writer is not None:
                writer.release()
                print(f"REC CLOSED: {self.path}", flush=True)
        finally:
            try:
                if display is not None:
                    display.stop()
            finally:
                if self.raw is not None:
                    self.raw.stop()


