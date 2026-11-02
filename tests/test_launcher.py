# SPDX-License-Identifier: AGPL-3.0-only
import signal
import unittest
from unittest.mock import patch

from pan_camera.launcher import Launcher


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.launcher = Launcher()

    def command(self, action, sequence=1, session=None):
        session = self.launcher.session if session is None else session
        return self.launcher.command(f"P2L1,{session},12,{sequence},{action}".encode())

    @patch('pan_camera.launcher.subprocess.Popen')
    def test_start_duplicate_and_stop_cleanup_signal(self, popen):
        popen.return_value.poll.return_value = None
        self.assertTrue(self.command('START').endswith(b',0'))
        self.command('START')
        self.command('START', 2)
        popen.assert_called_once()
        self.assertIn('--allow-servo', popen.call_args.args[0])
        self.assertEqual(self.launcher.state, 1)
        self.command('STOP', 3)
        self.command('STOP', 4)
        popen.return_value.send_signal.assert_called_once_with(signal.SIGINT)
        self.assertEqual(self.launcher.state, 2)
        popen.return_value.poll.return_value = 0
        self.assertEqual(self.launcher.state, 0)

    @patch('pan_camera.launcher.subprocess.Popen')
    def test_invalid_and_stale_requests_do_not_launch(self, popen):
        self.assertIsNone(self.launcher.command(b'garbage'))
        self.assertIsNone(self.launcher.command(b'P2L1,1,2,-3,START'))
        self.assertIsNone(self.command('START', session=-1))
        self.assertTrue(self.command('START', session=self.launcher.session ^ 1).endswith(b',4'))
        self.assertTrue(self.command('rm -rf').endswith(b',3'))
        popen.assert_not_called()

    @patch('pan_camera.launcher.subprocess.Popen')
    def test_error_is_visible_and_restart_is_allowed(self, popen):
        popen.return_value.poll.return_value = 1
        self.command('START')
        self.assertEqual(self.launcher.state, 3)
        popen.return_value.poll.return_value = None
        self.command('START', 2)
        self.assertEqual(self.launcher.state, 1)
        self.assertEqual(popen.call_count, 2)

    def test_stop_when_already_stopped(self):
        self.assertTrue(self.command('STOP').endswith(b',0'))
        self.assertEqual(self.launcher.state, 0)
