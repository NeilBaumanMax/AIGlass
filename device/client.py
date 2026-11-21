"""Pico Zero audio transport. Uses Python standard library and ALSA utilities."""
import argparse
import audioop
import base64
import json
import io
import ipaddress
import platform
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import queue
import re
import signal
import subprocess
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
import wave


def network_failure(exc):
    # HTTP errors mean the server was reached; don't disrupt Wi-Fi for them.
    if isinstance(exc, urllib.error.HTTPError):
        return False
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return isinstance(reason, OSError)


def error_detail(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return 'HTTP ' + str(exc.code)
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return type(reason).__name__ + ' errno=' + str(getattr(reason, 'errno', None))


def pin_hotspot_neighbor(server, server_mac, link):
    """Avoid broken ARP renewal only on the verified PC-hosted hotspot."""
    if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', server_mac):
        return False
    try:
        host = str(ipaddress.IPv4Address(urllib.parse.urlsplit(server).hostname))
        connected = re.search(r'Connected to ([0-9a-f:]{17})', link, re.I)
        if not connected or connected[1].lower() != server_mac:
            # A changed hotspot BSSID must not inherit our old permanent entry.
            neighbor = subprocess.run(['ip', 'neigh', 'show', 'to', host, 'dev', 'wlan0'],
                                      capture_output=True, text=True, timeout=3).stdout
            if server_mac in neighbor.lower() and 'PERMANENT' in neighbor:
                subprocess.run(['arp', '-i', 'wlan0', '-d', host],
                               capture_output=True, timeout=3)
            return False
        # BusyBox on this board supports arp -s, but not ip neigh replace.
        result = subprocess.run(['arp', '-i', 'wlan0', '-s', host, server_mac],
                                capture_output=True, timeout=3)
        return result.returncode == 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


class NetworkRecovery:
    """Repair a broken Wi-Fi association/ARP path, with a bounded retry rate."""
    def __init__(self, server):
        self.host = urllib.parse.urlsplit(server).hostname
        self.failures = 0
        self.next_attempt = 0.0

    def failed(self, exc):
        if not network_failure(exc):
            self.failures = 0
            return False
        self.failures += 1
        now = time.monotonic()
        if self.failures < 3 or now < self.next_attempt:
            return False
        self.next_attempt = now + 30
        try:
            # A hostname, remote route or healthy LAN neighbor must not be
            # treated as a failed local Wi-Fi neighbor.
            host = str(ipaddress.IPv4Address(self.host))
            link = subprocess.run(['iw', 'dev', 'wlan0', 'link'],
                                  capture_output=True, text=True, timeout=3)
            neighbor = subprocess.run(['ip', 'neigh', 'show', 'to', host, 'dev', 'wlan0'],
                                      capture_output=True, text=True, timeout=3)
            disconnected = link.returncode == 0 and 'Not connected' in link.stdout
            bad_neighbor = neighbor.returncode == 0 and any(
                state in neighbor.stdout.split() for state in ('INCOMPLETE', 'FAILED'))
            if not (disconnected or bad_neighbor):
                return False
            result = subprocess.run(['wpa_cli', '-i', 'wlan0', 'reassociate'],
                                    capture_output=True, text=True, timeout=3)
            recovered = result.returncode == 0 and 'OK' in result.stdout.split()
            logging.warning('Wi-Fi reassociation requested: %s', recovered)
            return recovered
        except (OSError, ValueError, subprocess.TimeoutExpired):
            logging.warning('Wi-Fi recovery command unavailable')
            return False


class Client:
    def __init__(self, server, token, server_mac=''):
        self.server = server.rstrip("/")
        self.token = token
        self.server_mac = server_mac
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.stop = threading.Event()
        self.muted = threading.Event()
        self.audio = queue.Queue(maxsize=3)
        self.session = ""
        self.recorder = self.player = None
        self.link_error = None

    def request(self, path, body, headers=None):
        request = urllib.request.Request(self.server + path, data=body, method="POST",
                                        headers={"X-Device-Token": self.token, **(headers or {})})
        try:
            with self.opener.open(request, timeout=6) as response:
                data = response.read()
                return json.loads(data) if data else {}
        except (urllib.error.URLError, OSError) as exc:
            self.link_error = exc
            raise

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
            logging.warning("Audio upload failed: %s", error_detail(exc))
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
            logging.warning("Playback link failed: %s", error_detail(exc))
            self.stop.set()

    def run(self):
        link = subprocess.run(['iw', 'dev', 'wlan0', 'link'], capture_output=True, text=True).stdout
        if pin_hotspot_neighbor(self.server, self.server_mac, link):
            logging.info('Verified hotspot server neighbor pinned')
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
    recovery = NetworkRecovery(config['server'])
    while True:
        client = Client(config["server"], config["token"], config.get('server_mac', ''))
        started = time.monotonic()
        try:
            client.run()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logging.warning("Connect failed: %s", error_detail(exc))
        if time.monotonic() - started > 30:
            recovery.failures = 0
        if client.link_error:
            recovery.failed(client.link_error)
        time.sleep(2)
