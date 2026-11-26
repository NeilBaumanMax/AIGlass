"""Replay clocks and model decisions, never claim these are real camera detections."""
import threading
import unittest
from unittest.mock import patch

from backend.guidance import Alert, CUES, Guidance
from backend.app import create_app
from backend.runtime import Runtime
from backend.speech import Speech


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = Guidance(now=0)
        self.policy.engine = 'ready'
        self.seq = 0

    def feed(self, kind, times):
        for now in times:
            self.seq += 1
            self.policy.observe(kind, self.seq, now, now)

    def accepted(self, now):
        alert = self.policy.next_alert(now)
        self.assertIsNotNone(alert)
        self.policy.acknowledge(alert, 'accepted', now)
        return alert

    def test_flicker_and_duplicate_frames_do_not_trigger(self):
        self.feed('obstacle', [0, .1])
        self.assertIsNone(self.policy.next_alert(.1))
        self.feed('straight', [.2])
        self.feed('obstacle', [.3, .4])
        self.assertFalse(self.policy.observe('obstacle', self.seq, .6, .6))
        self.assertIsNone(self.policy.next_alert(.6))
        self.feed('obstacle', [.7])
        self.assertEqual(self.accepted(.7).kind, 'obstacle')

    def test_high_fps_does_not_skip_time_confirmation(self):
        self.feed('left', [i / 100 for i in range(30)])
        self.assertIsNone(self.policy.next_alert(.3))
        self.feed('left', [.6])
        self.assertEqual(self.accepted(.6).kind, 'left')

    def test_unstable_new_results_do_not_keep_old_hazard_alive(self):
        self.feed('obstacle', [0, .1, .2])
        alert = self.accepted(.2)
        for i in range(1, 20):
            self.feed('left' if i % 2 else 'right', [.2 + i * .1])
        self.assertFalse(self.policy.valid(alert, 2.1))
        self.assertIsNone(self.policy.snapshot(2.1)['confirmed'])

    def test_stale_or_future_result_not_accepted(self):
        self.assertFalse(self.policy.observe('stairs', 1, 0, 2))
        self.assertFalse(self.policy.observe('stairs', 2, 3, 2))
        self.assertEqual(self.policy.snapshot(2)['state'], 'waiting')

    def test_same_hazard_repeats_only_with_fresh_evidence_after_cooldown(self):
        self.feed('obstacle', [0, .1, .2])
        self.assertFalse(self.accepted(.2).repeated)
        for now in range(1, 8):
            self.feed('obstacle', [now])
            self.assertIsNone(self.policy.next_alert(now))
        self.feed('obstacle', [8.3])
        self.assertTrue(self.accepted(8.3).repeated)
        self.assertFalse(self.policy.valid(Alert('obstacle', self.policy.epoch), 10))

    def test_returning_hazard_after_confirmed_clear_is_a_new_warning(self):
        self.feed('obstacle', [0, .1, .2])
        self.accepted(.2)
        self.feed('straight', [.4, .7, 1.0])
        self.assertEqual(self.policy.stable, 'obstacle')
        self.feed('straight', [1.4])
        self.assertEqual(self.policy.stable, 'straight')
        self.feed('obstacle', [2.5, 2.6, 2.7])
        alert = self.accepted(2.8)
        self.assertFalse(alert.repeated)

    def test_escalation_does_not_wait_for_global_gap(self):
        self.feed('straight', [0, .3, .6])
        self.accepted(.6)
        self.feed('obstacle', [.7, .8, .9])
        self.assertEqual(self.accepted(.9).kind, 'obstacle')
        self.feed('stairs', [1, 1.1, 1.2])
        self.assertEqual(self.accepted(1.2).kind, 'stairs')

    def test_rejected_direction_is_retried_not_marked_spoken(self):
        self.feed('left', [0, .3, .6])
        alert = self.policy.next_alert(.6)
        self.policy.acknowledge(alert, 'deferred', .6)
        self.assertIsNone(self.policy.snapshot(.6)['last_spoken'])
        self.feed('left', [1.6])
        self.assertEqual(self.accepted(1.6).kind, 'left')

    def test_deferred_old_direction_never_survives_a_turn(self):
        self.feed('left', [0, .3, .6])
        alert = self.policy.next_alert(.6)
        self.policy.acknowledge(alert, 'deferred', .6)
        self.feed('right', [.7, 1.0, 1.3])
        self.assertFalse(self.policy.valid(alert, 1.3))
        self.feed('right', [1.7])
        self.assertEqual(self.accepted(1.7).kind, 'right')

    def test_mode_or_source_boundary_invalidates_pending_audio(self):
        self.feed('left', [0, .3, .6])
        alert = self.accepted(.6)
        self.policy.reset(.7)
        self.assertFalse(self.policy.valid(alert, .7))
        self.feed('left', [.8])
        self.assertIsNone(self.policy.next_alert(.8))

    def test_no_camera_reports_unavailable_once_not_directions(self):
        self.assertIsNone(self.policy.next_alert(7.9))
        self.assertEqual(self.accepted(8).kind, 'waiting')
        self.assertIsNone(self.policy.next_alert(30))
        self.assertIsNone(self.policy.snapshot(30)['confirmed'])
        self.policy.reconnect_audio(40)
        self.assertIsNone(self.policy.next_alert(41))
        self.assertEqual(self.accepted(48).kind, 'waiting')

    def test_loss_then_confirmed_recovery(self):
        self.feed('left', [8, 8.3, 8.6])
        self.accepted(8.6)
        self.assertEqual(self.accepted(11.2).kind, 'lost')
        self.feed('right', [12, 12.3, 12.6])
        self.assertIsNone(self.policy.next_alert(12.6))
        self.feed('right', [13.6, 14.6, 15.2])
        self.assertEqual(self.accepted(15.2).kind, 'restored')

    def test_recovery_never_delays_new_hazard(self):
        self.accepted(8)  # waiting notice
        self.feed('stairs', [8.1, 8.2, 8.3])
        self.assertEqual(self.accepted(8.3).kind, 'stairs')
        self.assertFalse(self.policy.needs_recovery)

    def test_inference_error_disables_existing_direction(self):
        self.feed('left', [8, 8.3, 8.6])
        alert = self.accepted(8.6)
        self.policy.engine = 'error'
        self.assertFalse(self.policy.valid(alert, 8.7))
        self.assertEqual(self.accepted(11.2).kind, 'error')

    def test_unknown_scene_does_not_repeat_every_eight_seconds(self):
        self.feed('stop', [0, .2, .4, .6, .8])
        self.accepted(.8)
        for now in range(1, 30):
            self.feed('stop', [now])
            self.assertIsNone(self.policy.next_alert(now))
        self.feed('stop', [30, 30.9])
        self.assertTrue(self.accepted(30.9).repeated)

    def test_uncertain_variants_share_cooldown_and_never_reinterrupt(self):
        self.feed('stop', [0, .2, .4, .6, .8])
        self.accepted(.8)
        self.feed('unclear', [1, 1.3, 1.6, 1.9, 2.2])
        self.assertIsNone(self.policy.next_alert(2.2))
        self.feed('scan_left', [2.5, 3, 3.5])
        self.assertIsNone(self.policy.next_alert(3.5))
        self.feed('scan_left', [4, 5, 6, 6.9])
        alert = self.accepted(6.9)
        self.assertEqual(alert.kind, 'scan_left')
        self.assertTrue(alert.repeated)
        self.assertFalse(alert.interrupts)

    def test_confirmed_route_after_unknown_is_not_held_by_unknown_cooldown(self):
        self.feed('stop', [0, .2, .4, .6, .8])
        self.accepted(.8)
        self.feed('left', [1, 1.4, 2.1, 3, 4, 4.9])
        self.assertEqual(self.accepted(4.9).kind, 'left')
        self.feed('stop', [5, 5.2, 5.4, 5.6, 5.8])
        self.assertFalse(self.accepted(5.8).repeated)

    def test_changed_direction_is_announced_without_waiting_for_repeat_timer(self):
        self.feed('left', [0, .3, .6])
        self.accepted(.6)
        self.feed('right', [1, 1.3, 1.6, 2.6, 3.6, 4.7])
        self.assertEqual(self.accepted(4.7).kind, 'right')
        self.feed('left', [5, 5.3, 5.6, 6.6, 7.6, 8.8])
        self.assertEqual(self.accepted(8.8).kind, 'left')

    def test_flickering_green_never_overrides_confirmed_unknown(self):
        self.feed('stop', [0, .2, .4, .6, .8])
        self.accepted(.8)
        for i in range(1, 20):
            self.feed('left' if i % 2 else 'stop', [.8 + i * .1])
        self.assertEqual(self.policy.stable, 'stop')
        self.assertIsNone(self.policy.next_alert(2.7))

    def test_side_observation_is_revoked_as_soon_as_side_changes(self):
        self.feed('scan_left', [0, .4, .8])
        alert = self.accepted(.8)
        self.feed('scan_right', [1])
        self.assertFalse(self.policy.valid(alert, 1))
        self.assertFalse(self.policy.valid(alert, 1, playing=True))


class SpeechGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.speech = Speech(self.runtime)
        self.speech.prompts.update({cue.prompt: b'test-wav' for cue in CUES.values()})
        self.runtime.guidance = Guidance(now=0)
        self.runtime.engine_state = 'ready'
        self.runtime.guidance.engine = 'ready'
        with patch('backend.speech.time.monotonic', return_value=100):
            self.session = self.speech.connect()
        self.speech.pending.clear()
        self.seq = 0

    def feed(self, kind, start=100):
        duration = CUES[kind].confirm_seconds
        for when in (start, start + duration / 2, start + duration):
            self.seq += 1
            self.runtime.guidance.observe(kind, self.seq, when, when)
        return start + duration

    def dispatch(self, now):
        with patch('backend.speech.time.monotonic', return_value=now):
            self.speech.seen = now
            return self.runtime.dispatch_guidance(now)

    def test_new_hazard_interrupts_agent_without_wake_or_cloud(self):
        self.speech.agent_cancel = threading.Event()
        self.speech.busy = True
        self.speech.enqueue('old AI answer', b'old')
        with patch('backend.qwen.ask') as ask, patch('backend.tts.synthesize') as tts:
            self.dispatch(self.feed('stairs'))
        ask.assert_not_called()
        tts.assert_not_called()
        self.assertTrue(self.speech.agent_cancel.is_set())
        self.assertEqual(self.speech.active['text'], CUES['stairs'].text)
        self.assertFalse(self.speech.pending)

    def test_repeat_hazard_does_not_keep_cancelling_a_conversation(self):
        self.dispatch(self.feed('obstacle'))
        self.speech.active = None
        self.speech.busy = True
        self.speech.agent_cancel = threading.Event()
        for when in range(101, 109):
            self.seq += 1
            self.runtime.guidance.observe('obstacle', self.seq, when, when)
        self.seq += 1
        self.runtime.guidance.observe('obstacle', self.seq, 108.3, 108.3)
        self.dispatch(108.3)
        self.assertFalse(self.speech.agent_cancel.is_set())
        self.assertEqual(self.runtime.guidance.delivery, 'deferred')

    def test_new_side_of_same_obstacle_does_not_cancel_agent_again(self):
        self.dispatch(self.feed('obstacle_left'))
        self.speech.active = None
        self.speech.busy = True
        self.speech.agent_cancel = threading.Event()
        for when in range(101, 108):
            self.seq += 1
            self.runtime.guidance.observe('obstacle_right', self.seq, when, when)
        self.dispatch(107)
        self.assertFalse(self.speech.agent_cancel.is_set())
        self.assertEqual(self.runtime.guidance.delivery, 'deferred')

    def test_low_priority_cannot_cut_off_stairs(self):
        self.dispatch(self.feed('stairs'))
        first = self.speech.active['id']
        for when in (100.3, 100.8, 101.3):
            self.seq += 1
            self.runtime.guidance.observe('obstacle', self.seq, when, when)
        # Direct delivery tests the speech priority gate independently of cooldown.
        with patch('backend.speech.time.monotonic', return_value=101.3):
            result = self.speech.alert(Alert('obstacle', self.runtime.guidance.epoch))
        self.assertEqual(result, 'priority_busy')
        self.assertEqual(self.speech.active['id'], first)

    def test_direction_deferred_in_dialog_is_rechecked_after_dialog(self):
        self.speech.awake_until = 108
        self.dispatch(self.feed('left'))
        self.assertFalse(self.speech.pending)
        self.speech.awake_until = 0
        self.dispatch(self.feed('right', 101))
        self.assertEqual(self.speech.pending[-1]['text'], CUES['right'].text)

    def test_no_speaker_or_missing_prompt_does_not_count_as_announced(self):
        now = self.feed('obstacle')
        self.speech.seen = 90
        with patch('backend.speech.time.monotonic', return_value=now):
            self.runtime.dispatch_guidance(now)
        self.assertEqual(self.runtime.guidance.delivery, 'audio_offline')
        self.assertIsNone(self.runtime.guidance.last_spoken)
        self.speech.prompts.pop('obstacle')
        self.dispatch(101.3)
        self.assertEqual(self.runtime.guidance.delivery, 'missing_audio')
        self.assertIsNone(self.runtime.guidance.last_spoken)

    def test_stale_queued_direction_is_dropped_at_device_poll(self):
        self.dispatch(self.feed('left'))
        with patch('backend.speech.time.monotonic', return_value=102.2):
            self.assertIsNone(self.speech.poll(self.session, False, None))
        self.assertFalse(self.speech.pending)

    def test_source_disconnect_cancels_already_playing_guidance(self):
        now = self.feed('left')
        self.dispatch(now)
        with patch('backend.speech.time.monotonic', return_value=now):
            active = self.speech.poll(self.session, False, None)
        self.runtime.disconnect()
        with patch('backend.speech.time.monotonic', return_value=now + .1):
            self.assertIsNone(self.speech.poll(self.session, True, None))
        self.assertIsNotNone(active)

    def test_failed_playback_can_retry_instead_of_becoming_permanently_silent(self):
        now = self.feed('obstacle')
        self.dispatch(now)
        current = self.speech.active['id']
        with patch('backend.speech.time.monotonic', return_value=now + .1):
            self.speech.poll(self.session, False, current, 'test playback error')
        self.assertNotIn('obstacle', self.runtime.guidance.last_sent)
        self.assertEqual(self.runtime.guidance.delivery, 'playback_failed')

    def test_device_receives_serializable_audio_without_internal_policy(self):
        now = self.feed('stairs')
        self.dispatch(now)
        client = create_app(self.runtime, self.speech, 'test-device-token').test_client()
        with patch('backend.speech.time.monotonic', return_value=now):
            response = client.post('/device/poll', json={'session': self.session},
                                   headers={'X-Device-Token': 'test-device-token'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json['command']), {'id', 'text', 'wav'})
        self.assertEqual(response.json['command']['text'], CUES['stairs'].text)
