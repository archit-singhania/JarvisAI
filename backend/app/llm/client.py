"""
LLM Client — multi-provider with streaming.
Groq model updated: llama-3.1-70b-versatile → llama-3.3-70b-versatile
"""
import logging
from typing import AsyncGenerator, Dict, List, Optional, Any
from groq import Groq
import google.generativeai as genai

from app.config import settings

logger = logging.getLogger("jarvis.llm")

_JARVIS_SYSTEM = """You are Jarvis, Tony Stark's AI assistant — brilliant, witty, and efficient.
You have a dry sense of humour but never waste words.
Keep answers concise and conversational unless depth is genuinely needed.
When rapping or singing, be creative and rhythmic.
When telling jokes, be sharp and punchy.
Never say you're an AI unless directly asked."""


class LLMClient:

    def __init__(self):
        self.provider = settings.LLM_PROVIDER
        self._groq_client = None
        self._gemini_model = None
        logger.info(f"LLMClient ready — provider: {self.provider}, model: {settings.LLM_MODEL}")

    @property
    def groq_client(self):
        if self._groq_client is None:
            if not settings.GROQ_API_KEY:
                raise ValueError("GROQ_API_KEY not set in .env")
            self._groq_client = Groq(api_key=settings.GROQ_API_KEY)
        return self._groq_client

    @property
    def gemini_model(self):
        if self._gemini_model is None:
            if not settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not set")
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self._gemini_model = genai.GenerativeModel(settings.LLM_MODEL or "gemini-1.5-flash")
        return self._gemini_model

    # ── Build messages ─────────────────────────────────────────────

    def _build_messages(
        self,
        messages: List[Dict],
        rag_context: Optional[Dict] = None,
        tool_results: Optional[Dict] = None,
        system_override: Optional[str] = None,
    ) -> List[Dict]:
        system = system_override or _JARVIS_SYSTEM

        if rag_context and rag_context.get("documents"):
            ctx = "\n\n".join(d["content"] for d in rag_context["documents"][:3])
            system += f"\n\nRelevant context from memory:\n{ctx}"

        if tool_results:
            system += f"\n\nTool result: {tool_results}"

        built = [{"role": "system", "content": system}]
        for m in messages:
            if m.get("role") in ("user", "assistant"):
                built.append({"role": m["role"], "content": m["content"]})
        return built

    # ── Full response ──────────────────────────────────────────────

    async def generate_response(
        self,
        messages: List[Dict],
        rag_context: Optional[Dict] = None,
        tool_results: Optional[Dict] = None,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        built = self._build_messages(messages, rag_context, tool_results, system_prompt)
        try:
            if self.provider == "groq":
                return await self._groq_full(built)
            elif self.provider == "gemini":
                return await self._gemini_full(built)
            elif self.provider == "ollama":
                return await self._ollama_full(built)
            else:
                raise ValueError(f"Unknown provider: {self.provider}")
        except Exception as e:
            logger.error(f"LLM error: {e}", exc_info=True)
            return {"content": "I ran into an issue — please try again.", "error": str(e)}

    async def _groq_full(self, messages: List[Dict]) -> Dict:
        resp = self.groq_client.chat.completions.create(
            model=settings.LLM_MODEL,   # llama-3.3-70b-versatile
            messages=messages,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
            stream=False,
        )
        return {
            "content": resp.choices[0].message.content,
            "model": settings.LLM_MODEL,
            "provider": "groq",
            "tokens": {
                "prompt": resp.usage.prompt_tokens,
                "completion": resp.usage.completion_tokens,
            },
        }

    async def _gemini_full(self, messages: List[Dict]) -> Dict:
        history, prompt = [], ""
        for m in messages:
            if m["role"] == "system":
                prompt = m["content"] + "\n\n"
            elif m["role"] == "user":
                history.append({"role": "user", "parts": [m["content"]]})
            elif m["role"] == "assistant":
                history.append({"role": "model", "parts": [m["content"]]})
        chat = self.gemini_model.start_chat(history=history[:-1] if history else [])
        resp = chat.send_message(
            messages[-1]["content"],
            generation_config={
                "temperature": settings.TEMPERATURE,
                "max_output_tokens": settings.MAX_TOKENS,
            },
        )
        return {"content": resp.text, "model": settings.LLM_MODEL, "provider": "gemini"}

    async def _ollama_full(self, messages: List[Dict]) -> Dict:
        import ollama
        resp = ollama.chat(model=settings.OLLAMA_MODEL, messages=messages)
        return {
            "content": resp["message"]["content"],
            "model": settings.OLLAMA_MODEL,
            "provider": "ollama",
        }

    # ── Streaming ──────────────────────────────────────────────────

    async def stream_response(
        self,
        messages: List[Dict],
        rag_context: Optional[Dict] = None,
        tool_results: Optional[Dict] = None,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        built = self._build_messages(messages, rag_context, tool_results, system_prompt)
        try:
            if self.provider == "groq":
                async for chunk in self._groq_stream(built):
                    yield chunk
            elif self.provider == "ollama":
                async for chunk in self._ollama_stream(built):
                    yield chunk
            else:
                resp = await self.generate_response(
                    messages, rag_context, tool_results, system_prompt
                )
                yield resp["content"]
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield "Sorry, I encountered an error while streaming."

    async def _groq_stream(self, messages: List[Dict]) -> AsyncGenerator[str, None]:
        stream = self.groq_client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def _ollama_stream(self, messages: List[Dict]) -> AsyncGenerator[str, None]:
        import ollama
        stream = ollama.chat(
            model=settings.OLLAMA_MODEL, messages=messages, stream=True
        )
        for chunk in stream:
            content = chunk["message"]["content"]
            if content:
                yield content
