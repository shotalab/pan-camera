# SPDX-License-Identifier: AGPL-3.0-only

"""Run PAN-CAMERA."""

from .app import main

try:
    main()
except KeyboardInterrupt:
    print("\nInterrupted")
