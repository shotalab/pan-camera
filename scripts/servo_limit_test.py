# SPDX-License-Identifier: AGPL-3.0-only

"""PAN-CAMERA hardware PWM servo range test."""

from pathlib import Path
from time import sleep

from pan_camera.actuator import ServoConfig, PanServo


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "servo.toml"


def main():
    config = ServoConfig.load(CONFIG_PATH)

    positions = [
        ("CENTER", config.center_us),
        ("RIGHT", config.right_us),
        ("CENTER", config.center_us),
        ("LEFT", config.left_us),
        ("CENTER", config.center_us),
    ]

    print("PAN-CAMERA - Servo Range Test")
    print("PWM: Hardware / GPIO18")
    print(
        f"Range: {config.right_us} - "
        f"{config.left_us} us"
    )
    print("Press Ctrl+C to stop.")
    print()

    try:
        with PanServo(config) as servo:
            for name, pulse in positions:
                print(
                    f"{name:>6}: {pulse} us",
                    flush=True,
                )

                servo.move_to(pulse)
                sleep(0.8)

    except KeyboardInterrupt:
        print("\nTest interrupted")

    print("PWM stopped")
    print("Range test finished")


if __name__ == "__main__":
    main()
