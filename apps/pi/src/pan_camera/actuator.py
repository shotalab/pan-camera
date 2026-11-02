# SPDX-License-Identifier: AGPL-3.0-only

"""PAN-CAMERA hardware PWM servo actuator."""

from dataclasses import dataclass
from pathlib import Path
from time import sleep
import tomllib
import fcntl
import hashlib


PWM_ROOT = Path("/sys/class/pwm")


@dataclass(frozen=True)
class ServoConfig:
    gpio: int
    pwm_controller: str
    pwm_channel: int
    frequency_hz: int
    right_us: int
    center_us: int
    left_us: int
    step_us: int
    step_interval_s: float
    max_speed_us_per_s: float = 600.0
    acceleration_us_per_s2: float = 1800.0

    @classmethod
    def load(cls, path: str | Path) -> "ServoConfig":
        with Path(path).open("rb") as f:
            data = tomllib.load(f)["servo"]

        config = cls(**data)

        if (
            config.gpio != 18
            or config.pwm_channel != 2
            or config.pwm_controller != "1f00098000.pwm"
        ):
            raise ValueError("Unexpected GPIO18 PWM mapping")

        if config.frequency_hz != 50:
            raise ValueError("SG90 requires 50Hz configuration")

        if not (
            500 <= config.right_us
            < config.center_us
            < config.left_us <= 2500
        ):
            raise ValueError("Invalid servo pulse range")

        if config.step_us <= 0 or config.step_interval_s <= 0:
            raise ValueError("Invalid movement settings")
        if not (0 < config.max_speed_us_per_s <= 2000
                and 0 < config.acceleration_us_per_s2 <= 10000):
            raise ValueError("Invalid motion profile settings")

        return config


class PanServo:
    def __init__(
        self,
        config: ServoConfig,
        pwm_dir: Path | None = None,
        *,
        initial_us: int | None = None,
        resume_held: bool = False,
    ):
        self.config = config
        self._test_pwm_dir = pwm_dir
        self._pwm = None
        self._current_us = None
        self._resume_held = resume_held
        self._lease = None
        self._initial_us = (
            config.center_us if initial_us is None
            else initial_us
        )
        if not config.right_us <= self._initial_us <= config.left_us:
            raise ValueError("Invalid initial servo pulse")

    def _find_pwm_dir(self) -> Path:
        if self._test_pwm_dir is not None:
            return self._test_pwm_dir

        chips = [
            chip
            for chip in PWM_ROOT.glob("pwmchip*")
            if self.config.pwm_controller in str(chip.resolve())
        ]

        if len(chips) != 1:
            raise RuntimeError("RP1 PWM controller not found")

        return chips[0] / f"pwm{self.config.pwm_channel}"

    def __enter__(self):
        if self._pwm is not None:
            raise RuntimeError("Servo already open")

        pwm = self._find_pwm_dir()
        key = hashlib.sha256(str(pwm.resolve()).encode()).hexdigest()[:16]
        lease = Path(f"/tmp/pan-camera-pwm-{key}.lock").open("a+")
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            lease.close()
            raise RuntimeError("Servo is controlled by another process")
        self._lease = lease
        try:
            return self._open_pwm(pwm)
        except BaseException:
            self._release_lease()
            raise

    def _open_pwm(self, pwm):

        if not pwm.is_dir():
            raise RuntimeError(
                "PWM not prepared. Run setup_hardware_pwm.sh"
            )

        expected_period = (
            1_000_000_000 // self.config.frequency_hz
        )

        actual_period = int(
            (pwm / "period").read_text().strip()
        )

        if actual_period != expected_period:
            raise RuntimeError("Unexpected PWM period")

        if (pwm / "polarity").read_text().strip() != "normal":
            raise RuntimeError("Unexpected PWM polarity")

        if (pwm / "enable").read_text().strip() != "0":
            duty = int((pwm / "duty_cycle").read_text().strip())
            self._lease.seek(0)
            marker = self._lease.read().strip()
            if (self._resume_held and marker == f"HOLD {duty}"
                    and duty % 1000 == 0
                    and self.config.right_us <= duty // 1000 <= self.config.left_us):
                self._pwm = pwm
                self._current_us = duty // 1000
                self._write_marker("")
                return self
            raise RuntimeError("PWM channel already in use")

        self._write_marker("")
        self._pwm = pwm

        try:
            self._write(self._initial_us)
            (pwm / "enable").write_text("1")
            sleep(0.5)
        except BaseException:
            self.close()
            raise

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _write(self, pulse_us: int):
        if self._pwm is None:
            raise RuntimeError("Servo is not open")

        duty_ns = pulse_us * 1000

        (self._pwm / "duty_cycle").write_text(str(duty_ns))
        self._current_us = pulse_us

    def set_pulse(self, pulse_us: int):
        """Write one hardware-PWM pulse without blocking."""
        if not self.config.right_us <= pulse_us <= self.config.left_us:
            raise ValueError("Servo pulse outside configured range")
        self._write(pulse_us)

    def move_to(self, target_us: int):
        c = self.config

        if not c.right_us <= target_us <= c.left_us:
            raise ValueError(
                f"Pulse must be between "
                f"{c.right_us} and {c.left_us} us"
            )

        if self._pwm is None:
            raise RuntimeError("Servo is not open")

        while self._current_us != target_us:
            delta = target_us - self._current_us

            step = min(abs(delta), c.step_us)
            direction = 1 if delta > 0 else -1

            next_us = self._current_us + direction * step
            self._write(next_us)
            sleep(c.step_interval_s)

    def center(self):
        self.move_to(self.config.center_us)

    @property
    def current_us(self):
        return self._current_us

    def _write_marker(self, value):
        self._lease.seek(0)
        self._lease.truncate()
        self._lease.write(value)
        self._lease.flush()

    def _release_lease(self):
        if self._lease is not None:
            self._lease.close()
            self._lease = None

    def close(self, *, hold_position=False):
        if self._pwm is None:
            self._release_lease()
            return

        pwm = self._pwm

        try:
            if hold_position:
                # Hardware PWM continues after the process exits.
                self._write_marker(f"HOLD {self._current_us * 1000}")
            else:
                (pwm / "enable").write_text("0")
                self._write_marker("")
        finally:
            self._pwm = None
            self._current_us = None
            self._release_lease()
