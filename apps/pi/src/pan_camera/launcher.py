# SPDX-License-Identifier: AGPL-3.0-only
"""Small, fixed-command supervisor for the M5Stack application menu."""

import logging
import secrets
import signal
import socket
import subprocess
import sys
import time
import tomllib
from collections import OrderedDict

from .paths import ROOT

LOG = logging.getLogger(__name__)


class Launcher:
    def __init__(self):
        self.session = secrets.randbits(32)
        self.process = None
        self.stopping = False
        self.failed = False
        self.replies = OrderedDict()

    @property
    def state(self):
        if self.process is not None:
            result = self.process.poll()
            if result is None:
                return 2 if self.stopping else 1
            self.failed = result != 0
            self.process = None
            self.stopping = False
        return 3 if self.failed else 0

    def start(self):
        if self.state in (1, 2):
            return 2 if self.stopping else 0
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-u", "-m", "pan_camera", "--allow-servo", "--fps", "0"],
                cwd=ROOT, start_new_session=True,
            )
        except OSError:
            LOG.exception("Application start failed")
            self.failed = True
            return 3
        self.failed = False
        LOG.info("Application started: PID %s", self.process.pid)
        return 0

    def stop(self):
        if self.state == 1:
            # SIGINT runs the application's existing recording and PWM cleanup.
            try:
                self.process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            self.stopping = True
            LOG.info("Application stop requested")
        return 0

    def command(self, data):
        try:
            magic, session, client, sequence, action = data.decode("ascii").split(",")
            session, client, sequence = map(int, (session, client, sequence))
            if magic != "P2L1" or any(not 0 <= n <= 0xFFFFFFFF for n in (session, client, sequence)):
                return None
        except (ValueError, UnicodeError):
            return None
        if session != self.session:
            code = 4
        else:
            key = (client, sequence)
            if key in self.replies:
                code = self.replies[key]
            else:
                code = self.start() if action == "START" else self.stop() if action == "STOP" else 3
                self.replies[key] = code
                if len(self.replies) > 128:
                    self.replies.popitem(last=False)
        return f"P2R1,{self.session},{client},{sequence},{code}".encode("ascii")

    def status(self):
        state = self.state
        pid = self.process.pid if self.process is not None else 0
        return f"P2S1,{self.session},{pid},{state}".encode("ascii")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    with (ROOT / "config/network.toml").open("rb") as file:
        network = tomllib.load(file)["network"]
    peer = (network["m5stack_ip"], network["video_port"])
    launcher = Launcher()
    running = True

    def shutdown(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", network.get("launcher_port", 5007)))
        sock.settimeout(0.2)
        last_status = 0.0
        LOG.info("Launcher ready; application is stopped")
        try:
            while running:
                try:
                    data, source = sock.recvfrom(256)
                except socket.timeout:
                    pass
                else:
                    # Same trusted peer restriction as application control.
                    if source == peer:
                        response = launcher.command(data)
                        if response is not None:
                            sock.sendto(response, peer)
                            last_status = 0.0
                if time.monotonic() - last_status >= 1.0:
                    sock.sendto(launcher.status(), peer)
                    last_status = time.monotonic()
        finally:
            launcher.stop()
            if launcher.process is not None:
                try:
                    launcher.process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    LOG.error("Application cleanup did not complete within 30 seconds")


if __name__ == "__main__":
    main()
