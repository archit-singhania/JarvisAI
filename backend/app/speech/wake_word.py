"""Optional installed ONNX wake-word engine. Startup verifies model and input."""
import asyncio
import logging
import threading
from app.config import settings

logger = logging.getLogger('wednesday.wakeword')


class WakeWordListener:
    def __init__(self,on_detected):
        self.on_detected = on_detected
        self._running = False
        self._thread = None
        self._audio_stream = None
        self._pa = None
        self._ready = threading.Event()
        self._error = None
        self._loop = None

    def start(self):
        if self._running:
            return
        # start() may be called in a worker; callback schedules safely onto the
        # loop captured by the API through call_soon_threadsafe below.
        self._running = True
        self._thread = threading.Thread(target=self._listen,daemon=True)
        self._thread.start()
        if not self._ready.wait(15):
            self.stop()
            raise RuntimeError('Wake-word startup timed out')
        if self._error:
            self.stop()
            raise RuntimeError('Wake-word initialization failed') from self._error

    def stop(self):
        self._running = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _listen(self):
        try:
            import numpy as np
            import pyaudio
            from openwakeword.model import Model
            model_path = settings.MODELS_DIR/'wakeword'/'hey_jarvis.onnx'
            if not model_path.is_file():
                raise FileNotFoundError('Install models/wakeword/hey_jarvis.onnx explicitly')
            model = Model(wakeword_models=[str(model_path)],inference_framework='onnx')
            self._pa = pyaudio.PyAudio()
            self._audio_stream = self._pa.open(rate=16000,channels=1,format=pyaudio.paInt16,input=True,frames_per_buffer=1280)
            self._ready.set()
            while self._running:
                frames = self._audio_stream.read(1280,exception_on_overflow=False)
                prediction = model.predict(np.frombuffer(frames,dtype=np.int16))
                if any(score>=settings.WAKE_WORD_SENSITIVITY for score in prediction.values()):
                    model.reset()
                    self.on_detected()
        except Exception as error:
            self._error = error
            self._ready.set()
            logger.error('Wake-word engine unavailable: %s',type(error).__name__)
        finally:
            self._running = False
            if self._audio_stream:
                try:
                    self._audio_stream.stop_stream()
                    self._audio_stream.close()
                except Exception:
                    pass
            if self._pa:
                self._pa.terminate()
