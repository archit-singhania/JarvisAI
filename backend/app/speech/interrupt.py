"""
Interrupt Handler — lets the user say "stop" or "hey jarvis" mid-response
and immediately halts TTS playback + LLM streaming.

Works by maintaining a shared cancellation event.
The streaming WebSocket handler checks this event between every token.
The TTS player checks it before each sentence chunk.
"""
import asyncio
import logging
import threading

logger = logging.getLogger("jarvis.interrupt")


class InterruptHandler:
    """
    Central interrupt bus.

    Usage:
        handler = InterruptHandler()

        # In streaming loop:
        async for token in llm.stream_response(...):
            if handler.is_interrupted:
                break
            await ws.send_json({"type": "stream_chunk", "content": token})

        # To trigger interrupt (from wake word or "stop" command):
        handler.interrupt()

        # To reset for next turn:
        handler.reset()
    """

    def __init__(self):
        self._event = threading.Event()
        self._async_event: asyncio.Event | None = None

    def interrupt(self):
        """Signal that the current response should stop."""
        logger.info("Interrupt triggered — stopping current response")
        self._event.set()
        if self._async_event:
            # Thread-safe set on the asyncio event
            try:
                loop = asyncio.get_event_loop()
                loop.call_soon_threadsafe(self._async_event.set)
            except Exception:
                pass

    def reset(self):
        """Clear interrupt for the next turn."""
        self._event.clear()
        if self._async_event:
            self._async_event.clear()

    @property
    def is_interrupted(self) -> bool:
        return self._event.is_set()

    def get_async_event(self, loop: asyncio.AbstractEventLoop) -> asyncio.Event:
        """Get (or create) an asyncio.Event tied to this interrupt."""
        if self._async_event is None:
            self._async_event = asyncio.Event()
        return self._async_event


# Global singleton used by orchestrator, streaming handler, and TTS
interrupt_handler = InterruptHandler()
