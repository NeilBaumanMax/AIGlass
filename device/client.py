"""Pico Zero audio transport. Uses Python standard library and ALSA utilities."""
import argparse
import audioop
import base64
import json
import io
import platform
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
import urllib.request
import wave


class Client:
    def __init__(self, server, token):
        self.server = server.rstrip("/")
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.stop = threading.Event()
        self.muted = threading.Event()
        self.audio = queue.Queue(maxsize=3)
        self.session = ""
        self.recorder = self.player = None

    def request(self, path, body, headers=None):
        request = urllib.request.Request(self.server + path, data=body, method="POST",
                                        headers={"X-Device-Token": self.token, **(headers or {})})
        with self.opener.open(request, timeout=6) as response:
            data = response.read()
            return json.loads(data) if data else {}

    def capture(self):
        sequence = 0
        try:
            self.recorder = subprocess.Popen([
                "arecord", "-q", "-D", "hw:0,0", "-t", "raw", "-f", "S16_LE",
                "-r", "16000", "-c", "2", "--buffer-size=6400", "--period-size=1600",
            ], stdout=subprocess.PIPE)
            # The codec has a settling transient immediately after opening.
            while not self.stop.is_set():
                block = self.recorder.stdout.read(12800)
                if len(block) != 12800:
                    raise RuntimeError("arecord stopped")
                sequence += 1
                if sequence <= 10:
                    continue
                item = (sequence, block, self.muted.is_set(), time.monotonic())
                try:
                    self.audio.put_nowait(item)
                except queue.Full:
                    try:
                        self.audio.get_nowait()
                    except queue.Empty:
                        pass
                    self.audio.put_nowait(item)
        except Exception as exc:
            logging.warning("Capture failed: %s", type(exc).__name__)
            self.stop.set()

    def upload(self):
        try:
            while not self.stop.is_set():
                try:
                    seq, data, muted, captured = self.audio.get(timeout=.5)
                except queue.Empty:
                    continue
                if time.monotonic() - captured > 1:
                    continue
                self.request("/device/audio", data, {
                    "Content-Type": "application/octet-stream", "X-Session": self.session,
                    "X-Sequence": str(seq), "X-Muted": "1" if muted or self.muted.is_set() else "0",
                    "X-Audio-Format": "mic-reference",
                })
        except Exception as exc:
            logging.warning("Audio upload failed: %s", type(exc).__name__)
            self.stop.set()

    def playback(self):
        current = done = None
        error = ""
        mute_until = 0
        try:
            while not self.stop.is_set():
                playing = self.player is not None and self.player.poll() is None
                if self.player and not playing:
                    done = current
                    error = "" if self.player.returncode == 0 else "aplay exit " + str(self.player.returncode)
                    self.player = None
                    mute_until = time.monotonic() + .6
                body = {"session": self.session, "playing": playing or time.monotonic() < mute_until,
                        "done": done, "error": error, "current": current}
                result = self.request("/device/poll", json.dumps(body).encode(),
                                      {"Content-Type": "application/json"})
                command = result.get("command")
                command_id = command["id"] if command else None
                if command_id != current:
                    if self.player and self.player.poll() is None:
                        self.player.terminate()
                        self.player.wait(timeout=2)
                        self.player = None
                    current = command_id
                    if command:
                        self.muted.set()
                        wav = base64.b64decode(command["wav"])
                        if not wav:
                            done, error = current, "服务器未提供语音文件"
                        else:
                            with wave.open(io.BytesIO(wav)) as source:
                                pcm = source.readframes(source.getnframes())
                                if source.getnchannels() == 2:
                                    pcm = audioop.tomono(pcm, 2, .5, .5)
                                pcm = audioop.ratecv(pcm, 2, 1, source.getframerate(), 16000, None)[0]
                            path = Path("/tmp/aiglass-play.wav")
                            with wave.open(str(path), 'wb') as output:
                                output.setparams((1, 2, 16000, 0, 'NONE', 'NONE'))
                                output.writeframes(pcm)
                            self.player = subprocess.Popen(["aplay", "-q", "-D", "plughw:0,0", str(path)])
                            logging.info("Playing message %s", current)
                if self.player or time.monotonic() < mute_until:
                    self.muted.set()
                else:
                    self.muted.clear()
                self.stop.wait(.15)
        except Exception as exc:
            logging.warning("Playback link failed: %s", type(exc).__name__)
            self.stop.set()

    def run(self):
        link = subprocess.run(['iw', 'dev', 'wlan0', 'link'], capture_output=True, text=True).stdout
        ssid = next((line.split(':', 1)[1].strip() for line in link.splitlines() if 'SSID:' in line), '')
        body = {'os': 'Buildroot Linux ' + platform.release(), 'hostname': platform.node(),
                'ssid': ssid, 'audio_mode': 'mic-reference'}
        self.session = self.request("/device/session", json.dumps(body).encode(),
                                    {'Content-Type': 'application/json'})["session"]
        # Apply after association: the Wi-Fi interface may not exist at boot.
        # Continuous microphone traffic needs low-latency delivery.
        subprocess.run(["iw", "dev", "wlan0", "set", "power_save", "off"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logging.info("Connected to audio server")
        workers = [threading.Thread(target=target, daemon=True)
                   for target in (self.capture, self.upload, self.playback)]
        for worker in workers:
            worker.start()
        try:
            while not self.stop.wait(1):
                pass
        finally:
            self.stop.set()
            for process in (self.recorder, self.player):
                if process and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=2)
            for worker in workers:
                worker.join(timeout=7)


if __name__ == "__main__":
    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[RotatingFileHandler("/tmp/aiglass-client.log",
                                  maxBytes=128 * 1024, backupCount=1)])
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/userdata/aiglass/config.json")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    subprocess.run(["amixer", "cset", "name=ADC Mode", "SingadcL"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["amixer", "cset", "name=I2STDM Digital Loopback Mode", "Mode2"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["amixer", "cset", "name=ADC ALC Left Volume", "12"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["amixer", "cset", "name=ADC MICBIAS Voltage", "4"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["amixer", "cset", "name=ADC HPF Cut-off", "Off"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["amixer", "cset", "name=DAC LINEOUT Volume", "23"], check=True, stdout=subprocess.DEVNULL)
    while True:
        try:
            Client(config["server"], config["token"]).run()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logging.warning("Connect failed: %s", type(exc).__name__)
        time.sleep(2)
