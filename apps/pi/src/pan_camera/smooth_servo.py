# SPDX-License-Identifier: AGPL-3.0-only

"""Smooth, nonblocking pan-servo control using hardware PWM."""

from threading import Event, Lock, Thread
from math import copysign, sqrt
from time import monotonic

from .actuator import PanServo, ServoConfig


class SmoothPanServo:
    """Move toward the latest target in small steps every 20 ms."""

    def __init__(
        self,
        config: ServoConfig,
        initial_us: int,
        min_us: int = 1350,
        max_us: int = 1800,
        resume_held: bool = False,
    ):
        if not (
            config.right_us <= min_us
            <= config.center_us
            <= max_us <= config.left_us
        ):
            raise ValueError("Invalid tracking limits")

        self._hardware = PanServo(
            config, initial_us=initial_us, resume_held=resume_held
        )
        self.min_us = min_us
        self.max_us = max_us

        self._lock = Lock()
        self._stop = Event()
        self._thread = None
        self._error = None

        self._position = float(initial_us)
        self._target = float(initial_us)
        self._written = initial_us
        self._velocity = 0.0
        self._max_speed = config.max_speed_us_per_s
        self._acceleration = config.acceleration_us_per_s2

    def __enter__(self):
        self._hardware.__enter__()
        self._position = float(self._hardware.current_us)
        self._target = self._position
        self._written = int(self._position)

        try:
            self._thread = Thread(
                target=self._run,
                name="pancamera-servo",
                daemon=True,
            )
            self._thread.start()
        except BaseException:
            self._hardware.close()
            raise

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @property
    def current_us(self):
        with self._lock:
            return self._written

    def set_target(self, pulse_us: int):
        """Update target without waiting for movement."""
        with self._lock:
            self._check_error()
            self._target = float(
                max(self.min_us, min(self.max_us, pulse_us))
            )

    def hold(self):
        """Stop advancing when the selected target is lost."""
        with self._lock:
            self._check_error()
            self._position = float(self._written)
            self._target = float(self._written)
            self._velocity = 0.0

    def _check_error(self):
        if self._error is not None:
            raise RuntimeError(
                "Servo worker failed"
            ) from self._error

        if self._stop.is_set():
            raise RuntimeError("Servo worker is stopped")

    def _advance(self, dt):
        """Advance one command step; caller holds the lock."""
        delta = self._target - self._position
        if abs(delta) < 0.5:
            self._position = self._target
            self._velocity = 0.0
        else:
            speed = min(self._max_speed, sqrt(2 * self._acceleration * abs(delta)), 8 * abs(delta))
            desired = copysign(speed, delta)
            max_change = self._acceleration * dt
            self._velocity += max(-max_change, min(max_change, desired - self._velocity))
            step = self._velocity * dt
            if step * delta > 0 and abs(step) >= abs(delta):
                self._position = self._target
                self._velocity = 0.0
            else:
                self._position = max(self.min_us, min(self.max_us, self._position + step))
                if self._position in (self.min_us, self.max_us):
                    self._velocity = 0.0
        pulse = round(self._position)
        if pulse != self._written:
            self._hardware.set_pulse(pulse)
            self._written = pulse

    def _run(self):
        try:
            previous = monotonic()
            while not self._stop.wait(0.020):
                now = monotonic()
                dt = min(0.04, now - previous)
                previous = now
                with self._lock:
                    self._advance(dt)

        except Exception as exc:
            with self._lock:
                self._error = exc

            self._stop.set()

            # Stop PWM if the worker encounters an error.
            try:
                self._hardware.close()
            except Exception:
                pass

    def close(self, *, hold_position=False):
        self._stop.set()

        if self._thread is not None:
            self._thread.join(timeout=1.0)

        if (
            self._thread is not None
            and self._thread.is_alive()
        ):
            raise RuntimeError(
                "Servo worker did not stop"
            )

        if hold_position:
            self._hardware.close(hold_position=True)
        else:
            self._hardware.close()
