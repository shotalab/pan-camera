#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this setup with sudo" >&2
    exit 1
fi

chip=""

for candidate in /sys/class/pwm/pwmchip*; do
    [ -e "$candidate/npwm" ] || continue

    case "$(readlink -f "$candidate")" in
        *1f00098000.pwm*)
            chip="$candidate"
            break
            ;;
    esac
done

if [ -z "$chip" ]; then
    echo "RP1 hardware PWM controller not found" >&2
    exit 1
fi

pwm="$chip/pwm2"

if [ ! -d "$pwm" ]; then
    printf '2\n' > "$chip/export"
fi

if [ ! -d "$pwm" ]; then
    echo "PWM channel 2 export failed" >&2
    exit 1
fi

if [ "$(cat "$pwm/enable")" != "0" ]; then
    echo "PWM channel is already active; refusing setup" >&2
    exit 1
fi

if [ "$(cat "$pwm/polarity")" != "normal" ]; then
    echo "Unexpected PWM polarity" >&2
    exit 1
fi

if [ "$(cat "$pwm/period")" != "0" ]; then
    printf '0\n' > "$pwm/duty_cycle"
fi

printf '20000000\n' > "$pwm/period"
printf '0\n' > "$pwm/duty_cycle"

chgrp gpio "$pwm/duty_cycle" "$pwm/enable"
chmod 660 "$pwm/duty_cycle" "$pwm/enable"

echo "Hardware PWM prepared: $pwm"
