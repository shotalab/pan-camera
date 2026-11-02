# SPDX-License-Identifier: AGPL-3.0-only

"""Select pretrained detector classes by name."""

import tomllib

from .paths import ROOT


def enabled_classes(names, override=None, path=None):
    if override is None:
        with (path or ROOT / "config/detection.toml").open("rb") as f:
            switches = tomllib.load(f)["classes"]
        if any(type(value) is not bool for value in switches.values()):
            raise ValueError("Detection switches must be true or false")
        requested = [name for name, enabled in switches.items() if enabled]
        unknown = set(switches) - set(names.values())
    else:
        requested = override
        unknown = set(requested) - set(names.values())
    if unknown:
        raise ValueError(f"Unknown detection classes: {', '.join(sorted(unknown))}")
    if not requested:
        raise ValueError("Enable at least one detection class")
    return [class_id for class_id, name in names.items() if name in requested]
