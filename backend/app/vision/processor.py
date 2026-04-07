"""
Vision Processor — analyze images via LLaVA (Ollama, free local) or GPT-4o-mini fallback.
"""
import base64
import logging
from typing import Optional

logger = logging.getLogger("jarvis.vision")


class VisionProcessor:
    def __init__(self):
        from app.config import settings
        self.settings = settings
        logger.info("VisionProcessor initialised")

    async def analyze(self, image_data: bytes, prompt: Optional[str] = None) -> dict:
        """Analyze an image and return a description."""
        prompt = prompt or "Describe this image in detail. If there is text or code, transcribe it."
        try:
            return await self._analyze_ollama(image_data, prompt)
        except Exception as e:
            logger.warning(f"Ollama vision failed ({e}), trying OpenAI fallback")
            return await self._analyze_openai(image_data, prompt)

    async def _analyze_ollama(self, image_data: bytes, prompt: str) -> dict:
        """LLaVA via Ollama — 100% free, runs locally."""
        import ollama

        b64 = base64.b64encode(image_data).decode("utf-8")
        response = ollama.chat(
            model=self.settings.OLLAMA_VISION_MODEL,  # llava:13b
            messages=[{
                "role": "user",
                "content": prompt,
                "images": [b64],
            }],
        )
        description = response["message"]["content"]
        return {"success": True, "description": description, "provider": "ollama_llava"}

    async def _analyze_openai(self, image_data: bytes, prompt: str) -> dict:
        """GPT-4o-mini fallback (requires OPENAI_API_KEY, paid but cheap)."""
        import openai

        if not self.settings.OPENAI_API_KEY:
            return {"success": False, "description": "", "error": "No OpenAI key configured"}

        client = openai.AsyncOpenAI(api_key=self.settings.OPENAI_API_KEY)
        b64 = base64.b64encode(image_data).decode("utf-8")
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=500,
        )
        description = response.choices[0].message.content
        return {"success": True, "description": description, "provider": "openai_gpt4o_mini"}

    async def capture_screen(self) -> bytes:
        """Take a screenshot and return as bytes (for 'Hey Jarvis, what's on my screen?')."""
        import mss
        import io
        from PIL import Image

        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
