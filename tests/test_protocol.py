# SPDX-License-Identifier: AGPL-3.0-only

import struct
import unittest
from unittest.mock import Mock, patch

from pan_camera.protocol import send_video


class TestVideoProtocol(unittest.TestCase):
    @patch("pan_camera.protocol.time.sleep")
    def test_fragments_reassemble_with_expected_headers(self, _sleep):
        sock = Mock()
        jpeg = bytes(range(256)) * 5
        destination = ("127.0.0.1", 5005)
        send_video(sock, 12, 34, jpeg, destination)
        packets = [call.args for call in sock.sendto.call_args_list]
        self.assertEqual(len(packets), 2)
        for index, (packet, address) in enumerate(packets):
            self.assertEqual(address, destination)
            self.assertEqual(struct.unpack("!4sIIHHI", packet[:20]),
                             (b"P2V1", 12, 34, index, 2, len(jpeg)))
        self.assertEqual(b"".join(packet[20:] for packet, _ in packets), jpeg)
