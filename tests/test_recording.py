# SPDX-License-Identifier: AGPL-3.0-only

import json
from pathlib import Path
from queue import Queue
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from pan_camera.raw_recorder import RecordingConfig, RawAVRecorder
from pan_camera.recorder import Recorder


class TestRecordingLifecycle(unittest.TestCase):
    def test_camera_device_configuration_accepts_indices_and_device_paths(self):
        with TemporaryDirectory() as directory:
            config_dir = Path(directory) / 'config'
            config_dir.mkdir()
            path = config_dir / 'recording.toml'
            with patch('pan_camera.raw_recorder.ROOT', Path(directory)):
                for value, expected in (('0', 0), ('2', 2), ('"/dev/v4l/by-id/camera"', '/dev/v4l/by-id/camera')):
                    with self.subTest(value=value):
                        path.write_text(f'[recording]\ncamera_device = {value}\n')
                        self.assertEqual(RecordingConfig.load().camera_device, expected)
                for value in ('-1', 'true', '"camera"'):
                    with self.subTest(value=value):
                        path.write_text(f'[recording]\ncamera_device = {value}\n')
                        with self.assertRaisesRegex(ValueError, 'Invalid recording'):
                            RecordingConfig.load()

    def test_alsa_uses_device_options_for_channels_and_rate(self):
        recorder = RawAVRecorder(RecordingConfig())
        args = recorder._audio_input()
        self.assertEqual(args[args.index('-channels') + 1], '1')
        self.assertEqual(args[args.index('-sample_rate') + 1], '48000')
        self.assertEqual(args[args.index('-analyzeduration') + 1], '1')

    @patch('pan_camera.raw_recorder.MAX_QUEUE_BYTES', 3)
    def test_queue_memory_limit_does_not_allocate_an_oversized_packet(self):
        recorder = RawAVRecorder(RecordingConfig())
        recorder._queue = Queue(maxsize=60)
        recorder.submit(b'1234')
        with self.assertRaisesRegex(RuntimeError, 'memory limit'):
            recorder.check()
        self.assertTrue(recorder._queue.empty())

    def test_queue_overflow_reports_failure_without_blocking_capture(self):
        recorder = RawAVRecorder(RecordingConfig())
        recorder._queue = Queue(maxsize=1)
        recorder._started = time.monotonic()
        recorder._last_timestamp = -1
        recorder.submit(b'first')
        recorder.submit(b'second')
        with self.assertRaisesRegex(RuntimeError, 'queue overflow'):
            recorder.check()
        self.assertEqual(recorder._queue.qsize(), 1)

    @patch('pan_camera.recorder.RECORD_DIR')
    @patch('pan_camera.recorder.shutil.disk_usage')
    @patch('pan_camera.recorder.RawAVRecorder')
    @patch('pan_camera.recorder.cv2.VideoWriter')
    @patch('pan_camera.recorder.DisplayRecorder')
    def test_start_failure_rolls_back_annotated_writer(self, display, writer, raw, disk, directory):
        disk.return_value.free = 1024**3
        raw.return_value.start.side_effect = RuntimeError('audio unavailable')
        recorder = Recorder(8, raw_config=RecordingConfig())
        with self.assertRaisesRegex(RuntimeError, 'audio unavailable'):
            recorder.start()
        writer.return_value.release.assert_called_once()
        display.return_value.stop.assert_called_once()
        self.assertFalse(recorder.active)

    @patch('pan_camera.raw_recorder.shutil.which', return_value=None)
    def test_missing_ffmpeg_fails_before_start(self, _which):
        recorder = RawAVRecorder(RecordingConfig())
        with self.assertRaisesRegex(RuntimeError, 'Install ffmpeg'):
            recorder.start(Path('/tmp/unused-original.mkv'))
        self.assertIsNone(recorder._process)

    def test_cleanup_failure_still_closes_audio(self):
        for failing_writer in ('writer', 'display'):
            with self.subTest(failing_writer=failing_writer):
                recorder = Recorder(8)
                recorder.writer = Mock()
                recorder.display = Mock()
                if failing_writer == 'writer':
                    recorder.writer.release.side_effect = RuntimeError('disk failure')
                else:
                    recorder.display.stop.side_effect = RuntimeError('disk failure')
                recorder.raw = Mock()
                with self.assertRaisesRegex(RuntimeError, 'disk failure'):
                    recorder.stop()
                self.assertIsNone(recorder.display)
                recorder.raw.stop.assert_called_once()
                self.assertFalse(recorder.active)

    @patch('pan_camera.recorder.RECORD_DIR')
    @patch('pan_camera.recorder.shutil.disk_usage')
    @patch('pan_camera.recorder.cv2.VideoWriter')
    @patch('pan_camera.recorder.DisplayRecorder')
    def test_display_can_be_disabled(self, display, writer, disk, _directory):
        disk.return_value.free = 1024**3
        recorder = Recorder(8, RecordingConfig(raw_enabled=False, display_enabled=False))
        recorder.start()
        recorder.stop()
        display.assert_not_called()
        writer.return_value.release.assert_called_once()


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools required')
class TestOriginalRecordingIntegration(unittest.TestCase):
    def test_delayed_start_accepts_more_than_eight_large_frames(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'delayed.mp4'
            recorder = RawAVRecorder(RecordingConfig())
            recorder._audio_input = lambda: [
                '-re', '-use_wallclock_as_timestamps', '1', '-f', 'lavfi', '-i',
                'sine=frequency=440:sample_rate=48000',
            ]
            command = recorder._command
            recorder._command = lambda output: [
                sys.executable, '-c',
                'import os,sys,time; time.sleep(.8); os.execvp(sys.argv[1],sys.argv[1:])',
                *command(output),
            ]
            pixels = np.random.default_rng(7).integers(0, 256, (720, 1280, 3), dtype=np.uint8)
            _, data = cv2.imencode('.jpg', pixels, [cv2.IMWRITE_JPEG_QUALITY, 50])
            packet = data.tobytes()
            self.assertGreater(len(packet), 100_000)
            recorder.start(path)
            try:
                for _ in range(40):
                    recorder.submit(packet)
                    recorder.check()
                    time.sleep(.035)
            finally:
                recorder.stop()
            info = json.loads(subprocess.check_output([
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-count_packets', '-show_streams', '-of', 'json', str(path),
            ]))
            self.assertEqual(int(info['streams'][0]['nb_read_packets']), 40)

    def test_audio_failure_is_reported_and_process_is_reaped(self):
        with TemporaryDirectory() as directory:
            recorder = RawAVRecorder(RecordingConfig())
            recorder._audio_input = lambda: ['-f', 'lavfi', '-i', 'missing_audio_generator']
            recorder.start(Path(directory) / 'failed.mkv')
            _, encoded = cv2.imencode('.jpg', np.zeros((720, 1280, 3), np.uint8))
            try:
                deadline = time.monotonic() + 2
                while recorder._process.poll() is None and time.monotonic() < deadline:
                    recorder.submit(encoded.tobytes())
                    time.sleep(.03)
                with self.assertRaises(RuntimeError):
                    recorder.check()
            finally:
                with self.assertRaises(RuntimeError):
                    recorder.stop()
            self.assertIsNone(recorder._process)
            self.assertIsNone(recorder._thread)

    def test_mjpeg_streamcopy_and_audio_finalize(self):
        self.check_recording('copy')

    def test_h264_aac_mp4_preserves_frame_times_and_decodes(self):
        self.check_recording('h264')

    def check_recording(self, codec):
        with TemporaryDirectory() as directory:
            config = RecordingConfig(video_codec=codec)
            path = Path(directory) / ('clean' + config.output_suffix)
            recorder = RawAVRecorder(config)
            # Generated audio only: no real microphone or camera is accessed.
            recorder._audio_input = lambda: [
                '-re', '-use_wallclock_as_timestamps', '1', '-f', 'lavfi', '-i',
                'sine=frequency=440:sample_rate=48000',
            ]
            packets = []
            timestamps = []
            recorder.start(path)
            try:
                for number in range(24):
                    _, encoded = cv2.imencode('.jpg', np.full((720, 1280, 3), number * 8, np.uint8))
                    packet = encoded.tobytes()
                    packets.append(packet)
                    recorder.submit(packet)
                    timestamps.append(recorder._last_timestamp)
                    time.sleep(.04)
                recorder.check()
            finally:
                recorder.stop()
            info = json.loads(subprocess.check_output([
                'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)
            ]))
            video = next(s for s in info['streams'] if s['codec_type'] == 'video')
            audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
            self.assertEqual((video['codec_name'], video['width'], video['height']),
                             ('mjpeg' if codec == 'copy' else 'h264', 1280, 720))
            self.assertEqual(audio['codec_name'], 'pcm_s16le' if codec == 'copy' else 'aac')
            self.assertTrue(.5 < float(info['format']['duration']) < 4)
            timing = json.loads(subprocess.check_output([
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_packets', '-of', 'json', str(path),
            ]))['packets']
            actual = [float(packet['pts_time']) for packet in timing]
            self.assertEqual(len(actual), len(timestamps))
            for index, timestamp in enumerate(timestamps):
                self.assertAlmostEqual(actual[index] - actual[0],
                                       (timestamp - timestamps[0]) / 1000, delta=.002)
            if codec == 'copy':
                copied = subprocess.check_output([
                    'ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0',
                    '-c:v', 'copy', '-copytb', '1', '-f', 'image2pipe', 'pipe:1',
                ])
                self.assertEqual(copied, b''.join(packets))
            else:
                self.assertLess(path.stat().st_size, sum(map(len, packets)))
                subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.assertIsNone(recorder._process)
            self.assertIsNone(recorder._thread)
