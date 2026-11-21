"""SpeexDSP acoustic echo cancellation with synchronized codec loopback."""
import ctypes as C
from pathlib import Path

import numpy as np

DLL = Path(__file__).resolve().parent / '.tools/speexdsp/mingw64/bin/libspeexdsp-1.dll'


class EchoCanceller:
    frame_size = 320  # 20 ms at 16 kHz

    def __init__(self):
        self.lib = C.CDLL(str(DLL))
        self.lib.speex_echo_state_init.argtypes = [C.c_int, C.c_int]
        self.lib.speex_echo_state_init.restype = C.c_void_p
        self.lib.speex_echo_ctl.argtypes = [C.c_void_p, C.c_int, C.c_void_p]
        self.lib.speex_echo_cancellation.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p]
        self.lib.speex_echo_state_destroy.argtypes = [C.c_void_p]
        self.lib.speex_preprocess_state_init.argtypes = [C.c_int, C.c_int]
        self.lib.speex_preprocess_state_init.restype = C.c_void_p
        self.lib.speex_preprocess_ctl.argtypes = [C.c_void_p, C.c_int, C.c_void_p]
        self.lib.speex_preprocess_run.argtypes = [C.c_void_p, C.c_void_p]
        self.lib.speex_preprocess_state_destroy.argtypes = [C.c_void_p]
        self.state = self.lib.speex_echo_state_init(self.frame_size, 6400)
        rate = C.c_int(16000)
        self.lib.speex_echo_ctl(self.state, 24, C.byref(rate))
        self.pre = self.lib.speex_preprocess_state_init(self.frame_size, 16000)
        self.lib.speex_preprocess_ctl(self.pre, 24, self.state)
        denoise = C.c_int(0)
        self.lib.speex_preprocess_ctl(self.pre, 0, C.byref(denoise))
        value = C.c_int(-35)
        self.lib.speex_preprocess_ctl(self.pre, 20, C.byref(value))
        active = C.c_int(-12)
        self.lib.speex_preprocess_ctl(self.pre, 22, C.byref(active))
        self.metrics = {}
        self.echo_hold = 0

    def process(self, stereo):
        samples = np.frombuffer(stereo, dtype='<i2').reshape(-1, 2)
        if len(samples) % self.frame_size:
            raise ValueError('AEC requires complete 20 ms frames')
        mic = samples[:, 0].astype(np.float64)
        mic = np.clip(mic - mic.mean(), -32768, 32767).astype('<i2')
        ref = np.ascontiguousarray(samples[:, 1])
        output = np.zeros_like(mic)
        for i in range(0, len(mic), self.frame_size):
            self.lib.speex_echo_cancellation(self.state, mic[i:].ctypes.data,
                                            ref[i:].ctypes.data, output[i:].ctypes.data)
            if np.max(np.abs(ref[i:i+self.frame_size].astype(np.int32))) > 20:
                self.echo_hold = 6400
            else:
                self.echo_hold = max(0, self.echo_hold - self.frame_size)
            if self.echo_hold:
                self.lib.speex_preprocess_run(self.pre, output[i:].ctypes.data)
            else:
                # With no speaker reference, preserve even quiet near-end
                # speech exactly; do not classify it as suppressible noise.
                output[i:i+self.frame_size] = mic[i:i+self.frame_size]
        rms = lambda x: float(np.sqrt(np.mean(x.astype(float) ** 2)))
        self.metrics = {'input_rms': round(rms(mic)), 'output_rms': round(rms(output)),
                        'reference_rms': round(rms(ref))}
        return output.tobytes()

    def close(self):
        if self.state:
            self.lib.speex_preprocess_state_destroy(self.pre)
            self.lib.speex_echo_state_destroy(self.state)
            self.state = None
