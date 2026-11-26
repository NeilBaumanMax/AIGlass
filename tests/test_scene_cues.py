"""Synthetic masks: test speech interpretation, not model accuracy or clearance."""
import unittest

import numpy as np

from backend.scene_cues import describe_scene


class SceneCueTests(unittest.TestCase):
    def setUp(self):
        self.floor = np.zeros((200, 160), bool)
        self.obstacles = np.zeros_like(self.floor)
        self.stairs = np.zeros_like(self.floor)

    def describe(self, direction='stop'):
        return describe_scene(self.floor, self.obstacles, self.stairs, direction)

    def test_visible_side_is_observation_not_permission_to_walk(self):
        for span, expected in ((slice(15, 60), 'scan_left'), (slice(100, 145), 'scan_right'),
                               (slice(60, 100), 'scan_ahead')):
            with self.subTest(expected=expected):
                self.floor[:] = False
                self.floor[100:185, span] = True
                self.assertEqual(self.describe()['kind'], expected)

    def test_no_floor_noise_or_narrow_sliver_does_not_invent_route(self):
        self.assertEqual(self.describe()['kind'], 'unclear')
        self.floor[95:190:4, 20:130:4] = True
        self.assertEqual(self.describe()['kind'], 'unclear')
        self.floor[:] = False
        self.floor[100:190, 30:33] = True
        self.assertEqual(self.describe()['kind'], 'unclear')

    def test_two_disconnected_sides_do_not_pick_arbitrary_turn(self):
        self.floor[100:185, 15:60] = True
        self.floor[100:185, 100:145] = True
        self.assertEqual(self.describe()['kind'], 'stop')

    def test_only_upstream_valid_path_gives_walking_direction(self):
        self.floor[80:, 40:120] = True
        for direction in ('left', 'right', 'straight'):
            self.assertEqual(self.describe(direction)['kind'], direction)
        self.assertEqual(self.describe()['kind'], 'scan_ahead')

    def test_hazard_overrides_green_but_keeps_valid_alternative_direction(self):
        self.floor[80:, 40:120] = True
        self.obstacles[115:180, 60:100] = True
        self.assertEqual(self.describe('straight')['kind'], 'obstacle')
        self.assertEqual(self.describe('left')['kind'], 'obstacle_left')
        self.assertEqual(self.describe('right')['kind'], 'obstacle_right')
        self.assertEqual(self.describe()['kind'], 'obstacle')
        self.stairs[120:175, 65:95] = True
        self.assertEqual(self.describe('left')['kind'], 'stairs')
