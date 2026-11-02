# SPDX-License-Identifier: AGPL-3.0-only

import unittest
import struct
from unittest.mock import MagicMock, call, patch

from pan_camera import app


class TestTrackingStop(unittest.TestCase):
    def test_startup_failure_does_not_enable_servo(self):
        for failure in ("open", "capture", "bind"):
            with self.subTest(failure=failure):
                source = MagicMock()
                camera = MagicMock()
                sock = MagicMock()
                if failure == "open":
                    source.__enter__.side_effect = RuntimeError("Camera open failed")
                elif failure == "capture":
                    camera.__enter__.return_value.read.side_effect = RuntimeError("Camera capture failed")
                else:
                    sock.bind.side_effect = OSError("Port unavailable")
                with patch.object(app, "YOLO", return_value=MagicMock(names={0: "person", 39: "bottle", 41: "cup", 67: "cell phone", 73: "book"})), \
                     patch.object(app, "load_network", return_value=(("127.0.0.1", 5005), 5006)), \
                     patch.object(app, "USBCamera169", return_value=source), \
                     patch.object(app, "LatestFrameCamera", return_value=camera), \
                     patch.object(app.socket, "socket") as socket_class, \
                     patch.object(app, "SmoothPanServo") as servo_class, \
                     patch("sys.argv", ["pan_camera", "--classes", "cup", "person", "--allow-servo", "--frames", "1"]):
                    socket_class.return_value.__enter__.return_value = sock
                    with self.assertRaises((RuntimeError, OSError)):
                        app.main()
                    servo_class.assert_not_called()

    def test_button_stop_holds_pwm_until_program_exit(self):
        self.check_stop("TOGGLE", 3)

    def test_select_stops_tracking_and_changes_target(self):
        self.check_stop("SEL", 65535)

    def test_camera_loss_holds_servo_and_closes_recording(self):
        self.check_stop(None, None, camera_lost=True)

    def check_stop(self, stop_command, expected_selected, camera_lost=False):
        peer = ("192.168.0.115", 5005)
        commands = iter([
            BlockingIOError(),
            (b"P2C1,123,1,1,SEL", peer),
            (b"P2C1,123,1,2,TOGGLE", peer),
            (f"P2C1,123,1,3,{'REC' if camera_lost else stop_command}".encode(), peer),
            BlockingIOError() if camera_lost else (b"P2C1,123,1,4,SEL", peer),
            BlockingIOError(),
        ])
        sock = MagicMock()
        def receive(_size):
            servo.__enter__.assert_called_once()  # centered before remote commands
            self.assertGreaterEqual(camera.__enter__.return_value.read.call_count, 1)
            item = next(commands, BlockingIOError())
            if isinstance(item, Exception):
                raise item
            return item
        sock.recvfrom.side_effect = receive
        servo = MagicMock()
        servo.current_us = 1500
        servo.__enter__.return_value = servo
        frame = MagicMock()
        frame.shape = (720, 1280, 3)
        camera = MagicMock()
        camera.__enter__.return_value.read.return_value = frame
        if camera_lost:
            camera.__enter__.return_value.read.side_effect = [frame, frame, RuntimeError("Camera capture failed")]
        with patch.object(app, "load_network", return_value=(peer, 5006)), \
             patch.object(app.secrets, "randbits", return_value=123), \
             patch.object(app, "YOLO", return_value=MagicMock(names={0: "person", 39: "bottle", 41: "cup", 67: "cell phone", 73: "book"})), \
             patch.object(app, "USBCamera169", return_value=camera), \
             patch.object(app, "LatestFrameCamera", return_value=camera), \
             patch.object(app.socket, "socket") as socket_class, \
             patch.object(app, "SmoothPanServo", return_value=servo) as servo_class, \
             patch.object(app, "extract_tracks", return_value=[{"id": 2, "cx": 640, "confidence": 0.9, "class_id": 41, "name": "cup"}, {"id": 3, "cx": 900, "confidence": 0.8, "class_id": 41, "name": "cup"}]), \
             patch.object(app, "draw_preview"), \
             patch.object(app, "encode_jpeg", return_value=None), \
             patch.object(app, "Recorder") as recorder_class, \
             patch.object(app.time, "sleep"), \
             patch("sys.argv", ["pan_camera", "--classes", "cup", "person", "--allow-servo", "--frames", "2" if camera_lost else "1"]):
            recorder_class.return_value.active = False
            socket_class.return_value.__enter__.return_value = sock
            if camera_lost:
                with self.assertRaises(SystemExit) as exit_status:
                    app.main()
                self.assertEqual(exit_status.exception.code, 1)
            else:
                app.main()
        if camera_lost:
            servo.close.assert_called_once_with(hold_position=True)
            recorder_class.return_value.start.assert_called_once()
            recorder_class.return_value.stop.assert_called_once()
            self.assertEqual(servo.set_target.call_count, 2)  # startup + first tracking frame only
            return
        self.assertEqual(servo.hold.call_count, 2)  # start and stop
        servo_class.assert_called_once()
        self.assertEqual(servo_class.call_args.kwargs["initial_us"], 1500)
        servo.close.assert_called_once()
        self.assertLess(servo.method_calls.index(call.hold()), servo.method_calls.index(call.close()))
        replies = [c.args[0] for c in sock.sendto.call_args_list if c.args[0].startswith(b"P2A1")]
        self.assertIn(b"P2A1,123,1,4,0", replies)  # selection allowed after stop
        self.assertIn(b"P2A1,123,1,3,0", replies)
        status = next(c.args[0] for c in sock.sendto.call_args_list if c.args[0].startswith(b"P2T2"))
        fields = struct.unpack(app.TELEMETRY, status)
        self.assertEqual(fields[6], 0)  # STANDBY, no automatic restart
        self.assertEqual(fields[10], expected_selected)
