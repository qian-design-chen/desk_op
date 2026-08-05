"""麦克风录音模块，输出 16kHz 单声道 16bit PCM 字节。"""

import threading
import wave

import sounddevice as sd


class MicRecorder:
    """后台线程持续录音，stop() 返回全部 PCM 字节。"""

    def __init__(self, sample_rate=16000, channels=1, block_frames=3200):
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_frames = block_frames
        self._chunks = []
        self._stop = threading.Event()
        self._thread = None
        self._error = None

    @property
    def recording(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.recording:
            return
        self._chunks = []
        self._stop.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="mic-recorder"
        )
        self._thread.start()

    def _run(self):
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.block_frames,
                callback=self._callback,
            ):
                self._stop.wait()
        except Exception as exc:
            self._error = exc

    def _callback(self, indata, frames, time_info, status):
        if self._stop.is_set():
            raise sd.CallbackAbort
        self._chunks.append(indata.copy().tobytes())

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread:
            thread.join(timeout=6)
        if self._error:
            error = self._error
            self._error = None
            raise error
        pcm = b"".join(self._chunks)
        self._chunks = []
        self._thread = None
        return pcm


def save_wav(path, pcm, sample_rate=16000):
    """把 PCM 字节写成标准 WAV 文件。"""
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
