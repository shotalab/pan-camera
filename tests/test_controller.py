# SPDX-License-Identifier: AGPL-3.0-only

import unittest

from pan_camera.actuator import ServoConfig
from pan_camera.controller import PanController
from pan_camera.paths import ROOT


class TestPanController(unittest.TestCase):
    def setUp(self):
        config = ServoConfig.load(ROOT / 'config/servo.toml')
        self.controller = PanController(
            deadband_px=5, gain_us_per_px=.12, far_gain_us_per_px=.28,
            max_step_us=140, min_us=config.right_us, max_us=config.left_us,
        )

    def test_center_band_and_fine_corrections(self):
        for x, expected in ((635, 1500), (645, 1500), (646, 1499),
                            (634, 1501), (665, 1497)):
            with self.subTest(x=x):
                self.assertEqual(self.controller.next_pulse(1500, x, 1280), expected)

    def test_large_errors_respect_step_and_operating_limits(self):
        self.assertEqual(self.controller.next_pulse(1500, 1280, 1280), 1360)
        self.assertEqual(self.controller.next_pulse(1500, 0, 1280), 1640)
        for current, x, expected in (
            (self.controller.min_us, 1280, self.controller.min_us),
            (self.controller.max_us, 0, self.controller.max_us),
        ):
            with self.subTest(current=current):
                self.assertEqual(self.controller.next_pulse(current, x, 1280), expected)

    def test_missing_target_holds_position(self):
        self.assertEqual(self.controller.next_pulse(1500, None, 1280), 1500)
