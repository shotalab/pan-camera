# SPDX-License-Identifier: AGPL-3.0-only

"""M5Stack UDP video protocol and network settings."""

import struct
import time
import tomllib

from .paths import ROOT

TELEMETRY = "!4sIIHhHBBBBHBI"
CHUNK_SIZE = 1024
VIDEO_HEADER = "!4sIIHHI"


def load_network():
    with (ROOT / "config/network.toml").open("rb") as f:
        network = tomllib.load(f)["network"]
    return (network["m5stack_ip"], network["video_port"]), network["control_port"]


def send_video(sock, session, frame_id, jpeg, destination):
    count = (len(jpeg) + CHUNK_SIZE - 1) // CHUNK_SIZE
    for index in range(count):
        chunk = jpeg[index * CHUNK_SIZE:(index + 1) * CHUNK_SIZE]
        header = struct.pack(VIDEO_HEADER, b"P2V1", session, frame_id,
                             index, count, len(jpeg))
        sock.sendto(header + chunk, destination)
        time.sleep(0.002)
