# SPDX-License-Identifier: AGPL-3.0-only

"""1280x720 MJPEG camera for PAN-CAMERA."""

import cv2
import numpy as np
import time
from threading import Condition, Event, Thread


class USBCamera169:
    WIDTH = 1280
    HEIGHT = 720

    def __init__(self, width=1280, height=720, fps=30, raw_callback=None, device=0):
        self.width = width
        self.height = height
        self.fps = fps
        self.raw_callback = raw_callback
        self.device = device

    def __enter__(self):
        self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)

        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError("Camera open failed")

        self.cap.set(
            cv2.CAP_PROP_FOURCC,
            cv2.VideoWriter_fourcc(*"MJPG"),
        )
        try:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
            if self.raw_callback is not None:
                if not self.cap.set(cv2.CAP_PROP_CONVERT_RGB, 0):
                    raise RuntimeError("Camera backend cannot provide MJPEG packets; set raw_enabled=false")
            for _ in range(5):
                self.read()
        except Exception:
            self.cap.release()
            raise

        print(f"Camera: {self.width}x{self.height} MJPEG")
        return self

    def read(self):
        ok, frame = self.cap.read()

        if not ok:
            raise RuntimeError("Camera read failed")

        jpeg = None
        if self.raw_callback is not None:
            jpeg = frame.tobytes()
            if not jpeg.startswith(b"\xff\xd8"):
                raise RuntimeError("Camera did not return original MJPEG; set raw_enabled=false")
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise RuntimeError("Camera JPEG decode failed")

        height, width = frame.shape[:2]

        if (width, height) != (self.width, self.height):
            raise RuntimeError(
                f"Unexpected resolution: {width}x{height}"
            )

        if jpeg is not None:
            self.raw_callback(jpeg)
        return frame

    def __exit__(self, exc_type, exc, tb):
        self.cap.release()


class LatestFrameCamera:
    """Continuously drain capture buffers; keep only the latest frame."""

    def __init__(self, camera):
        self.camera = camera
        self._condition = Condition()
        self._stop = Event()
        self._frame = None
        self._error = None
        self._version = 0
        self._consumed = 0
        self._captured_at = 0.0
        self.frame_age_ms = 0.0

    @property
    def captured_count(self):
        with self._condition:
            return self._version

    def __enter__(self):
        self._thread = Thread(target=self._capture, daemon=True, name="camera-capture")
        self._thread.start()
        return self

    def _capture(self):
        try:
            while not self._stop.is_set():
                frame = self.camera.read()
                with self._condition:
                    self._frame = frame
                    self._captured_at = time.monotonic()
                    self._version += 1
                    self._condition.notify_all()
        except Exception as exc:
            with self._condition:
                self._error = exc
                self._condition.notify_all()

    def read(self):
        with self._condition:
            ready = self._condition.wait_for(
                lambda: self._error is not None or self._version != self._consumed,
                timeout=2.0,
            )
            if self._error is not None:
                raise RuntimeError("Camera capture failed") from self._error
            if not ready:
                raise RuntimeError("Camera frame timeout")
            self._consumed = self._version
            self.frame_age_ms = (time.monotonic() - self._captured_at) * 1000
            return self._frame

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            raise RuntimeError("Camera capture thread did not stop")
