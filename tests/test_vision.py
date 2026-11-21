"""Verify integration with the pinned upstream guidance, using controlled masks."""
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from vision import Vision, DIRECTION_MESSAGES
from walking_guidance import direction_path, render_guidance
from live_overlay import indoor_input, indoor_regions, render_regions
from outdoor_channel import channel_input, render_channel


class GuidanceTests(unittest.TestCase):
    def test_upstream_directions_and_disconnected_corridor(self):
        height, width = 200, 160
        for shift, expected in ((0, 'straight'), (-65, 'left'), (65, 'right')):
            with self.subTest(expected=expected):
                ground = np.zeros((height, width), dtype=bool)
                for y in range(65, height):
                    center = round(80 + shift * max(0, (180 - y) / 110))
                    ground[y, max(0, center - 18):min(width, center + 18)] = True
                points, hint = direction_path(ground)
                self.assertEqual(hint, expected)
                self.assertTrue(points)
                self.assertTrue(all(ground[y, x] for x, y in points))
                ground[130:145] = False
                self.assertEqual(direction_path(ground)[1], 'stop')
        self.assertEqual(direction_path(np.zeros((height, width), bool)), ([], 'stop'))

    def test_short_corridor_has_red_stop_endpoint_and_no_line_outside_mask(self):
        ground = np.zeros((200, 160), bool)
        ground[120:, 45:115] = True
        image = Image.new('RGB', (160, 200), '#202020')
        overlay, hint = render_guidance(image, ground)
        self.assertEqual(hint, 'stop')
        pixels = np.asarray(overlay)
        self.assertTrue(np.any(np.all(pixels == (255, 65, 65), axis=2)))
        np.testing.assert_array_equal(pixels[~ground], np.asarray(image)[~ground])

    def test_wrapper_matches_upstream_live_overlay_for_both_modes(self):
        vision = Vision()
        vision.models = {'indoor': object(), 'outdoor': object()}
        image = Image.new('RGB', (640, 480), '#808080')
        for mode, ground_label in (('indoor', 3), ('outdoor', 0)):
            with self.subTest(mode=mode):
                if mode == 'indoor':
                    frame, clipped = indoor_input(image, enhance=True)
                else:
                    frame = channel_input(image)
                labels = np.full((frame.height, frame.width), ground_label, np.int64)
                confidence = np.ones_like(labels, np.float32)
                if mode == 'indoor':
                    regions = indoor_regions(labels, confidence, clipped)
                    expected, hint = render_guidance(render_regions(image, *regions), regions[0])
                else:
                    expected, hint = render_channel(image, labels, confidence, with_guidance=True)
                with patch('walkscapes.predict_mask', return_value=(labels, confidence)):
                    result, event = vision.analyze(image, mode)
                np.testing.assert_array_equal(np.asarray(result), np.asarray(expected))
                self.assertEqual(vision.analysis['direction'], hint)
                self.assertEqual(event, DIRECTION_MESSAGES[hint])

    def test_stairs_keep_priority_over_direction(self):
        vision = Vision()
        vision.models['indoor'] = object()
        image = Image.new('RGB', (512, 384), '#808080')
        labels = np.full((384, 512), 3, np.int64)
        labels[220:360, 180:330] = 53  # ADE stairs in the forward image region.
        with patch('walkscapes.predict_mask', return_value=(labels, np.ones_like(labels, np.float32))):
            _, event = vision.analyze(image, 'indoor')
        self.assertEqual(event, '前方疑似台阶')


if __name__ == '__main__':
    unittest.main()
