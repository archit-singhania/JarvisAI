"""
Main Orchestrator — coordinates LLM, Speech, Vision, RAG, Tools.
Phase 3: exposes _trim_history, supports scheduler + wake_listener hooks.
"""
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from app.config import settings

logger = logging.getLogger("jarvis.orchestrator")


class Orchestrator:

    def __init__(self):
        self.conversation_history: List[Dict] = []
        self.context: Dict[str, Any] = {}

        # Phase 3 hooks (set by main.py lifespan)
        self.scheduler    = None
        self.wake_listener = None

        # Lazy component handles
        self._llm_client        = None
        self._speech_processor  = None
        self._vision_processor  = None
        self._rag_engine        = None
        self._tool_manager      = None

        logger.info("Orchestrator initialised")

    # ── Lazy properties ────────────────────────────────────────────

    @property
    def llm_client(self):
        if self._llm_client is None:
            from app.llm.client import LLMClient
            self._llm_client = LLMClient()
        return self._llm_client

    @property
    def speech_processor(self):
        if self._speech_processor is None:
            from app.speech.processor import SpeechProcessor
            self._speech_processor = SpeechProcessor()
        return self._speech_processor

    @property
    def vision_processor(self):
        if self._vision_processor is None:
            from app.vision.processor import VisionProcessor
            self._vision_processor = VisionProcessor()
        return self._vision_processor

    @property
    def rag_engine(self):
        if self._rag_engine is None:
            from app.rag.engine import RAGEngine
            self._rag_engine = RAGEngine()
        return self._rag_engine

    @property
    def tool_manager(self):
        if self._tool_manager is None:
            from app.tools.manager import ToolManager
            self._tool_manager = ToolManager()
        return self._tool_manager

    # ── Text pipeline ──────────────────────────────────────────────

    async def process_text_input(
        self,
        user_input: str,
        use_rag: bool = True,
        use_tools: bool = True,
    ) -> Dict[str, Any]:
        try:
            logger.info(f"Processing: {user_input[:60]}...")

            self.conversation_history.append({
                "role": "user",
                "content": user_input,
                "timestamp": datetime.now().isoformat(),
            })
            self._trim_history()

            # 1. Tools
            tool_result = None
            if use_tools:
                tool_result = await self.tool_manager.detect_and_execute(user_input)
                if tool_result and tool_result.get("success"):
                    result_text = tool_result["result"]
                    if result_text.startswith("[RAP_MODE") or result_text.startswith("[SING_MODE"):
                        user_input = result_text
                        tool_result = None

            # 2. RAG
            rag_context = None
            if use_rag:
                rag_context = await self.rag_engine.query(user_input)

            # 3. LLM or tool short-circuit
            if tool_result and tool_result.get("success"):
                response_text = tool_result["result"]
            else:
                llm_resp = await self.llm_client.generate_response(
                    messages=self.conversation_history,
                    rag_context=rag_context,
                    tool_results=tool_result,
                )
                response_text = llm_resp["content"]

            self.conversation_history.append({
                "role": "assistant",
                "content": response_text,
                "timestamp": datetime.now().isoformat(),
            })

            return {
                "success": True,
                "response": response_text,
                "type": "text",
                "tool_used": tool_result["tool"] if tool_result else None,
                "rag_used": bool(rag_context and rag_context.get("documents")),
                "metadata": {"timestamp": datetime.now().isoformat()},
            }

        except Exception as e:
            logger.error(f"Text pipeline error: {e}", exc_info=True)
            return {"success": False, "error": str(e), "type": "error"}

    # ── Audio pipeline ─────────────────────────────────────────────

    async def process_audio_input(self, audio_data: bytes) -> Dict[str, Any]:
        try:
            transcription = await self.speech_processor.transcribe(audio_data)
            if not transcription.get("success"):
                return {"success": False, "error": "STT failed", "type": "error"}

            user_text = transcription["text"]

            # Check for interrupt commands in speech
            from app.speech.interrupt import interrupt_handler
            stop_words = {"stop", "cancel", "shut up", "be quiet", "silence"}
            if any(w in user_text.lower() for w in stop_words):
                interrupt_handler.interrupt()
                return {
                    "success": True,
                    "transcript": user_text,
                    "response": "Stopping.",
                    "type": "audio",
                    "tool_used": "interrupt",
                }

            text_response = await self.process_text_input(user_text)
            if not text_response.get("success"):
                return text_response

            audio_response = await self.speech_processor.synthesize(
                text_response["response"]
            )

            return {
                "success": True,
                "transcript": user_text,
                "response": text_response["response"],
                "audio": audio_response.get("audio_data"),
                "audio_format": audio_response.get("format", "wav"),
                "tool_used": text_response.get("tool_used"),
                "type": "audio",
            }
        except Exception as e:
            logger.error(f"Audio pipeline error: {e}", exc_info=True)
            return {"success": False, "error": str(e), "type": "error"}

    # ── Screen analysis ────────────────────────────────────────────

    async def analyze_screen(self, prompt: Optional[str] = None) -> Dict[str, Any]:
        try:
            screenshot = await self.vision_processor.capture_screen()
            analysis = await self.vision_processor.analyze(screenshot, prompt)
            if analysis.get("success"):
                self.conversation_history.append({
                    "role": "user",
                    "content": f"[Screen] {prompt or 'Describe my screen'}",
                    "timestamp": datetime.now().isoformat(),
                })
                self.conversation_history.append({
                    "role": "assistant",
                    "content": analysis["description"],
                    "timestamp": datetime.now().isoformat(),
                })
            return {"success": True, "analysis": analysis.get("description", ""),
                    "type": "vision"}
        except Exception as e:
            return {"success": False, "error": str(e), "type": "error"}

    # ── Image input ────────────────────────────────────────────────

    async def process_image_input(
        self, image_data: bytes, prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        try:
            analysis = await self.vision_processor.analyze(image_data, prompt)
            return {"success": True, "analysis": analysis.get("description", ""),
                    "type": "vision"}
        except Exception as e:
            return {"success": False, "error": str(e), "type": "error"}

    # ── Helpers ────────────────────────────────────────────────────

    def _trim_history(self):
        max_msgs = settings.MAX_CONTEXT_MESSAGES * 2
        if len(self.conversation_history) > max_msgs:
            self.conversation_history = self.conversation_history[-max_msgs:]

    def clear_history(self):
        self.conversation_history = []
        logger.info("Conversation history cleared")

    def get_history(self) -> List[Dict]:
        return self.conversation_history


orchestrator = Orchestrator()
