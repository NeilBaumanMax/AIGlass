import json
import unittest
from unittest.mock import Mock

from wake import WakeDetector


class WakeTests(unittest.TestCase):
    def detector(self, text):
        detector = WakeDetector.__new__(WakeDetector)
        detector.detector = Mock()
        detector.detector.is_ready.return_value = False
        detector.stream = Mock()
        detector.pronunciation = Mock()
        detector.pronunciation.AcceptWaveform.return_value = False
        detector.pronunciation.PartialResult.return_value = json.dumps({'partial': text})
        detector.reset = Mock()
        return detector

    def test_complete_partial_wakes_before_final_transcript_revises_it_away(self):
        detector = self.detector('嗨 伊 迪')
        self.assertTrue(detector.accept(bytes(6400)))
        detector.reset.assert_called_once()

    def test_greeting_name_unknown_and_unrelated_sentences_do_not_wake(self):
        for text in ('嗨', '伊 迪 丝', '嗨 [unk]', '你的 意思', '海 伊', '这 是 嗨 伊 迪'):
            with self.subTest(text=text):
                detector = self.detector(text)
                self.assertFalse(detector.accept(bytes(6400)))
                detector.reset.assert_not_called()
