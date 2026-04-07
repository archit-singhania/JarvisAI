"""
Wake Word Listener — "Hey Jarvis" triggers the assistant.

Uses openwakeword — 100% free, no API key, fully offline.
Install: pip install openwakeword pyaudio numpy

IMPORTANT: openwakeword models are NOT bundled with the pip package.
They must be downloaded once before use. This file handles that automatically.
"""
import logging
import struct
import threading
from typing import Callable, Optional

logger = logging.getLogger("jarvis.wakeword")


def download_models():
    """
    Download openwakeword pre-trained models on first run.
    This is a one-time operation (~20MB). Models are saved locally.
    """
    try:
        import openwakeword
        openwakeword.utils.download_models()
        logger.info("openwakeword models downloaded/verified")
    except Exception as e:
        logger.warning(f"Could not download openwakeword models: {e}")


class WakeWordListener:
    """Listens for 'Hey Jarvis' using openwakeword (free, no API key)."""

    def __init__(self, on_detected: Callable[[], None]):
        self.on_detected = on_detected
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._audio_stream = None

    def start(self):
        if self._running:
            return
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

    def _listen_loop(self):
        try:
            self._listen_openwakeword()
        except ImportError:
            logger.warning(
                "openwakeword not installed. Run: pip install openwakeword\n"
                "Falling back to energy-based detection."
            )
            self._listen_energy_fallback()
        except Exception as e:
            logger.error(f"Wake word error: {e}", exc_info=True)
            logger.info("Falling back to energy-based detection")
            self._listen_energy_fallback()

    def _listen_openwakeword(self):
        """
        openwakeword — free, no key needed.
        Uses the built-in 'hey_jarvis' model.

        Models must be downloaded first — this is handled automatically.
        """
        import numpy as np
        import pyaudio
        from openwakeword.model import Model
        import openwakeword

        # Download models if not already present (one-time, ~20MB)
        logger.info("Checking/downloading openwakeword models...")
        try:
            openwakeword.utils.download_models()
        except Exception as e:
            logger.warning(f"Model download warning (may already exist): {e}")

        RATE      = 16000
        CHUNK     = 1280     # 80ms — openwakeword required frame size
        THRESHOLD = 0.5      # raise to reduce false positives

        oww_model = Model(
            wakeword_models=["hey_jarvis"],
            inference_framework="onnx",
        )

        pa = pyaudio.PyAudio()
        self._audio_stream = pa.open(
            rate=RATE,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=CHUNK,
        )

        logger.info(f"openwakeword active — say 'Hey Jarvis' (threshold={THRESHOLD})")

        while self._running:
            pcm = self._audio_stream.read(CHUNK, exception_on_overflow=False)
            audio_data = np.frombuffer(pcm, dtype=np.int16)
            prediction = oww_model.predict(audio_data)

            for model_name, score in prediction.items():
                if score >= THRESHOLD:
                    logger.info(f"Wake word '{model_name}' detected! (score={score:.2f})")
                    oww_model.reset()
                    self.on_detected()
                    break

        self._audio_stream.stop_stream()
        self._audio_stream.close()
        pa.terminate()

    def _listen_energy_fallback(self):
        """
        No ML fallback — fires on any loud burst after silence.
        Works without openwakeword for basic testing.
        """
        import math
        import pyaudio

        CHUNK     = 1024
        RATE      = 16000
        THRESHOLD = 0.025
        SILENCE_S = 1.5

        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )

        logger.info("Energy fallback active (any loud sound triggers)")

        silence_needed = int(RATE / CHUNK * SILENCE_S)
        silent_chunks  = 0
        armed          = True

        while self._running:
            data   = stream.read(CHUNK, exception_on_overflow=False)
            shorts = struct.unpack("%dh" % (len(data) // 2), data)
            rms    = math.sqrt(sum(s * s for s in shorts) / len(shorts)) / 32768.0

            if armed and rms > THRESHOLD:
                logger.info(f"Energy burst detected (rms={rms:.3f})")
                self.on_detected()
                armed         = False
                silent_chunks = 0
            elif not armed:
                if rms < THRESHOLD:
                    silent_chunks += 1
                    if silent_chunks >= silence_needed:
                        armed = True
                else:
                    silent_chunks = 0

        stream.stop_stream()
        stream.close()
        pa.terminate()
