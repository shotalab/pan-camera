# SPDX-License-Identifier: AGPL-3.0-only

"""PAN-CAMERA horizontal target tracking controller."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PanController:
    deadband_px: float = 30.0
    gain_us_per_px: float = 0.3
    max_step_us: int = 40

    # Initial conservative operating range.
    min_us: int = 1200
    max_us: int = 1800
    far_gain_us_per_px: float | None = None
    gain_ramp_px: float = 400.0

    def next_pulse(
        self,
        current_us: int,
        cup_x: float | None,
        frame_width: int = 640,
    ) -> int:
        if frame_width <= 0:
            raise ValueError("Invalid frame width")

        current_us = max(
            self.min_us,
            min(self.max_us, current_us),
        )

        # No detection: hold the current command.
        if cup_x is None:
            return current_us

        error_x = cup_x - frame_width / 2

        # Ignore small movements around the center.
        if abs(error_x) <= self.deadband_px:
            return current_us

        # Cup right -> smaller pulse -> camera right.
        if self.far_gain_us_per_px is None:
            delta = round(-error_x * self.gain_us_per_px)
        else:
            distance = abs(error_x) - self.deadband_px
            blend = min(1.0, distance / self.gain_ramp_px)
            gain = self.gain_us_per_px + blend * (self.far_gain_us_per_px - self.gain_us_per_px)
            # Avoid an extra dead zone caused by rounding sub-microsecond corrections.
            correction = max(1, round(distance * gain))
            delta = -correction if error_x > 0 else correction

        delta = max(
            -self.max_step_us,
            min(self.max_step_us, delta),
        )

        return max(
            self.min_us,
            min(self.max_us, current_us + delta),
        )
