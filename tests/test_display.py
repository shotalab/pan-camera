# SPDX-License-Identifier: AGPL-3.0-only
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cv2
import numpy as np

from pan_camera.display import DisplayRecorder, draw_display


STATUS = dict(state=1, selected_id=2, target_name='cup', confidence=93,
              object_count=2, error=-10, pwm=1500, fps=12.9, seconds=3)


class DisplayTests(unittest.TestCase):
    def test_preview_is_preserved_and_hud_changes_with_state(self):
        preview = np.full((180, 320, 3), (60, 100, 140), np.uint8)
        track = draw_display(preview, **STATUS)
        lost = draw_display(preview, **(STATUS | {'state': 2, 'seconds': 4}))
        free = draw_display(preview, **(STATUS | {'state': 0, 'selected_id': None}))
        self.assertEqual(track.shape, (240, 320, 3))
        np.testing.assert_array_equal(track[20:200], preview)
        self.assertFalse(np.array_equal(track, lost))
        self.assertFalse(np.array_equal(track, free))

    @patch('pan_camera.display.time.monotonic')
    @patch('pan_camera.display.cv2.VideoWriter')
    def test_elapsed_time_holds_previous_frame_across_capture_gap(self, writer, clock):
        clock.return_value = 10
        recorder = DisplayRecorder('unused.avi', started=10)
        preview = np.zeros((180, 320, 3), np.uint8)
        recorder.write(preview, **STATUS)  # slot 0
        first = writer.return_value.write.call_args.args[0]
        clock.return_value = 10.1
        recorder.write(preview, **STATUS)  # no extra frame in same slot
        self.assertEqual(writer.return_value.write.call_count, 1)
        clock.return_value = 10.8
        recorder.write(preview, **(STATUS | {'state': 2}))  # slots 1,2 held; 3 new
        self.assertEqual(writer.return_value.write.call_count, 4)
        self.assertIs(writer.return_value.write.call_args_list[1].args[0], first)
        self.assertIs(writer.return_value.write.call_args_list[2].args[0], first)
        clock.return_value = 11.05
        recorder.stop()  # slot 4 held
        self.assertEqual(writer.return_value.write.call_count, 5)
        writer.return_value.release.assert_called_once()

    def test_display_output_decodes_at_expected_size_and_rate(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'display.avi'
            with patch('pan_camera.display.time.monotonic', return_value=10):
                recorder = DisplayRecorder(path, started=10)
                recorder.write(np.zeros((180, 320, 3), np.uint8), **STATUS)
                recorder.stop()
            capture = cv2.VideoCapture(str(path))
            try:
                ok, image = capture.read()
                self.assertTrue(ok)
                self.assertEqual(image.shape, (240, 320, 3))
                self.assertEqual(capture.get(cv2.CAP_PROP_FPS), 4)
            finally:
                capture.release()
