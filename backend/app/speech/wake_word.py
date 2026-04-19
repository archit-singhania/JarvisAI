"""
Wake Word Listener — Phase 4 final.
FIX: asyncio.create_task() cannot be called from a background thread.
     We now store the event loop at start() time and use loop.call_soon_threadsafe().
"""
import logging
import struct
import threading
from typing import Callable, Optional

logger = logging.getLogger("jarvis.wakeword")


class WakeWordListener:

    def __init__(self, on_detected: Callable[[], None]):
        self.on_detected = on_detected
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._audio_stream = None
        self._loop = None  # main asyncio loop, stored at start() time

    def start(self):
        if self._running:
            return
        # Capture the running event loop from the main thread NOW
        import asyncio
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = None

        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("Wake word listener started")

    def stop(self):
        self._running = False
        if self._audio_stream:
            try:
                self._audio_stream.stop_stream()
                self._audio_stream.close()
            except Exception:
                pass
        logger.info("Wake word listener stopped")

    def _fire(self):
        """Thread-safe callback — schedules on_detected on the asyncio event loop."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self.on_detected)
        else:
            try:
                self.on_detected()
            except Exception as e:
                logger.warning(f"Wake callback error: {e}")

    def _listen_loop(self):
        try:
            self._listen_openwakeword()
        except ImportError:
            logger.warning("openwakeword not installed — energy fallback")
            self._listen_energy_fallback()
        except Exception as e:
            logger.error(f"Wake word error: {e}", exc_info=True)
            logger.info("Falling back to energy-based detection")
            self._listen_energy_fallback()

    def _listen_openwakeword(self):
        import numpy as np
        import pyaudio
        from openwakeword.model import Model
        import openwakeword

        logger.info("Checking/downloading openwakeword models...")
        try:
            openwakeword.utils.download_models()
        except Exception as e:
            logger.warning(f"Model check note: {e}")

        RATE      = 16000
        CHUNK     = 1280
        THRESHOLD = 0.5

        oww_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")

        pa = pyaudio.PyAudio()
        self._audio_stream = pa.open(
            rate=RATE, channels=1, format=pyaudio.paInt16,
            input=True, frames_per_buffer=CHUNK,
        )
        logger.info(f"openwakeword active — say 'Hey Jarvis' (threshold={THRESHOLD})")

        while self._running:
            pcm        = self._audio_stream.read(CHUNK, exception_on_overflow=False)
            audio_data = np.frombuffer(pcm, dtype=np.int16)
            prediction = oww_model.predict(audio_data)

            for model_name, score in prediction.items():
                if score >= THRESHOLD:
                    logger.info(f"Wake word '{model_name}' detected! (score={score:.2f})")
                    oww_model.reset()
                    self._fire()  # ← thread-safe
                    break

        self._audio_stream.stop_stream()
        self._audio_stream.close()
        pa.terminate()

    def _listen_energy_fallback(self):
        import math
        import pyaudio

        CHUNK = 1024; RATE = 16000; THRESHOLD = 0.025; SILENCE_S = 1.5
        pa = pyaudio.PyAudio()
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE,
                         input=True, frames_per_buffer=CHUNK)
        logger.info("Energy fallback active (any speech triggers)")

        silence_needed = int(RATE / CHUNK * SILENCE_S)
        silent_chunks = 0; armed = True

        while self._running:
            data   = stream.read(CHUNK, exception_on_overflow=False)
            shorts = struct.unpack("%dh" % (len(data) // 2), data)
            rms    = (sum(s * s for s in shorts) / len(shorts)) ** 0.5 / 32768.0

            if armed and rms > THRESHOLD:
                logger.info(f"Speech detected (rms={rms:.3f})")
                self._fire()  # ← thread-safe
                armed = False; silent_chunks = 0
            elif not armed:
                silent_chunks = (silent_chunks + 1) if rms < THRESHOLD else 0
                if silent_chunks >= silence_needed:
                    armed = True

        stream.stop_stream(); stream.close(); pa.terminate()
