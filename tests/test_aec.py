import unittest
import numpy as np
from aec import DLL, EchoCanceller


@unittest.skipUnless(DLL.exists(), 'Install the optional SpeexDSP runtime first')
class AECTests(unittest.TestCase):
    def test_quiet_voice_without_speaker_is_not_suppressed(self):
        mic = np.tile(np.array([12, -12], dtype='<i2'), 1600)
        stereo = np.column_stack((mic,np.zeros_like(mic))).astype('<i2').tobytes()
        aec = EchoCanceller()
        try:
            self.assertEqual(aec.process(stereo), mic.tobytes())
        finally:
            aec.close()

    def test_known_echo_is_removed_and_near_speech_survives(self):
        rng = np.random.default_rng(7)
        ref = rng.normal(0, 2500, 16000 * 6)
        echo = np.roll(ref, 160) * .2
        echo[:160] = 0
        near = np.zeros_like(echo)
        near[16000*4:] = np.sin(np.arange(16000*2)*2*np.pi*330/16000)*700
        mic = echo + near + rng.normal(0, 3, len(ref))
        stereo = np.column_stack((mic,ref)).astype('<i2').tobytes()
        aec = EchoCanceller()
        try:
            out = b''.join(aec.process(stereo[i:i+12800]) for i in range(0,len(stereo),12800))
        finally:
            aec.close()
        clean = np.frombuffer(out,'<i2').astype(float)
        self.assertLess(clean[32000:64000].std(), echo[32000:64000].std()*.35)
        self.assertGreater(clean[80000:].std(), 100)
