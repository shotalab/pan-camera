# SPDX-License-Identifier: AGPL-3.0-only

import time
import unittest
from unittest.mock import patch

from pan_camera.actuator import ServoConfig
from pan_camera.paths import ROOT
from pan_camera.smooth_servo import SmoothPanServo


class TestSmoothServo(unittest.TestCase):
    @patch("pan_camera.smooth_servo.PanServo")
    def test_move_hold_and_close(self, hardware_class):
        config = ServoConfig.load(ROOT / "config/servo.toml")
        hardware_class.return_value.current_us = 1500
        servo = SmoothPanServo(config, 1500, min_us=config.right_us, max_us=config.left_us)
        with servo:
            servo.set_target(1550)
            deadline = time.monotonic() + 1
            while servo.current_us == 1500 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertGreater(servo.current_us, 1500)
            servo.hold()
            held = servo.current_us
            time.sleep(0.08)
            self.assertEqual(servo.current_us, held)
        hardware_class.return_value.close.assert_called_once()
        self.assertFalse(servo._thread.is_alive())


class TestDistanceProfile(unittest.TestCase):
    def make_servo(self):
        config = ServoConfig.load(ROOT / "config/servo.toml")
        servo = SmoothPanServo(config, 1500, min_us=800, max_us=2200)
        servo._hardware = unittest.mock.Mock()
        return servo

    def test_accelerates_cruises_and_slows_without_crossing_target(self):
        servo = self.make_servo()
        servo.set_target(2100)
        positions, speeds = [], []
        for _ in range(400):
            servo._advance(0.02)
            positions.append(servo._position)
            speeds.append(servo._velocity)
        self.assertTrue(all(a <= b <= 2100 for a, b in zip([1500] + positions, positions)))
        self.assertEqual(servo.current_us, 2100)
        self.assertLessEqual(max(speeds), servo._max_speed)
        self.assertGreater(speeds[4], speeds[0])
        self.assertEqual(speeds[-1], 0)
        self.assertTrue(all(abs(b-a) <= servo._max_speed * .02 + 1e-6
                            for a,b in zip([1500] + positions, positions)))

    def test_near_target_and_reversal_stay_in_range(self):
        servo = self.make_servo()
        servo.set_target(1505)
        for _ in range(100):
            servo._advance(.02)
            self.assertLessEqual(servo._position, 1505)
        self.assertEqual(servo.current_us, 1505)
        servo.set_target(2200)
        for _ in range(20):
            servo._advance(.02)
        servo.set_target(800)
        for _ in range(400):
            servo._advance(.02)
            self.assertTrue(800 <= servo._position <= 2200)
        self.assertEqual(servo.current_us, 800)
        servo.hold()
        held = servo.current_us
        for _ in range(20):
            servo._advance(.02)
        self.assertEqual(servo.current_us, held)
        self.assertEqual(servo._velocity, 0)
