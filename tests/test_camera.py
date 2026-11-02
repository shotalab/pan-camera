# SPDX-License-Identifier: AGPL-3.0-only

import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from pan_camera.camera import USBCamera169


class TestUSBCamera(unittest.TestCase):
    @patch("pan_camera.camera.cv2.VideoCapture")
    def test_configured_device_path_is_used(self, capture):
        frame = Mock()
        frame.shape = (720, 1280, 3)
        capture.return_value.read.return_value = (True, frame)
        with USBCamera169(device="/dev/v4l/by-id/camera-video-index0"):
            pass
        capture.assert_called_once_with("/dev/v4l/by-id/camera-video-index0", cv2.CAP_V4L2)

    @patch("pan_camera.camera.cv2.VideoCapture")
    def test_open_failure_releases_capture(self, capture):
        capture.return_value.isOpened.return_value = False
        with self.assertRaisesRegex(RuntimeError, "Camera open failed"):
            with USBCamera169():
                pass
        capture.return_value.release.assert_called_once()

    @patch("pan_camera.camera.cv2.VideoCapture")
    def test_capture_and_release(self, capture):
        cap = capture.return_value
        cap.isOpened.return_value = True
        frame = unittest.mock.Mock()
        frame.shape = (720, 1280, 3)
        cap.read.return_value = (True, frame)
        with USBCamera169() as camera:
            self.assertIs(camera.read(), frame)
        cap.release.assert_called_once()

    @patch("pan_camera.camera.cv2.VideoCapture")
    def test_wrong_resolution_releases_camera(self, capture):
        cap = capture.return_value
        cap.isOpened.return_value = True
        frame = unittest.mock.Mock()
        frame.shape = (480, 640, 3)
        cap.read.return_value = (True, frame)
        with self.assertRaises(RuntimeError):
            with USBCamera169():
                pass
        cap.release.assert_called_once()


class TestLatestFrameCamera(unittest.TestCase):
    def test_latest_frame_and_shutdown(self):
        from threading import Event
        from unittest.mock import Mock
        from pan_camera.camera import LatestFrameCamera

        waiting = Event()
        release = Event()
        frames = iter([object(), object()])
        latest = None

        def capture():
            nonlocal latest
            try:
                latest = next(frames)
                return latest
            except StopIteration:
                waiting.set()
                release.wait(2)
                return latest

        source = Mock()
        source.read.side_effect = capture
        camera = LatestFrameCamera(source)
        camera.__enter__()
        try:
            self.assertTrue(waiting.wait(1))
            self.assertIs(camera.read(), latest)
        finally:
            camera._stop.set()
            release.set()
            camera.__exit__(None, None, None)
        self.assertFalse(camera._thread.is_alive())

    def test_capture_failure_propagates(self):
        from unittest.mock import Mock
        from pan_camera.camera import LatestFrameCamera

        source = Mock()
        source.read.side_effect = RuntimeError("disconnected")
        with LatestFrameCamera(source) as camera:
            with self.assertRaisesRegex(RuntimeError, "Camera capture failed"):
                camera.read()


class TestOriginalCapture(unittest.TestCase):
    @patch('pan_camera.camera.cv2.VideoCapture')
    def test_original_jpeg_bytes_are_preserved(self, capture):
        _, data = cv2.imencode('.jpg', np.zeros((720, 1280, 3), np.uint8))
        capture.return_value.read.return_value = (True, data.reshape(1, -1))
        callback = Mock()
        with USBCamera169(raw_callback=callback) as camera:
            frame = camera.read()
        self.assertEqual(frame.shape, (720, 1280, 3))
        self.assertEqual(callback.call_args.args[0], data.tobytes())
        capture.return_value.release.assert_called_once()

    @patch('pan_camera.camera.cv2.VideoCapture')
    def test_backend_failure_is_explicit_and_releases_camera(self, capture):
        capture.return_value.set.side_effect = lambda prop, value: prop != cv2.CAP_PROP_CONVERT_RGB
        with self.assertRaisesRegex(RuntimeError, 'raw_enabled=false'):
            with USBCamera169(raw_callback=Mock()):
                pass
        capture.return_value.release.assert_called_once()

    @patch('pan_camera.camera.cv2.VideoCapture')
    def test_non_jpeg_raw_capture_is_rejected(self, capture):
        capture.return_value.read.return_value = (True, np.zeros((720, 1280, 3), np.uint8))
        callback = Mock()
        with self.assertRaisesRegex(RuntimeError, 'original MJPEG'):
            with USBCamera169(raw_callback=callback):
                pass
        callback.assert_not_called()
        capture.return_value.release.assert_called_once()


