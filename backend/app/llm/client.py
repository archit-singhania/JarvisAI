"""
LLM Client — Groq / Gemini / Ollama, full + streaming.
FIX: Groq client resets itself on 401 so a key change takes effect immediately.
FIX: stream_response no longer yields "Sorry I encountered an error" to the user —
     it raises so the caller can handle gracefully.
"""
import logging
from typing import AsyncGenerator, Dict, List, Optional, Any
from app.config import settings

logger = logging.getLogger("jarvis.llm")


class LLMClient:

    def __init__(self):
        self._groq_client = None
        self._gemini_model = None
        logger.info(f"LLMClient ready — {settings.LLM_PROVIDER} / {settings.LLM_MODEL}")

    @property
    def _s(self):
        return settings

    @property
    def groq_client(self):
        if self._groq_client is None:
            from groq import Groq
            if not self._s.has_groq():
                raise ValueError("GROQ_API_KEY not configured in .env")
            self._groq_client = Groq(api_key=self._s.GROQ_API_KEY)
        return self._groq_client

    def _reset_groq_client(self):
        """Force re-create client on next call (picks up new key from .env)."""
        self._groq_client = None

    def _build(
        self,
        messages: List[Dict],
        rag_context: Optional[Dict] = None,
        tool_results: Optional[Dict] = None,
        system_override: Optional[str] = None,
    ) -> List[Dict]:
        system = system_override or self._s.JARVIS_PERSONA

        if rag_context and rag_context.get("documents"):
            ctx = "\n\n".join(d["content"] for d in rag_context["documents"][:3])
            system += f"\n\nRelevant context:\n{ctx}"

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
        built = self._build(messages, rag_context, tool_results, system_prompt)
        try:
            p = self._s.LLM_PROVIDER
            if p == "groq":   return await self._groq_full(built)
            if p == "gemini": return await self._gemini_full(built)
            if p == "ollama": return await self._ollama_full(built)
            raise ValueError(f"Unknown provider: {p}")
        except Exception as e:
            self._handle_error(e)
            logger.error(f"LLM error: {e}", exc_info=True)
            return {"content": "I ran into an issue, please try again.", "error": str(e)}

    async def _groq_full(self, messages: List[Dict]) -> Dict:
        try:
            resp = self.groq_client.chat.completions.create(
                model=self._s.LLM_MODEL, messages=messages,
                temperature=self._s.TEMPERATURE, max_tokens=self._s.MAX_TOKENS,
                stream=False,
            )
            return {
                "content":  resp.choices[0].message.content,
                "model":    self._s.LLM_MODEL, "provider": "groq",
                "tokens":   {"prompt": resp.usage.prompt_tokens,
                             "completion": resp.usage.completion_tokens},
            }
        except Exception as e:
            self._handle_error(e); raise

    async def _gemini_full(self, messages: List[Dict]) -> Dict:
        import google.generativeai as genai
        if not self._gemini_model:
            genai.configure(api_key=self._s.GEMINI_API_KEY)
            self._gemini_model = genai.GenerativeModel(self._s.LLM_MODEL or "gemini-1.5-flash")
        history = []
        for m in messages:
            if m["role"] == "user":      history.append({"role":"user",  "parts":[m["content"]]})
            elif m["role"] == "assistant": history.append({"role":"model","parts":[m["content"]]})
        chat = self._gemini_model.start_chat(history=history[:-1] if history else [])
        resp = chat.send_message(messages[-1]["content"],
                                 generation_config={"temperature": self._s.TEMPERATURE,
                                                    "max_output_tokens": self._s.MAX_TOKENS})
        return {"content": resp.text, "provider": "gemini"}

    async def _ollama_full(self, messages: List[Dict]) -> Dict:
        import ollama
        resp = ollama.chat(model=self._s.OLLAMA_MODEL, messages=messages)
        return {"content": resp["message"]["content"], "provider": "ollama"}

    # ── Streaming ──────────────────────────────────────────────────

    async def stream_response(
        self,
        messages: List[Dict],
        rag_context: Optional[Dict] = None,
        tool_results: Optional[Dict] = None,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        built = self._build(messages, rag_context, tool_results, system_prompt)
        p = self._s.LLM_PROVIDER
        try:
            if p == "groq":
                async for chunk in self._groq_stream(built): yield chunk
            elif p == "ollama":
                async for chunk in self._ollama_stream(built): yield chunk
            else:
                resp = await self.generate_response(messages, rag_context, tool_results, system_prompt)
                yield resp["content"]
        except Exception as e:
            self._handle_error(e)
            logger.error(f"Stream error: {e}", exc_info=True)
            # Don't yield "Sorry..." — let caller handle it cleanly
            raise

    async def _groq_stream(self, messages: List[Dict]) -> AsyncGenerator[str, None]:
        try:
            stream = self.groq_client.chat.completions.create(
                model=self._s.LLM_MODEL, messages=messages,
                temperature=self._s.TEMPERATURE, max_tokens=self._s.MAX_TOKENS,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta: yield delta
        except Exception as e:
            self._handle_error(e); raise

    async def _ollama_stream(self, messages: List[Dict]) -> AsyncGenerator[str, None]:
        import ollama
        for chunk in ollama.chat(model=self._s.OLLAMA_MODEL, messages=messages, stream=True):
            c = chunk["message"]["content"]
            if c: yield c

    def _handle_error(self, e: Exception):
        """Reset cached clients on auth errors so new key is picked up."""
        err_str = str(e).lower()
        if "401" in err_str or "invalid api key" in err_str or "authentication" in err_str:
            logger.warning("Auth error — resetting Groq client (key may have changed)")
            self._reset_groq_client()
            # Also reload settings from .env so new key is used
            try:
                self._s.reload()
            except Exception:
                pass
