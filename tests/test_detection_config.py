# SPDX-License-Identifier: AGPL-3.0-only

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from pan_camera.detection_config import enabled_classes
from pan_camera.app import extract_tracks


class TestDetectionConfig(unittest.TestCase):
    def test_enabled_switches_and_cli_override(self):
        names = {0: 'person', 39: 'bottle', 41: 'cup'}
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'detection.toml'
            path.write_text('[classes]\ncup=true\nperson=true\nbottle=false\n')
            self.assertEqual(enabled_classes(names, path=path), [0, 41])
            self.assertEqual(enabled_classes(names, ['bottle'], path=path), [39])
            path.write_text('[classes]\ncup=false\n')
            with self.assertRaises(ValueError):
                enabled_classes(names, path=path)
            path.write_text('[classes]\ncup="true"\n')
            with self.assertRaises(ValueError):
                enabled_classes(names, path=path)
        with self.assertRaises(ValueError):
            enabled_classes(names, ['dragon'])

    def test_extracted_tracks_keep_class_and_name(self):
        import torch
        from ultralytics.engine.results import Boxes
        result = Mock()
        result.names = {0: 'person', 41: 'cup'}
        # Tracking boxes: x1,y1,x2,y2,track_id,confidence,class_id
        result.boxes = Boxes(torch.tensor([[0,0,100,200,7,.9,0], [200,0,300,100,8,.8,41]], dtype=torch.float32), (720,1280))
        tracks = extract_tracks(result)
        self.assertEqual([(t['id'], t['class_id'], t['name']) for t in tracks],
                         [(7,0,'person'), (8,41,'cup')])
