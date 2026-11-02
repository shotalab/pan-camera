# SPDX-License-Identifier: AGPL-3.0-only

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pan_camera.actuator import ServoConfig, PanServo


ROOT = Path(__file__).resolve().parents[1]


class TestServoConfig(unittest.TestCase):
    def setUp(self):
        self.config = ServoConfig.load(
            ROOT / "config/servo.toml"
        )

        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.pwm = Path(temp.name)

        for name, value in {
            "period": "20000000",
            "duty_cycle": "0",
            "enable": "0",
            "polarity": "normal",
        }.items():
            (self.pwm / name).write_text(value)

    def test_center_and_cleanup(self):
        with patch("pan_camera.actuator.sleep"):
            with PanServo(
                self.config, pwm_dir=self.pwm
            ) as servo:
                self.assertEqual(
                    (self.pwm / "enable").read_text(), "1"
                )
                self.assertEqual(
                    (self.pwm / "duty_cycle").read_text(),
                    "1500000",
                )

        self.assertEqual(
            (self.pwm / "enable").read_text(), "0"
        )

    def test_smooth_motion(self):
        with patch("pan_camera.actuator.sleep"):
            with PanServo(
                self.config, pwm_dir=self.pwm
            ) as servo:
                with patch.object(
                    servo, "_write", wraps=servo._write
                ) as write:
                    servo.move_to(1200)
                    servo.center()

                pulses = [
                    call.args[0]
                    for call in write.call_args_list
                ]

                self.assertIn(1200, pulses)
                self.assertEqual(pulses[-1], 1500)

                self.assertTrue(all(
                    abs(b - a) <= self.config.step_us
                    for a, b in zip(pulses, pulses[1:])
                ))

    def test_range_protection(self):
        with patch("pan_camera.actuator.sleep"):
            with PanServo(
                self.config, pwm_dir=self.pwm
            ) as servo:
                for pulse in (799, 2201):
                    with self.assertRaises(ValueError):
                        servo.move_to(pulse)

    def test_busy_channel_is_not_modified(self):
        (self.pwm / "enable").write_text("1")

        with self.assertRaises(RuntimeError):
            with PanServo(
                self.config, pwm_dir=self.pwm
            ):
                pass

        self.assertEqual(
            (self.pwm / "enable").read_text(), "1"
        )

    def test_hold_survives_close_and_resumes_without_position_jump(self):
        with patch("pan_camera.actuator.sleep"):
            servo = PanServo(self.config, pwm_dir=self.pwm)
            servo.__enter__()
            servo.set_pulse(1730)
            servo.close(hold_position=True)
            self.assertEqual((self.pwm / "enable").read_text(), "1")
            self.assertEqual((self.pwm / "duty_cycle").read_text(), "1730000")
            resumed = PanServo(self.config, pwm_dir=self.pwm, resume_held=True)
            with patch.object(resumed, "_write", wraps=resumed._write) as write:
                with resumed:
                    self.assertEqual(resumed.current_us, 1730)
                    write.assert_not_called()
            self.assertEqual((self.pwm / "enable").read_text(), "0")

    def test_resume_does_not_take_over_live_owner(self):
        with patch("pan_camera.actuator.sleep"):
            with PanServo(self.config, pwm_dir=self.pwm):
                with self.assertRaisesRegex(RuntimeError, "another process"):
                    with PanServo(self.config, pwm_dir=self.pwm, resume_held=True):
                        pass
                self.assertEqual((self.pwm / "enable").read_text(), "1")

    def test_resume_rejects_unmarked_enabled_channel(self):
        (self.pwm / "enable").write_text("1")
        (self.pwm / "duty_cycle").write_text("1500000")
        with self.assertRaisesRegex(RuntimeError, "already in use"):
            with PanServo(self.config, pwm_dir=self.pwm, resume_held=True):
                pass
        self.assertEqual((self.pwm / "enable").read_text(), "1")


if __name__ == "__main__":
    unittest.main()
